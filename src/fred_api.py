import argparse
import json
import logging
import math
import os
from pathlib import Path
import time
import tempfile

import pandas as pd
import requests
from dotenv import load_dotenv


LOGGER = logging.getLogger(__name__)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
OUTPUT_CSV_PATH = PROJECT_ROOT / "data" / "macro_data.csv"
CACHE_DIR = PROJECT_ROOT / "data" / "cache"

FRED_OBSERVATIONS_ENDPOINT = (
    "https://api.stlouisfed.org/fred/series/observations"
)

SERIES_IDS = [
    "UNRATE",
    "FEDFUNDS",
    "CPIAUCSL",
    "DGS10",
    "T10Y2Y",
]

SERIES_METADATA = {
    "UNRATE": {
        "series_name": "Unemployment Rate",
        "unit": "Percent",
        "frequency": "Monthly",
        "seasonal_adjustment": "Seasonally Adjusted",
        "source_name": "U.S. Bureau of Labor Statistics",
    },
    "FEDFUNDS": {
        "series_name": "Federal Funds Effective Rate",
        "unit": "Percent",
        "frequency": "Monthly",
        "seasonal_adjustment": "Not Seasonally Adjusted",
        "source_name": (
            "Board of Governors of the Federal Reserve System (US)"
        ),
    },
    "CPIAUCSL": {
        "series_name": (
            "Consumer Price Index for All Urban Consumers: All Items"
        ),
        "unit": "Index 1982-1984=100",
        "frequency": "Monthly",
        "seasonal_adjustment": "Seasonally Adjusted",
        "source_name": "U.S. Bureau of Labor Statistics",
    },
    "DGS10": {
        "series_name": (
            "10-Year Treasury Constant Maturity Market Yield"
        ),
        "unit": "Percent",
        "frequency": "Daily",
        "seasonal_adjustment": "Not Seasonally Adjusted",
        "source_name": (
            "Board of Governors of the Federal Reserve System (US)"
        ),
    },
    "T10Y2Y": {
        "series_name": (
            "10-Year Treasury Constant Maturity Minus "
            "2-Year Treasury Constant Maturity"
        ),
        "unit": "Percent",
        "frequency": "Daily",
        "seasonal_adjustment": "Not Seasonally Adjusted",
        "source_name": "Federal Reserve Bank of St. Louis",
    },
}

OBSERVATION_START = "2019-01-01"
OBSERVATION_END = "2024-12-31"
SORT_ORDER = "asc"
REQUEST_TIMEOUT_SECONDS = 30
REQUEST_INTERVAL_SECONDS = 0.6
CACHE_MAX_AGE_HOURS = 24
MAX_RETRIES = 4
BACKOFF_BASE_SECONDS = 1.0
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


class TransientRequestError(RuntimeError):
    """A temporary request failure that persisted after retries."""


def load_fred_api_key(env_path):
    """Load the FRED key from the project environment."""
    load_dotenv(dotenv_path=env_path, override=False)
    fred_api_key = os.getenv("FRED_API_KEY")

    invalid_key_values = {
        None,
        "",
        "replace_with_your_fred_api_key",
    }

    if fred_api_key in invalid_key_values:
        raise ValueError(
            "FRED_API_KEY is missing. "
            "Set it in the project's .env file."
        )

    return fred_api_key


def cache_age_hours(cache_path):
    if not cache_path.exists():
        return None

    age_seconds = time.time() - cache_path.stat().st_mtime
    return age_seconds / 3600


def load_json_cache(cache_path, max_age_hours=None):
    if not cache_path.exists():
        return None

    if max_age_hours is not None:
        age_hours = cache_age_hours(cache_path)
        if age_hours is None or age_hours > max_age_hours:
            return None

    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(
            f"Cannot read cache JSON: {cache_path}"
        ) from error

    if not isinstance(payload, dict):
        raise TypeError(
            f"Cache JSON must be an object: "
            f"{cache_path}"
        )

    return payload


def write_json_cache(cache_path, payload):
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = cache_path.with_suffix(".json.tmp")

    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary_path.replace(cache_path)


def fred_cache_path(series_id, observation_start, observation_end):
    start_text = observation_start.replace("-", "")
    end_text = observation_end.replace("-", "")
    return (
        CACHE_DIR
        / (
            f"fred_{series_id}_"
            f"{start_text}_{end_text}.json"
        )
    )


def retry_wait_seconds(response, attempt):
    retry_after = response.headers.get("Retry-After")

    if retry_after:
        try:
            return max(float(retry_after), 0.0)
        except ValueError:
            pass

    return BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))


def request_fred_json(session, request_params):
    """Request FRED JSON without exposing the API key in error messages."""
    for attempt in range(1, MAX_RETRIES + 1):
        time.sleep(REQUEST_INTERVAL_SECONDS)
        try:
            response = session.get(
                FRED_OBSERVATIONS_ENDPOINT,
                params=request_params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except (requests.Timeout, requests.ConnectionError):
            if attempt == MAX_RETRIES:
                break
            wait = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
            LOGGER.warning("FRED connection failed; retrying in %.1f seconds (%d/%d).", wait, attempt, MAX_RETRIES)
            time.sleep(wait)
            continue

        if response.status_code in RETRY_STATUS_CODES:
            if attempt == MAX_RETRIES:
                raise TransientRequestError(f"FRED request failed after retries (HTTP {response.status_code}).")
            wait = retry_wait_seconds(response, attempt)
            LOGGER.warning("FRED returned HTTP %d; retrying in %.1f seconds (%d/%d).", response.status_code, wait, attempt, MAX_RETRIES)
            time.sleep(wait)
            continue

        try:
            response.raise_for_status()
        except requests.HTTPError:
            raise requests.HTTPError(
                f"FRED request returned HTTP {response.status_code}.", response=response
            ) from None
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("FRED returned invalid JSON.") from None
        if not isinstance(payload, dict):
            raise TypeError("FRED JSON must be an object.")
        return payload

    raise TransientRequestError("FRED request failed after all retry attempts.") from None


def fetch_fred_series(
    series_id,
    api_key,
    observation_start,
    observation_end,
    session,
    refresh_cache=False,
):
    """Return one FRED series with date and value columns."""
    request_params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": observation_start,
        "observation_end": observation_end,
        "sort_order": SORT_ORDER,
    }
    cache_path = fred_cache_path(
        series_id=series_id,
        observation_start=observation_start,
        observation_end=observation_end,
    )

    payload = None
    payload_source = None

    if not refresh_cache:
        payload = load_json_cache(
            cache_path=cache_path,
            max_age_hours=CACHE_MAX_AGE_HOURS,
        )
        if payload is not None:
            payload_source = "fresh_cache"

    if payload is None:
        try:
            payload = request_fred_json(
                session=session,
                request_params=request_params,
            )
            payload_source = "network"
        except TransientRequestError:
            payload = load_json_cache(
                cache_path=cache_path,
                max_age_hours=None,
            )
            if payload is None:
                raise

            payload_source = "stale_cache"
            LOGGER.warning("Using stale FRED cache for %s after a temporary request failure.", series_id)

    observations = payload.get("observations", [])

    if not observations:
        error_message = payload.get("error_message") or payload.get(
            "message"
        )
        if error_message:
            raise ValueError(
                f"{series_id} FRED error: {str(error_message).replace(api_key, '***') if api_key else error_message}"
            )
        raise ValueError(
            f"{series_id} has no observations."
        )

    raw_series_df = pd.DataFrame(observations)
    required_columns = {"date", "value"}
    missing_required_columns = (
        required_columns - set(raw_series_df.columns)
    )

    if missing_required_columns:
        raise KeyError(
            f"{series_id} is missing required columns: "
            f"{sorted(missing_required_columns)}"
        )

    series_df = raw_series_df[["date", "value"]].rename(
        columns={"value": series_id}
    ).copy()

    series_df["date"] = pd.to_datetime(
        series_df["date"],
        errors="coerce",
    )
    series_df[series_id] = pd.to_numeric(
        series_df[series_id],
        errors="coerce",
    )
    series_df = series_df.sort_values("date").reset_index(
        drop=True
    )

    date_missing_count = series_df["date"].isna().sum()
    duplicate_date_count = series_df["date"].duplicated().sum()
    value_missing_count = series_df[series_id].isna().sum()

    if date_missing_count != 0:
        raise ValueError(
            f"{series_id} contains invalid dates: "
            f"{date_missing_count}"
        )

    if duplicate_date_count != 0:
        raise ValueError(
            f"{series_id} contains duplicate dates: "
            f"{duplicate_date_count}"
        )

    if series_df[series_id].notna().sum() == 0:
        raise ValueError(
            f"{series_id} has no numeric observations."
        )

    if not series_df[series_id].dropna().map(math.isfinite).all():
        raise ValueError(f"{series_id} contains non-finite observations.")

    if payload_source == "network":
        write_json_cache(cache_path, payload)
    LOGGER.debug(
        "%s: %d observations, %d missing values, %s to %s (%s)",
        series_id, len(series_df), value_missing_count,
        series_df["date"].min().date(), series_df["date"].max().date(), payload_source,
    )

    return series_df


def collect_fred_series(
    series_ids,
    api_key,
    observation_start,
    observation_end,
    session,
    refresh_cache=False,
):
    """Collect a DataFrame for each requested series."""
    if len(series_ids) != len(set(series_ids)):
        raise ValueError("Series IDs must be unique.")

    series_frames = {}

    for series_id in series_ids:
        try:
            series_frames[series_id] = fetch_fred_series(
                series_id=series_id,
                api_key=api_key,
                observation_start=observation_start,
                observation_end=observation_end,
                session=session,
                refresh_cache=refresh_cache,
            )
        except (
            requests.RequestException,
            RuntimeError,
            ValueError,
            KeyError,
            TypeError,
            OSError,
        ) as error:
            raise RuntimeError(
                f"{series_id} collection failed."
            ) from error

    return series_frames


def merge_fred_series(series_frames, series_ids):
    """Outer-join the series on observation date."""
    if not series_ids:
        raise ValueError("At least one series ID is required.")
    first_series_id = series_ids[0]
    macro_df = series_frames[first_series_id].copy()

    for series_id in series_ids[1:]:
        macro_df = macro_df.merge(
            series_frames[series_id],
            on="date",
            how="outer",
            validate="one_to_one",
        )

    macro_df = macro_df.sort_values("date").reset_index(
        drop=True
    )
    macro_df = macro_df[["date", *series_ids]]

    return macro_df


def validate_macro_data(
    macro_df,
    series_frames,
    series_ids,
    observation_start,
    observation_end,
):
    """Validate merged columns, dates and monthly coverage."""
    expected_columns = ["date", *series_ids]

    if list(macro_df.columns) != expected_columns:
        raise ValueError(
            "Unexpected merged column order: "
            f"{list(macro_df.columns)}"
        )

    if macro_df["date"].isna().sum() != 0:
        raise ValueError("The merged data contains missing dates.")

    if macro_df["date"].duplicated().sum() != 0:
        raise ValueError("The merged data contains duplicate dates.")

    if not macro_df["date"].is_monotonic_increasing:
        raise ValueError("The merged dates are not sorted.")

    expected_monthly_dates = pd.date_range(
        start=observation_start,
        end=observation_end,
        freq="MS",
    )
    expected_monthly_date_set = set(expected_monthly_dates)

    monthly_series_ids = [
        "UNRATE",
        "FEDFUNDS",
        "CPIAUCSL",
    ]

    for series_id in monthly_series_ids:
        actual_date_set = set(series_frames[series_id]["date"])
        missing_months = sorted(
            expected_monthly_date_set - actual_date_set
        )
        extra_dates = sorted(
            actual_date_set - expected_monthly_date_set
        )

        LOGGER.debug('%s %s', f"{series_id}_expected_month_count:", len(expected_monthly_dates))
        LOGGER.debug('%s %s', f"{series_id}_actual_month_count:", len(series_frames[series_id]))
        LOGGER.debug('%s %s', f"{series_id}_missing_month_count:", len(missing_months))
        LOGGER.debug('%s %s', f"{series_id}_extra_date_count:", len(extra_dates))

        if missing_months or extra_dates:
            raise ValueError(
                f"{series_id} has unexpected monthly observation dates."
            )

    largest_source_row_count = max(
        len(series_df)
        for series_df in series_frames.values()
    )
    merged_row_count_valid = (
        len(macro_df) >= largest_source_row_count
    )

    if not merged_row_count_valid:
        raise ValueError(
            "The outer join has fewer rows than a source series."
        )

    missing_summary = macro_df[series_ids].isna().sum()

    LOGGER.debug('%s %s', "macro_row_count:", len(macro_df))
    LOGGER.debug('%s %s', "macro_column_count:", len(macro_df.columns))
    LOGGER.debug('%s %s', "macro_columns:", list(macro_df.columns))
    LOGGER.debug('%s %s', "macro_first_date:", macro_df["date"].min().date())
    LOGGER.debug('%s %s', "macro_last_date:", macro_df["date"].max().date())
    LOGGER.debug('%s %s', "merged_row_count_valid:", merged_row_count_valid)
    LOGGER.debug('%s', "macro_missing_summary:")
    LOGGER.debug('%s', missing_summary)


def save_and_check_macro_data(macro_df, output_csv_path):
    """Validate a CSV round trip before replacing the saved file."""
    if not output_csv_path.parent.is_dir():
        raise FileNotFoundError("Create the data directory before collecting observations.")
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=output_csv_path.parent, prefix=output_csv_path.name+".", suffix=".tmp", delete=False) as stream:
            temporary_path = Path(stream.name)
            macro_df.to_csv(stream, index=False, date_format="%Y-%m-%d")
        saved = pd.read_csv(temporary_path, parse_dates=["date"])
        if saved["date"].isna().any() or saved["date"].duplicated().any():
            raise ValueError("The saved CSV contains missing or duplicate dates.")
        try:
            pd.testing.assert_frame_equal(saved, macro_df.reset_index(drop=True), check_dtype=False, check_exact=False, rtol=1e-10, atol=1e-12)
        except AssertionError as error:
            raise ValueError("The CSV round trip changed the observations.") from error
        temporary_path.replace(output_csv_path)
        return saved
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def parse_args():
    parser = argparse.ArgumentParser(description="Collect the core FRED series and rebuild data/macro_data.csv.")
    parser.add_argument("--refresh", action="store_true", help="Request data even when a fresh cache is available.")
    parser.add_argument("--verbose", action="store_true", help="Show collection and validation details.")
    return parser.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    LOGGER.setLevel(logging.DEBUG if args.verbose else logging.INFO)
    try:
        api_key = load_fred_api_key(ENV_PATH)
        with requests.Session() as session:
            frames = collect_fred_series(SERIES_IDS, api_key, OBSERVATION_START, OBSERVATION_END, session, refresh_cache=args.refresh)
        macro_df = merge_fred_series(frames, SERIES_IDS)
        validate_macro_data(macro_df, frames, SERIES_IDS, OBSERVATION_START, OBSERVATION_END)
        saved = save_and_check_macro_data(macro_df, OUTPUT_CSV_PATH)
    except (ValueError, KeyError, TypeError, OSError, RuntimeError, requests.RequestException) as error:
        LOGGER.error("Collection failed: %s", error)
        return 1
    print(f"Saved {len(saved)} rows and {len(saved.columns)} columns to {OUTPUT_CSV_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
