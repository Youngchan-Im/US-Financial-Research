import argparse
import json
import os
from pathlib import Path
import time

import pandas as pd
import requests
from dotenv import load_dotenv


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
    """재시도 뒤에도 끝나지 않은 일시적 요청 오류다."""




def load_fred_api_key(env_path):
    """U.S. Financial Research Project 전용 .env에서 key를 읽는다."""
    load_dotenv(dotenv_path=env_path, override=False)
    fred_api_key = os.getenv("FRED_API_KEY")

    invalid_key_values = {
        None,
        "",
        "replace_with_your_fred_api_key",
    }

    if fred_api_key in invalid_key_values:
        raise ValueError(
            "FRED_API_KEY가 준비되지 않았습니다. "
            "프로젝트 루트의 .env를 확인하세요."
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
            f"캐시 JSON을 읽지 못했습니다: {cache_path}"
        ) from error

    if not isinstance(payload, dict):
        raise TypeError(
            f"캐시 JSON 최상위 구조가 딕셔너리가 아닙니다: "
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
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        time.sleep(REQUEST_INTERVAL_SECONDS)

        try:
            response = session.get(
                FRED_OBSERVATIONS_ENDPOINT,
                params=request_params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

            if response.status_code in RETRY_STATUS_CODES:
                if attempt == MAX_RETRIES:
                    raise TransientRequestError(
                        "FRED request가 일시적 HTTP 오류 상태로 "
                        f"종료되었습니다: {response.status_code}"
                    )

                wait_seconds = retry_wait_seconds(
                    response=response,
                    attempt=attempt,
                )
                print(
                    "fred_retry:",
                    f"attempt={attempt}",
                    f"status={response.status_code}",
                    f"wait_seconds={wait_seconds}",
                )
                time.sleep(wait_seconds)
                continue

            response.raise_for_status()
            payload = response.json()

            if not isinstance(payload, dict):
                raise TypeError(
                    "FRED JSON 최상위 구조가 딕셔너리가 아닙니다."
                )

            return payload

        except (requests.Timeout, requests.ConnectionError) as error:
            last_error = error
            if attempt == MAX_RETRIES:
                break

            wait_seconds = BACKOFF_BASE_SECONDS * (
                2 ** (attempt - 1)
            )
            print(
                "fred_retry:",
                f"attempt={attempt}",
                "status=network_error",
                f"wait_seconds={wait_seconds}",
            )
            time.sleep(wait_seconds)

        except requests.RequestException:
            raise
        except ValueError as error:
            raise ValueError(
                "FRED response를 JSON으로 변환하지 못했습니다."
            ) from error

    raise TransientRequestError(
        "FRED request가 재시도 횟수를 초과했습니다."
    ) from last_error


def fetch_fred_series(
    series_id,
    api_key,
    observation_start,
    observation_end,
    session,
    refresh_cache=False,
):
    """FRED series 하나를 date와 series ID column으로 반환한다."""
    request_params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": observation_start,
        "observation_end": observation_end,
        "sort_order": SORT_ORDER,
    }
    safe_request_params = {
        **request_params,
        "api_key": "***",
    }
    safe_request_text = json.dumps(
        safe_request_params,
        sort_keys=True,
    )
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
            write_json_cache(
                cache_path=cache_path,
                payload=payload,
            )
            payload_source = "network"
        except TransientRequestError as error:
            payload = load_json_cache(
                cache_path=cache_path,
                max_age_hours=None,
            )
            if payload is None:
                raise

            payload_source = "stale_cache"
            print(
                "fred_cache_fallback:",
                series_id,
                type(error).__name__,
            )

    observations = payload.get("observations", [])

    if not observations:
        error_message = payload.get("error_message") or payload.get(
            "message"
        )
        if error_message:
            raise ValueError(
                f"{series_id} FRED error: {error_message}"
            )
        raise ValueError(
            f"{series_id} observations 목록이 비어 있습니다."
        )

    raw_series_df = pd.DataFrame(observations)
    required_columns = {"date", "value"}
    missing_required_columns = (
        required_columns - set(raw_series_df.columns)
    )

    if missing_required_columns:
        raise KeyError(
            f"{series_id} 필수 column이 없습니다: "
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
            f"{series_id}에 변환되지 않은 날짜가 있습니다: "
            f"{date_missing_count}"
        )

    if duplicate_date_count != 0:
        raise ValueError(
            f"{series_id}에 중복 날짜가 있습니다: "
            f"{duplicate_date_count}"
        )

    if series_df[series_id].notna().sum() == 0:
        raise ValueError(
            f"{series_id}에 숫자로 변환된 관측값이 없습니다."
        )

    print("request_series_id:", series_id)
    print("safe_request_params:", safe_request_params)
    print(
        "actual_key_hidden_in_preview:",
        api_key not in safe_request_text,
    )
    print("payload_source:", payload_source)
    print("cache_file:", cache_path.name)
    print("returned_row_count:", len(series_df))
    print("value_missing_count:", value_missing_count)
    print("first_date:", series_df["date"].min().date())
    print("last_date:", series_df["date"].max().date())
    print("date_is_monotonic:", series_df["date"].is_monotonic_increasing)
    print("-" * 60)

    return series_df


def collect_fred_series(
    series_ids,
    api_key,
    observation_start,
    observation_end,
    session,
    refresh_cache=False,
):
    """series ID 목록을 반복해 DataFrame 딕셔너리를 만든다."""
    if len(series_ids) != len(set(series_ids)):
        raise ValueError("SERIES_IDS에 중복된 series ID가 있습니다.")

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
                f"{series_id} 수집에 실패했습니다."
            ) from error

    return series_frames


def merge_fred_series(series_frames, series_ids):
    """series별 DataFrame을 date 기준 outer 방식으로 병합한다."""
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
    """병합 결과의 column, 날짜, 월별 관측 수를 확인한다."""
    expected_columns = ["date", *series_ids]

    if list(macro_df.columns) != expected_columns:
        raise ValueError(
            "병합 결과 column 순서가 다릅니다: "
            f"{list(macro_df.columns)}"
        )

    if macro_df["date"].isna().sum() != 0:
        raise ValueError("병합 결과에 결측 날짜가 있습니다.")

    if macro_df["date"].duplicated().sum() != 0:
        raise ValueError("병합 결과에 중복 날짜가 있습니다.")

    if not macro_df["date"].is_monotonic_increasing:
        raise ValueError("병합 결과의 날짜가 오름차순이 아닙니다.")

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

        print(
            f"{series_id}_expected_month_count:",
            len(expected_monthly_dates),
        )
        print(
            f"{series_id}_actual_month_count:",
            len(series_frames[series_id]),
        )
        print(
            f"{series_id}_missing_month_count:",
            len(missing_months),
        )
        print(
            f"{series_id}_extra_date_count:",
            len(extra_dates),
        )

        if missing_months or extra_dates:
            raise ValueError(
                f"{series_id}의 월별 날짜 구성이 예상과 다릅니다."
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
            "outer 병합 결과가 가장 긴 원본 DataFrame보다 짧습니다."
        )

    missing_summary = macro_df[series_ids].isna().sum()

    print("macro_row_count:", len(macro_df))
    print("macro_column_count:", len(macro_df.columns))
    print("macro_columns:", list(macro_df.columns))
    print("macro_first_date:", macro_df["date"].min().date())
    print("macro_last_date:", macro_df["date"].max().date())
    print("merged_row_count_valid:", merged_row_count_valid)
    print("macro_missing_summary:")
    print(missing_summary)


def save_and_check_macro_data(macro_df, output_csv_path):
    """병합 결과를 CSV로 저장하고 다시 읽어 형태를 확인한다."""
    if not output_csv_path.parent.exists():
        raise FileNotFoundError(
            "data 폴더가 없습니다. 프로젝트 루트에 "
            "data 폴더를 만든 뒤 다시 실행하세요."
        )

    temporary_path = output_csv_path.with_suffix(".csv.tmp")
    macro_df.to_csv(
        temporary_path,
        index=False,
        date_format="%Y-%m-%d",
    )
    temporary_path.replace(output_csv_path)

    saved_macro_df = pd.read_csv(
        output_csv_path,
        parse_dates=["date"],
    )

    if len(saved_macro_df) != len(macro_df):
        raise ValueError("저장 전후 row 수가 다릅니다.")

    if list(saved_macro_df.columns) != list(macro_df.columns):
        raise ValueError("저장 전후 column 목록이 다릅니다.")

    if saved_macro_df["date"].duplicated().sum() != 0:
        raise ValueError("저장된 CSV에 중복 날짜가 있습니다.")

    print("saved_csv_path:", output_csv_path)
    print("saved_csv_exists:", output_csv_path.exists())
    print("saved_row_count:", len(saved_macro_df))
    print("saved_column_count:", len(saved_macro_df.columns))
    print("saved_columns:", list(saved_macro_df.columns))
    print("saved_first_date:", saved_macro_df["date"].min().date())
    print("saved_last_date:", saved_macro_df["date"].max().date())

    return saved_macro_df


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "FRED 핵심 경제지표를 수집해 macro CSV를 "
            "재생성합니다."
        )
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="유효한 캐시가 있어도 FRED API를 다시 요청합니다.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    print("project_root:", PROJECT_ROOT)
    print("env_file_exists:", ENV_PATH.exists())
    print("output_csv_path:", OUTPUT_CSV_PATH)
    print("observation_start:", OBSERVATION_START)
    print("observation_end:", OBSERVATION_END)
    print("series_ids:", SERIES_IDS)

    for series_id in SERIES_IDS:
        metadata = SERIES_METADATA[series_id]
        print(
            "series_metadata:",
            series_id,
            metadata["unit"],
            metadata["frequency"],
            metadata["seasonal_adjustment"],
            metadata["source_name"],
        )

    try:
        fred_api_key = load_fred_api_key(ENV_PATH)
        print("fred_api_key_loaded:", True)

        with requests.Session() as session:
            series_frames = collect_fred_series(
                series_ids=SERIES_IDS,
                api_key=fred_api_key,
                observation_start=OBSERVATION_START,
                observation_end=OBSERVATION_END,
                session=session,
                refresh_cache=args.refresh,
            )

        macro_df = merge_fred_series(
            series_frames=series_frames,
            series_ids=SERIES_IDS,
        )

        validate_macro_data(
            macro_df=macro_df,
            series_frames=series_frames,
            series_ids=SERIES_IDS,
            observation_start=OBSERVATION_START,
            observation_end=OBSERVATION_END,
        )

        saved_macro_df = save_and_check_macro_data(
            macro_df=macro_df,
            output_csv_path=OUTPUT_CSV_PATH,
        )

    except (
        ValueError,
        KeyError,
        TypeError,
        OSError,
        RuntimeError,
        requests.RequestException,
    ) as error:
        print("collection_complete:", False)
        print("error_type:", type(error).__name__)
        print("error_message:", str(error))
        return 1

    print("collection_complete:", True)
    print(saved_macro_df.head())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

