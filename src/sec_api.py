import argparse
from getpass import getpass
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
CSV_OUTPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "company_financials.csv"
)
CACHE_DIR = PROJECT_ROOT / "data" / "cache"

SEC_COMPANYFACTS_URL_TEMPLATE = (
    "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
)
REQUEST_TIMEOUT_SECONDS = 30
REQUEST_INTERVAL_SECONDS = 0.2
CACHE_MAX_AGE_HOURS = 24
MAX_RETRIES = 4
BACKOFF_BASE_SECONDS = 1.0
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


class TransientRequestError(RuntimeError):
    """A temporary request failure that persisted after retries."""


FISCAL_YEAR_START = 2021
FISCAL_YEAR_END = 2025

COMPANY_CONFIGS = {
    "AAPL": {
        "company_name": "Apple Inc.",
        "cik_int": 320193,
        "sector": "Technology",
        "revenue_concepts": [
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
        ],
    },
    "MSFT": {
        "company_name": "Microsoft Corporation",
        "cik_int": 789019,
        "sector": "Technology",
        "revenue_concepts": [
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
        ],
    },
    "JPM": {
        "company_name": "JPMorgan Chase & Co.",
        "cik_int": 19617,
        "sector": "Banking",
        "revenue_concepts": [
            "Revenues",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
        ],
    },
    "TSLA": {
        "company_name": "Tesla, Inc.",
        "cik_int": 1318605,
        "sector": "Automotive and Energy",
        "revenue_concepts": [
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
        ],
    },
    "WMT": {
        "company_name": "Walmart Inc.",
        "cik_int": 104169,
        "sector": "Retail",
        "revenue_concepts": [
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "SalesRevenueNet",
            "Revenues",
        ],
    },
}

COMMON_METRIC_CONFIGS = {
    "net_income": {
        "fact_type": "duration",
        "concept_candidates": ["NetIncomeLoss"],
    },
    "assets": {
        "fact_type": "instant",
        "concept_candidates": ["Assets"],
    },
    "liabilities": {
        "fact_type": "instant",
        "concept_candidates": ["Liabilities"],
    },
    "operating_cash_flow": {
        "fact_type": "duration",
        "concept_candidates": [
            "NetCashProvidedByUsedInOperatingActivities"
        ],
    },
}

METRIC_NAMES = [
    "revenue",
    "net_income",
    "assets",
    "liabilities",
    "operating_cash_flow",
]
DURATION_METRIC_NAMES = [
    "revenue",
    "net_income",
    "operating_cash_flow",
]
INSTANT_METRIC_NAMES = [
    "assets",
    "liabilities",
]
METRIC_VALUE_COLUMNS = [
    "revenue_usd",
    "net_income_usd",
    "assets_usd",
    "liabilities_usd",
    "operating_cash_flow_usd",
]
QUALITY_FLAG_COLUMNS = [
    "duration_dates_match",
    "instant_dates_match",
    "period_end_matches_balance_sheet_date",
]
FINAL_COLUMNS = [
    "company_name",
    "ticker",
    "cik",
    "sector",
    "fiscal_year",
    "period_start",
    "period_end",
    "balance_sheet_date",
    "revenue_usd",
    "net_income_usd",
    "assets_usd",
    "liabilities_usd",
    "operating_cash_flow_usd",
    "form",
    "unit",
    "revenue_concept",
    "net_income_concept",
    "assets_concept",
    "liabilities_concept",
    "operating_cash_flow_concept",
    "revenue_duration_days",
    "net_income_duration_days",
    "operating_cash_flow_duration_days",
    "revenue_filed",
    "net_income_filed",
    "assets_filed",
    "liabilities_filed",
    "operating_cash_flow_filed",
    "revenue_accn",
    "net_income_accn",
    "assets_accn",
    "liabilities_accn",
    "operating_cash_flow_accn",
    "duration_dates_match",
    "instant_dates_match",
    "period_end_matches_balance_sheet_date",
    "metric_coverage_count",
    "missing_metrics",
    "source",
]
DATE_COLUMNS = [
    "period_start",
    "period_end",
    "balance_sheet_date",
    "revenue_filed",
    "net_income_filed",
    "assets_filed",
    "liabilities_filed",
    "operating_cash_flow_filed",
]


def build_sec_headers(contact_email):
    normalized_email = contact_email.strip()

    if not normalized_email or "@" not in normalized_email:
        raise ValueError("Enter a valid contact email address.")

    return {
        "User-Agent": (
            "U.S. Financial Research Project "
            f"{normalized_email}"
        ),
        "Accept-Encoding": "gzip, deflate",
    }


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


def retry_wait_seconds(response, attempt):
    retry_after = response.headers.get("Retry-After")

    if retry_after:
        try:
            return max(float(retry_after), 0.0)
        except ValueError:
            pass

    return BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))


def request_sec_json(session, url, headers):
    """Request SEC JSON with bounded retries for temporary failures."""
    for attempt in range(1, MAX_RETRIES + 1):
        time.sleep(REQUEST_INTERVAL_SECONDS)
        try:
            response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        except (requests.Timeout, requests.ConnectionError):
            if attempt == MAX_RETRIES:
                break
            wait = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
            LOGGER.warning(
                "SEC connection failed; retrying in %.1f seconds (%d/%d).",
                wait, attempt, MAX_RETRIES,
            )
            time.sleep(wait)
            continue
        if response.status_code in RETRY_STATUS_CODES:
            if attempt == MAX_RETRIES:
                raise TransientRequestError(
                    f"SEC request failed after retries (HTTP {response.status_code})."
                )
            wait = retry_wait_seconds(response, attempt)
            LOGGER.warning(
                "SEC returned HTTP %d; retrying in %.1f seconds (%d/%d).",
                response.status_code, wait, attempt, MAX_RETRIES,
            )
            time.sleep(wait)
            continue
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("SEC returned invalid JSON.") from None
        if not isinstance(payload, dict):
            raise TypeError("SEC JSON must be an object.")
        return payload
    raise TransientRequestError("SEC request failed after all retry attempts.") from None


def get_sec_json(
    session,
    url,
    headers,
    cache_path,
    refresh_cache=False,
):
    if not refresh_cache:
        cached_payload = load_json_cache(
            cache_path=cache_path,
            max_age_hours=CACHE_MAX_AGE_HOURS,
        )
        if cached_payload is not None:
            return cached_payload, "fresh_cache"

    try:
        payload = request_sec_json(
            session=session,
            url=url,
            headers=headers,
        )
        if "/api/xbrl/companyfacts/CIK" in url:
            expected_cik = url.rsplit("CIK", 1)[-1].split(".json", 1)[0]
            actual_cik = str(payload.get("cik", "")).zfill(10)
            if actual_cik != expected_cik or not isinstance(payload.get("facts"), dict) or not payload["facts"]:
                raise ValueError("SEC companyfacts response does not match the requested CIK or fact structure.")
        write_json_cache(
            cache_path=cache_path,
            payload=payload,
        )
        return payload, "network"
    except TransientRequestError:
        stale_payload = load_json_cache(
            cache_path=cache_path,
            max_age_hours=None,
        )
        if stale_payload is not None:
            LOGGER.warning("Using stale SEC cache %s after a temporary request failure.", cache_path.name)
            return stale_payload, "stale_cache"
        raise


def concept_usd_facts_to_df(
    companyfacts_json,
    concept_id,
):
    try:
        concept_data = (
            companyfacts_json["facts"]
            ["us-gaap"]
            [concept_id]
        )
        usd_records = concept_data["units"]["USD"]
    except KeyError as error:
        raise KeyError(
            f"{concept_id} has no USD fact records."
        ) from error

    facts_df = pd.DataFrame(usd_records)

    if facts_df.empty:
        raise ValueError(
            f"{concept_id} has no USD fact records."
        )

    required_columns = [
        "end",
        "val",
        "accn",
        "fy",
        "fp",
        "form",
        "filed",
    ]
    missing_columns = [
        column
        for column in required_columns
        if column not in facts_df.columns
    ]

    if missing_columns:
        raise ValueError(
            f"{concept_id} facts are missing required columns: "
            f"{missing_columns}"
        )

    if "start" not in facts_df.columns:
        facts_df["start"] = pd.NaT

    facts_df["start"] = pd.to_datetime(
        facts_df["start"],
        errors="coerce",
    )
    facts_df["end"] = pd.to_datetime(
        facts_df["end"],
        errors="coerce",
    )
    facts_df["filed"] = pd.to_datetime(
        facts_df["filed"],
        errors="coerce",
    )
    facts_df["val"] = pd.to_numeric(
        facts_df["val"],
        errors="coerce",
    )
    facts_df["reported_fy"] = pd.to_numeric(
        facts_df["fy"],
        errors="coerce",
    ).astype("Int64")
    facts_df["end_year"] = facts_df["end"].dt.year.astype(
        "Int64"
    )
    facts_df["duration_days"] = (
        facts_df["end"]
        - facts_df["start"]
    ).dt.days + 1
    facts_df["concept_id"] = concept_id
    facts_df["unit"] = "USD"

    return facts_df


def report_fiscal_year_context(annual_df, concept_id):
    comparable = annual_df.dropna(
        subset=["reported_fy", "fiscal_year"]
    )
    mismatch_count = comparable.loc[
        comparable["reported_fy"].ne(
            comparable["fiscal_year"]
        )
    ].shape[0]

    LOGGER.debug('%s %s %s %s', "fiscal_year_context:", concept_id, f"candidate_rows={len(annual_df)}", f"reported_fy_mismatch_count={mismatch_count}")


def select_latest_record_per_fiscal_year(facts_df):
    return (
        facts_df
        .sort_values(
            ["end", "filed", "accn"],
            ascending=[True, True, True],
        )
        .drop_duplicates(
            subset=["fiscal_year"],
            keep="last",
        )
        .sort_values("fiscal_year")
        .reset_index(drop=True)
    )


def extract_annual_duration_facts(
    companyfacts_json,
    concept_id,
    metric_name,
    fiscal_year_start,
    fiscal_year_end,
):
    facts_df = concept_usd_facts_to_df(
        companyfacts_json=companyfacts_json,
        concept_id=concept_id,
    )

    annual_df = facts_df.loc[
        facts_df["form"].eq("10-K")
        & facts_df["fp"].eq("FY")
        & facts_df["duration_days"].between(330, 400)
    ].copy()

    annual_df = annual_df.dropna(
        subset=["start", "end", "filed", "val"]
    )
    annual_df["fiscal_year"] = annual_df["end"].dt.year
    annual_df = annual_df.loc[
        annual_df["fiscal_year"].between(
            fiscal_year_start,
            fiscal_year_end,
        )
    ].copy()

    if annual_df.empty:
        raise ValueError(
            f"{concept_id} has no duration facts "
            "in the requested year range."
        )

    report_fiscal_year_context(
        annual_df=annual_df,
        concept_id=concept_id,
    )
    annual_df = select_latest_record_per_fiscal_year(
        annual_df
    )

    annual_df = annual_df.rename(
        columns={
            "start": f"{metric_name}_period_start",
            "end": f"{metric_name}_period_end",
            "val": f"{metric_name}_usd",
            "filed": f"{metric_name}_filed",
            "accn": f"{metric_name}_accn",
            "duration_days": (
                f"{metric_name}_duration_days"
            ),
            "concept_id": f"{metric_name}_concept",
        }
    )

    output_columns = [
        "fiscal_year",
        f"{metric_name}_period_start",
        f"{metric_name}_period_end",
        f"{metric_name}_usd",
        f"{metric_name}_filed",
        f"{metric_name}_accn",
        f"{metric_name}_duration_days",
        f"{metric_name}_concept",
    ]

    return annual_df[output_columns]


def extract_annual_instant_facts(
    companyfacts_json,
    concept_id,
    metric_name,
    fiscal_year_start,
    fiscal_year_end,
):
    facts_df = concept_usd_facts_to_df(
        companyfacts_json=companyfacts_json,
        concept_id=concept_id,
    )

    annual_df = facts_df.loc[
        facts_df["form"].eq("10-K")
        & facts_df["fp"].eq("FY")
        & facts_df["start"].isna()
    ].copy()

    annual_df = annual_df.dropna(
        subset=["end", "filed", "val"]
    )
    annual_df["fiscal_year"] = annual_df["end"].dt.year
    annual_df = annual_df.loc[
        annual_df["fiscal_year"].between(
            fiscal_year_start,
            fiscal_year_end,
        )
    ].copy()

    if annual_df.empty:
        raise ValueError(
            f"{concept_id} has no instant facts "
            "in the requested year range."
        )

    report_fiscal_year_context(
        annual_df=annual_df,
        concept_id=concept_id,
    )
    annual_df = select_latest_record_per_fiscal_year(
        annual_df
    )

    annual_df = annual_df.rename(
        columns={
            "end": f"{metric_name}_balance_sheet_date",
            "val": f"{metric_name}_usd",
            "filed": f"{metric_name}_filed",
            "accn": f"{metric_name}_accn",
            "concept_id": f"{metric_name}_concept",
        }
    )

    output_columns = [
        "fiscal_year",
        f"{metric_name}_balance_sheet_date",
        f"{metric_name}_usd",
        f"{metric_name}_filed",
        f"{metric_name}_accn",
        f"{metric_name}_concept",
    ]

    return annual_df[output_columns]


def empty_metric_frame(metric_name, fact_type):
    if fact_type == "duration":
        columns = [
            "fiscal_year",
            f"{metric_name}_period_start",
            f"{metric_name}_period_end",
            f"{metric_name}_usd",
            f"{metric_name}_filed",
            f"{metric_name}_accn",
            f"{metric_name}_duration_days",
            f"{metric_name}_concept",
        ]
    elif fact_type == "instant":
        columns = [
            "fiscal_year",
            f"{metric_name}_balance_sheet_date",
            f"{metric_name}_usd",
            f"{metric_name}_filed",
            f"{metric_name}_accn",
            f"{metric_name}_concept",
        ]
    else:
        raise ValueError(
            f"Unsupported fact type: {fact_type}"
        )

    return pd.DataFrame(columns=columns)


def metric_config_for_company(company_config, metric_name):
    if metric_name == "revenue":
        return {
            "fact_type": "duration",
            "concept_candidates": company_config[
                "revenue_concepts"
            ],
        }

    return COMMON_METRIC_CONFIGS[metric_name]


def resolve_metric_frame(
    companyfacts_json,
    company_config,
    metric_name,
):
    config = metric_config_for_company(
        company_config=company_config,
        metric_name=metric_name,
    )
    fact_type = config["fact_type"]
    target_year_count = (
        FISCAL_YEAR_END - FISCAL_YEAR_START + 1
    )

    best_frame = empty_metric_frame(
        metric_name=metric_name,
        fact_type=fact_type,
    )
    best_concept = None
    best_coverage = 0
    candidate_results = []

    for concept_id in config["concept_candidates"]:
        try:
            if fact_type == "duration":
                candidate_frame = extract_annual_duration_facts(
                    companyfacts_json=companyfacts_json,
                    concept_id=concept_id,
                    metric_name=metric_name,
                    fiscal_year_start=FISCAL_YEAR_START,
                    fiscal_year_end=FISCAL_YEAR_END,
                )
            else:
                candidate_frame = extract_annual_instant_facts(
                    companyfacts_json=companyfacts_json,
                    concept_id=concept_id,
                    metric_name=metric_name,
                    fiscal_year_start=FISCAL_YEAR_START,
                    fiscal_year_end=FISCAL_YEAR_END,
                )
        except (KeyError, TypeError, ValueError) as error:
            candidate_results.append(
                {
                    "concept_id": concept_id,
                    "coverage_years": 0,
                    "result": str(error),
                }
            )
            continue

        coverage_years = candidate_frame[
            "fiscal_year"
        ].nunique()
        candidate_results.append(
            {
                "concept_id": concept_id,
                "coverage_years": int(coverage_years),
                "result": "usable",
            }
        )

        if coverage_years > best_coverage:
            best_frame = candidate_frame
            best_concept = concept_id
            best_coverage = int(coverage_years)

        if coverage_years == target_year_count:
            break

    status = "missing"
    if best_coverage == target_year_count:
        status = "complete"
    elif best_coverage > 0:
        status = "partial"

    diagnostic = {
        "metric_name": metric_name,
        "selected_concept": best_concept,
        "coverage_years": best_coverage,
        "status": status,
        "candidate_results": candidate_results,
    }

    return best_frame, diagnostic


def merge_metric_frame(left_df, right_df, metric_name):
    if right_df["fiscal_year"].duplicated().any():
        raise ValueError(
            f"{metric_name} has duplicate fiscal-year records."
        )

    return left_df.merge(
        right_df,
        on="fiscal_year",
        how="left",
        validate="one_to_one",
    )


def coalesce_columns(dataframe, columns):
    existing_columns = [
        column
        for column in columns
        if column in dataframe.columns
    ]

    if not existing_columns:
        return pd.Series(pd.NaT, index=dataframe.index)

    return dataframe[existing_columns].bfill(axis=1).iloc[:, 0]


def row_dates_match(row, columns):
    values = [
        row[column]
        for column in columns
        if column in row.index and pd.notna(row[column])
    ]

    if len(values) <= 1:
        return pd.NA

    return all(value == values[0] for value in values[1:])


def nullable_date_match(left_value, right_value):
    if pd.isna(left_value) or pd.isna(right_value):
        return pd.NA

    return left_value == right_value


def build_company_financials(
    companyfacts_json,
    ticker,
    company_config,
):
    company_cik = f"{company_config['cik_int']:010d}"
    payload_cik = int(companyfacts_json.get("cik", -1))

    if payload_cik != company_config["cik_int"]:
        raise ValueError(
            f"{ticker} companyfacts CIK does not match the configuration."
        )

    fiscal_years = list(
        range(FISCAL_YEAR_START, FISCAL_YEAR_END + 1)
    )
    merged_df = pd.DataFrame(
        {"fiscal_year": fiscal_years}
    )
    diagnostics = []

    for metric_name in METRIC_NAMES:
        metric_frame, diagnostic = resolve_metric_frame(
            companyfacts_json=companyfacts_json,
            company_config=company_config,
            metric_name=metric_name,
        )
        diagnostics.append(diagnostic)
        merged_df = merge_metric_frame(
            left_df=merged_df,
            right_df=metric_frame,
            metric_name=metric_name,
        )

    duration_start_columns = [
        f"{metric_name}_period_start"
        for metric_name in DURATION_METRIC_NAMES
    ]
    duration_end_columns = [
        f"{metric_name}_period_end"
        for metric_name in DURATION_METRIC_NAMES
    ]
    instant_date_columns = [
        f"{metric_name}_balance_sheet_date"
        for metric_name in INSTANT_METRIC_NAMES
    ]

    merged_df["period_start"] = coalesce_columns(
        dataframe=merged_df,
        columns=duration_start_columns,
    )
    merged_df["period_end"] = coalesce_columns(
        dataframe=merged_df,
        columns=duration_end_columns,
    )
    merged_df["balance_sheet_date"] = coalesce_columns(
        dataframe=merged_df,
        columns=instant_date_columns,
    )

    merged_df["duration_dates_match"] = merged_df.apply(
        lambda row: (
            row_dates_match(row, duration_start_columns)
            and row_dates_match(row, duration_end_columns)
            if pd.notna(
                row_dates_match(row, duration_start_columns)
            )
            and pd.notna(
                row_dates_match(row, duration_end_columns)
            )
            else pd.NA
        ),
        axis=1,
    ).astype("boolean")
    merged_df["instant_dates_match"] = merged_df.apply(
        lambda row: row_dates_match(
            row,
            instant_date_columns,
        ),
        axis=1,
    ).astype("boolean")
    merged_df[
        "period_end_matches_balance_sheet_date"
    ] = merged_df.apply(
        lambda row: nullable_date_match(
            row["period_end"],
            row["balance_sheet_date"],
        ),
        axis=1,
    ).astype("boolean")

    merged_df["metric_coverage_count"] = merged_df[
        METRIC_VALUE_COLUMNS
    ].notna().sum(axis=1)
    merged_df["missing_metrics"] = merged_df.apply(
        lambda row: ", ".join(
            metric_name
            for metric_name in METRIC_NAMES
            if pd.isna(row[f"{metric_name}_usd"])
        ),
        axis=1,
    )

    merged_df["company_name"] = company_config["company_name"]
    merged_df["ticker"] = ticker
    merged_df["cik"] = company_cik
    merged_df["sector"] = company_config["sector"]
    merged_df["form"] = "10-K"
    merged_df["unit"] = "USD"
    merged_df["source"] = "SEC EDGAR companyfacts"

    date_columns_to_drop = (
        duration_start_columns
        + duration_end_columns
        + instant_date_columns
    )
    merged_df = merged_df.drop(
        columns=date_columns_to_drop,
    )

    company_financials_df = (
        merged_df[FINAL_COLUMNS]
        .sort_values("fiscal_year")
        .reset_index(drop=True)
    )

    return company_financials_df, diagnostics


def validate_company_financials(
    company_financials_df,
    ticker,
    company_config,
):
    expected_fiscal_years = set(
        range(FISCAL_YEAR_START, FISCAL_YEAR_END + 1)
    )
    actual_fiscal_years = set(
        company_financials_df["fiscal_year"].tolist()
    )
    expected_cik = f"{company_config['cik_int']:010d}"

    if list(company_financials_df.columns) != FINAL_COLUMNS:
        raise ValueError(
            f"{ticker}: unexpected final column order."
        )

    if actual_fiscal_years != expected_fiscal_years:
        raise ValueError(
            f"{ticker}: fiscal years must cover 2021-2025"
            "."
        )

    if company_financials_df["fiscal_year"].duplicated().any():
        raise ValueError(
            f"{ticker}: duplicate fiscal years."
        )

    if not company_financials_df["ticker"].eq(ticker).fillna(False).all():
        raise ValueError(f"{ticker}: unexpected ticker values.")

    if not company_financials_df["cik"].eq(expected_cik).fillna(False).all():
        raise ValueError(
            f"{ticker}: CIK does not match the configured ten-digit identifier."
        )

    if company_financials_df[
        "metric_coverage_count"
    ].lt(3).any():
        raise ValueError(
            f"{ticker}: some fiscal years have "
            "fewer than three available metrics."
        )

    for column in METRIC_VALUE_COLUMNS:
        values = company_financials_df[column].dropna()
        try:
            finite = pd.to_numeric(values, errors="raise").map(math.isfinite).all()
        except (TypeError, ValueError):
            finite = False
        if not finite:
            raise ValueError(f"{ticker}: {column} must contain finite numeric values.")

    positive_when_present = [
        "revenue_usd",
        "assets_usd",
        "liabilities_usd",
    ]

    for column in positive_when_present:
        values = company_financials_df[column].dropna()
        if not values.gt(0).all():
            raise ValueError(
                f"{ticker}: {column} contains nonpositive values."
            )

    for metric_name in METRIC_NAMES:
        value_column = f"{metric_name}_usd"
        concept_column = f"{metric_name}_concept"
        filed_column = f"{metric_name}_filed"
        accn_column = f"{metric_name}_accn"
        present_mask = company_financials_df[
            value_column
        ].notna()

        if company_financials_df.loc[
            present_mask,
            [concept_column, filed_column, accn_column],
        ].isna().any().any():
            raise ValueError(
                f"{ticker}: {metric_name} provenance contains "
                "missing values."
            )

    for flag_column in QUALITY_FLAG_COLUMNS:
        if company_financials_df[flag_column].eq(False).any():
            raise ValueError(
                f"{ticker}: {flag_column} failed validation."
            )


def collect_all_company_financials(
    headers,
    session,
    refresh_cache=False,
):
    company_frames = []
    diagnostic_rows = []

    for ticker, company_config in COMPANY_CONFIGS.items():
        cik = f"{company_config['cik_int']:010d}"
        companyfacts_url = (
            SEC_COMPANYFACTS_URL_TEMPLATE.format(cik=cik)
        )
        cache_path = (
            CACHE_DIR
            / f"sec_companyfacts_{cik}.json"
        )

        try:
            companyfacts_json, cache_status = get_sec_json(
                session=session,
                url=companyfacts_url,
                headers=headers,
                cache_path=cache_path,
                refresh_cache=refresh_cache,
            )
        except (
            requests.RequestException,
            RuntimeError,
            ValueError,
            TypeError,
            OSError,
        ) as error:
            raise RuntimeError(
                f"{ticker} companyfacts collection failed."
            ) from error

        LOGGER.debug('%s %s %s %s', "sec_payload_source:", ticker, cache_status, cache_path.name)
        company_financials_df, diagnostics = (
            build_company_financials(
                companyfacts_json=companyfacts_json,
                ticker=ticker,
                company_config=company_config,
            )
        )
        validate_company_financials(
            company_financials_df=company_financials_df,
            ticker=ticker,
            company_config=company_config,
        )
        company_frames.append(company_financials_df)

        for diagnostic in diagnostics:
            diagnostic_rows.append(
                {
                    "ticker": ticker,
                    "metric_name": diagnostic["metric_name"],
                    "selected_concept": diagnostic[
                        "selected_concept"
                    ],
                    "coverage_years": diagnostic[
                        "coverage_years"
                    ],
                    "status": diagnostic["status"],
                    "cache_status": cache_status,
                }
            )

    combined_df = (
        pd.concat(company_frames, ignore_index=True)
        .sort_values(["ticker", "fiscal_year"])
        .reset_index(drop=True)
    )
    diagnostics_df = pd.DataFrame(diagnostic_rows)

    return combined_df, diagnostics_df


def validate_combined_financials(combined_df):
    expected_tickers = set(COMPANY_CONFIGS)
    actual_tickers = set(combined_df["ticker"].unique())
    expected_row_count = len(COMPANY_CONFIGS) * (
        FISCAL_YEAR_END - FISCAL_YEAR_START + 1
    )

    if list(combined_df.columns) != FINAL_COLUMNS:
        raise ValueError("Unexpected combined CSV column order.")

    if actual_tickers != expected_tickers:
        raise ValueError("Unexpected tickers in the combined data.")

    if len(combined_df) != expected_row_count:
        raise ValueError(
            f"Expected {expected_row_count} rows in the combined data."
        )

    if combined_df.duplicated(
        subset=["ticker", "fiscal_year"]
    ).any():
        raise ValueError("Duplicate ticker/fiscal-year keys.")

    if not combined_df["cik"].astype("string").str.fullmatch(r"[0-9]{10}").fillna(False).all():
        raise ValueError("CIKs must be ten-digit strings.")

    rows_per_ticker = combined_df.groupby(
        "ticker"
    )["fiscal_year"].nunique()
    expected_year_count = (
        FISCAL_YEAR_END - FISCAL_YEAR_START + 1
    )

    if not rows_per_ticker.eq(expected_year_count).all():
        raise ValueError(
            "Each company must have five fiscal years."
        )

    for ticker, company_config in COMPANY_CONFIGS.items():
        validate_company_financials(
            combined_df.loc[combined_df["ticker"].eq(ticker)], ticker, company_config
        )

    if combined_df["metric_coverage_count"].lt(3).any():
        raise ValueError(
            "Some company-year rows have fewer than three available metrics."
        )


def normalize_nullable_boolean_series(series):
    def normalize_value(value):
        if pd.isna(value) or str(value).strip() == "":
            return pd.NA

        normalized = str(value).strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False

        raise ValueError(
            f"Invalid boolean value: {value}"
        )

    return series.map(normalize_value).astype("boolean")


def reload_company_financials(csv_path):
    reloaded_df = pd.read_csv(
        csv_path,
        dtype={
            "ticker": "string",
            "cik": "string",
            "revenue_accn": "string",
            "net_income_accn": "string",
            "assets_accn": "string",
            "liabilities_accn": "string",
            "operating_cash_flow_accn": "string",
        },
        parse_dates=DATE_COLUMNS,
    )

    for flag_column in QUALITY_FLAG_COLUMNS:
        reloaded_df[flag_column] = (
            normalize_nullable_boolean_series(
                reloaded_df[flag_column]
            )
        )

    reloaded_df["missing_metrics"] = reloaded_df["missing_metrics"].fillna("")
    return reloaded_df


def save_company_financials(combined_df, csv_path):
    """Validate the temporary CSV before replacing the last good dataset."""
    validate_combined_financials(combined_df)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=csv_path.parent, prefix=csv_path.name+".", suffix=".tmp", delete=False) as stream:
            temporary_path = Path(stream.name)
            combined_df.to_csv(stream, index=False, date_format="%Y-%m-%d")
        reloaded = reload_company_financials(temporary_path)
        validate_combined_financials(reloaded)
        try:
            pd.testing.assert_frame_equal(reloaded, combined_df.reset_index(drop=True), check_dtype=False, check_exact=False, rtol=1e-10, atol=1e-12)
        except AssertionError as error:
            raise ValueError("The CSV round trip changed the financial data.") from error
        temporary_path.replace(csv_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def parse_args():
    parser = argparse.ArgumentParser(description="Collect SEC companyfacts and rebuild data/company_financials.csv.")
    parser.add_argument("--refresh", action="store_true", help="Request data even when a fresh cache is available.")
    parser.add_argument("--verbose", action="store_true", help="Show concept selection and validation details.")
    return parser.parse_args()


def load_sec_contact_email(env_path):
    load_dotenv(dotenv_path=env_path)
    contact_email = os.getenv("SEC_CONTACT_EMAIL", "").strip()

    if not contact_email:
        contact_email = getpass(
            "Contact email for the SEC User-Agent: "
        ).strip()

    return contact_email


def main():
    args = parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    LOGGER.setLevel(logging.DEBUG if args.verbose else logging.INFO)
    try:
        headers = build_sec_headers(load_sec_contact_email(ENV_PATH))
        with requests.Session() as session:
            combined, diagnostics = collect_all_company_financials(headers, session, refresh_cache=args.refresh)
        validate_combined_financials(combined)
        save_company_financials(combined, CSV_OUTPUT_PATH)
        reloaded = reload_company_financials(CSV_OUTPUT_PATH)
        LOGGER.debug("Selected concepts and coverage:\n%s", diagnostics.to_string(index=False))
    except (ValueError, KeyError, TypeError, OSError, RuntimeError, requests.RequestException) as error:
        LOGGER.error("Collection failed: %s", error)
        return 1
    print(f"Saved {len(reloaded)} rows and {len(reloaded.columns)} columns to {CSV_OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
