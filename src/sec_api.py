from getpass import getpass
from pathlib import Path
import time

import pandas as pd
import requests 


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CSV_OUTPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "apple_financials_extended.csv"
)

APPLE_TICKER = "AAPL"
APPLE_CIK_INT = 320193
APPLE_CIK  = f"{APPLE_CIK_INT:010d}"

SEC_COMPANYFACTS_URL_TEMPLATE = (
    "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
)
REQUEST_TIMEOUT_SECONDS = 30
REQUEST_INTERVAL_SECONDS = 0.2

FISCAL_YEAR_START = 2021
FISCAL_YEAR_END = 2025

METRIC_CONFIGS = {
    "revenue": {
        "concept_id": (
            "RevenueFromContractWithCustomerExcludingAssessedTax"
        ),
        "fact_type": "duration",
    },
    "net_income": {
        "concept_id": "NetIncomeLoss",
        "fact_type": "duration",
    },
    "assets": {
        "concept_id": "Assets",
        "fact_type": "instant",
    },
    "liabilities": {
        "concept_id": "Liabilities",
        "fact_type": "instant",
    },
    "operating_cash_flow": {
        "concept_id": (
            "NetCashProvidedByUsedInOperatingActivities"
        ),
        "fact_type": "duration",
    },
}

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

FINAL_COLUMNS = [
    "company_name",
    "ticker",
    "cik",
    "fiscal_year",
    "period_start",
    "period_end",
    "balance_sheet_date",
    "revenue_usd",
    "net_income_us",
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
    "liabilities_accn",
    "operating_cash_flow_accn",
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
        raise ValueError("연락 가능한 이메일 형식을 입력하세요.")

    return {
        "User-Agent": (
            "U.S. Financial Research Project "
            f"{normalized_email}"
        ),
        "Accept-Encoding": "gzip, deflate",
    }


def get_sec_json(
        url,
        headers,
        pause_seconds=REQUEST_INTERVAL_SECONDS,
):
    if pause_seconds < 0:
        raise ValueError("pause_seconds는 0 이상이어야 합니다.")

    time.sleep(pause_seconds)

    response = requests.get(
        url,
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    payload = response.json()

    if not isinstance(payload, dict):
        raise TypeError("SEC JSON 최상위 구조가 딕셔너리가 아닙니다.")

    return payload


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
            f"{concept_id}의 USD facts 경로를 찾지 못했습니다."
        ) from error

    facts_df = pd.DataFrame(usd_records)

    if facts_df.empty:
        raise ValueError(
            f"{concept_id}의 USD fact record가 없습니다."
        )

    required_columns = [
        "start",
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
            f"{concept_id} facts에 필요한 column이 없습니다: "
            f"{missing_columns}"
        )

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
    facts_df["duration_days"] = (
        facts_df["end"]
        - facts_df["start"]
    ).dt.days + 1
    facts_df["concept_id"] = concept_id
    facts_df["unit"] = "USD"

    return facts_df


def select_latest_record_per_fiscal_year(facts_df):
    return (
        facts_df
        .sort_values(
            ["end", "filed", "accn"],
            asending=[True, True, True],
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
            f"{concept_id}에서 지정 범위의 duration facts를 "
            "찾지 못했습니다."
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
            "duration": (
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
            f"{concept_id}에서 지정 범위의 instant facts를 "
            "찾지 못했습니다."
        )

    annual_df = select_latest_record_per_fiscal_year(
        annual_df
    )

    annual_df = annual_df.rename(
        columns={
            "end": f"{metric_name}_period_end",
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


def merge_metric_frame(
        left_df,
        right_df,
        metric_name,
):
    merged_df = left_df.merge(
        right_df,
        on="fiscal_year",
        how="outer",
        validate="one_to_one",
        indicator=True,
    )

    if not merged_df["_merge"].eq("both").all():
        unmatched_df = merged_df.loc[
            merged_df["_merge"].ne("both"),
            ["fiscal_year", "_merge"],
        ]
        raise ValueError(
            f"{metric_name} 병합에서 회계 범위가 "
            f"일치하지 않습니다: {unmatched_df.to_dict('records')}"
        )

    return merged_df.drop(columns="_merge")


def extract_metric_frames(companyfacts_json):
    metric_frames = {}

    for metric_name, config in METRIC_CONFIGS.items():
        if config["fact_type"] == "duration":
            metric_frames[metric_name] = (
                extract_annual_duration_facts(
                    companyfacts_json=companyfacts_json,
                    concept_id=config["concept_id"],
                    metric_name=metric_name,
                    fiscal_year_start=FISCAL_YEAR_START,
                    fiscal_year_end=FISCAL_YEAR_END,
                )
            )
        elif config["fact_type"] == "instant":
            metric_frames[metric_name] = (
                extract_annual_instant_facts(
                    companyfacts_json=companyfacts_json,
                    concept_id=config["concept_id"],
                    metric_name=metric_name,
                    fiscal_year_start=FISCAL_YEAR_START,
                    fiscal_year_end=FISCAL_YEAR_END,
                )
            )
        else:
            raise ValueError(
                f"지원하지 않는 fact_type입니다: "
                f"{config['fact_type']}"
            )

    return metric_frames


def validate_metric_dates(merged_df):
    common_period_start = merged_df["revenue_period_start"]
    common_period_end = merged_df["common_period_end"]

    for metric_name in [
        "net_income",
        "operating_cash_flow",
    ]:
        start_column = f"{metric_name}_period_start"
        end_column = f"{metric_name}_period_end"

        if not common_period_start.eq(
            merged_df[start_column]
        ).all():
            raise ValueError(
                f"revenue와 {metric_name}의 시작일이 "
                "일치하지 않습니다."
            )

        if not common_period_end.eq(
            merged_df[end_column]
        ).all():
            raise ValueError(
                f"revenue와 {metric_name}의 종료일이 "
                "일치하지 않습니다."
            )

    assets_date = merged_df["assets_balance_sheet_date"]
    liabilities_date = (
        merged_df["liabilities_balance_sheet_date"]
    )

    if not assets_date.eq(liabilities_date).all():
        raise ValueError(
            "assets와 liabilities의 balance sheet date가 "
            "일치하지 않습니다."
        )

    if not common_period_start.eq(assets_date).all():
        raise ValueError(
            "duration fact의 period end와 instant fact의 "
            "balance sheet date가 일치하지 않습니다."
        )


def build_apple_financials_extended(companyfacts_json):
    metric_frames = extract_metric_frames(companyfacts_json)

    merged_df = metric_frames["revenue"].copy()

    for metric_name in [
        "net_income",
        "assets",
        "liabilities",
        "operating_cash_flow",
    ]:
        merged_df = merge_metric_frame(
            left_df=merged_df,
            right_df=metric_frames[metric_name],
            metric_name=metric_name,
        )

    validate_metric_dates(merged_df)

    apple_financials_extended_df = merged_df.copy()
    apple_financials_extended_df["company"] = (
        companyfacts_json["entityName"]
    )
    apple_financials_extended_df["ticker"] = APPLE_TICKER
    apple_financials_extended_df["cik"] = APPLE_CIK
    apple_financials_extended_df["period_start"] = (
        apple_financials_extended_df[
            "revenue_period_start"
        ]
    )
    apple_financials_extended_df["period_end"] = (
        apple_financials_extended_df[
            "revenue_period_end"
        ]
    )
    apple_financials_extended_df["balance_sheet_date"] = (
        apple_financials_extended_df[
            "assets_balance_sheet_date"
        ]
    )
    apple_financials_extended_df["form"] = "10-K"
    apple_financials_extended_df["unit"] = "USD"
    apple_financials_extended_df["source"] = (
        "SEC EDGAR companyfacts"
    )

    date_columns_to_drop = []

    for metric_name in DURATION_METRIC_NAMES:
        date_columns_to_drop.extend(
            [
                f"{metric_name}_period_start",
                f"{metric_name}_period_end",
            ]
        )

    for metric_name in INSTANT_METRIC_NAMES:
        date_columns_to_drop.append(
            f"{metric_name}_balance_sheet_date"
        )

    apple_financials_extended_df = (
        apple_financials_extended_df
        .drop(columns=date_columns_to_drop)
        [FINAL_COLUMNS]
        .sort_values("fiscal_year")
        .reset_index(drop=True)
    )

    return apple_financials_extended_df


def validate_apple_financials_extended(financials_df):
    expected_fiscal_years = set(
        range(FISCAL_YEAR_START, FISCAL_YEAR_END + 1)
    )
    actual_fiscal_years = set(
        financials_df["fiscal_year"].tolist()
    )

    if list(financials_df.columns) != FINAL_COLUMNS:
        raise ValueError(("최종 column 순서가 기준과 다릅니다."))

    if actual_fiscal_years != expected_fiscal_years:
        raise ValueError(
            "회계연도 범위가 2021~2025와 일치하지 않습니다."
        )

    if financials_df["fiscal_year"].duplicated().any():
        raise ValueError("fiscal_year 중복이 있습니다.")

    if financials_df[METRIC_VALUE_COLUMNS].isna().any().any():
        raise ValueError("다섯 재무지표에 결측치가 있습니다.")

    if not financials_df[METRIC_VALUE_COLUMNS].gt(0).all().all():
        raise ValueError("Apple 기준 지표 값에 0 이하가 있습니다.")

    if not financials_df["cik"].eq(APPLE_CIK).all():
        raise ValueError("CIK가 10자리 Apple CIK와 다릅니다.")

    if not financials_df["form"].eq("10-K").all():
        raise ValueError("form이 모두 10-K가 아닙니다.")

    if not financials_df["unit"].eq("USD").all():
        raise ValueError("unit이 모두 USD가 아닙니다.")

    if not financials_df["period_end"].eq(
        financials_df["balance_sheet_date"]
    ).all():
        raise ValueError(
            "period_end와 balance_sheet_date가 일치하지 않습니다."
        )

    if not financials_df["fiscal_year"].eq(
        financials_df["period_end"].dt.year
    ).all():
        raise ValueError("fiscal_year와 period_end의 연도가 다릅니다.")

    duration_columns = [
        f"{metric_name}_duration_days"
        for metric_name in DURATION_METRIC_NAMES
    ]
    
    if not financials_df[duration_columns].apply(
        lambda column: column.between(330, 400)
    ).all().all():
        raise ValueError(
            "duration factㅇ의 기간 길이가 330~400일 범위를 "
            "벗어났습니다."
        )

    expected_concepts = {
        f"{metric_name}_concept": config["config_id"]
        for metric_name, config in METRIC_CONFIGS.items()
    }

    for column, expected_concept in expected_concepts.items():
        if not financials_df[column].eq(
            expected_concept
        ).all():
            raise ValueError(
                f"{column}이 예상 concept과 다릅니다."
            )

    source_columns = [
        column
        for column in financials_df.columns
        if column.endswith("_filed")
        or column.endswith("_accn")
    ]

    if financials_df[source_columns].isna().any().any():
        raise ValueError("filed 또는 accn에 결측치가 있습니다.")

    return {
        "shape": financials_df.shape,
        "fiscal_year": sorted(actual_fiscal_years),
        "duplicate_fiscal_year_count": int(
            financials_df["fiscal_year"].duplicated().sum()
        ),
        "missing_metric_value_count": int(
            financials_df[METRIC_VALUE_COLUMNS]
            .isna()
            .sum()
            .sum()
        ),
    }


def save_and_reload_financials(financials_df):
    if not CSV_OUTPUT_PATH.parent.is_dir():
        raise FileNotFoundError(
            "data 폴더가 없습니다: "
            f"{CSV_OUTPUT_PATH.parent}"
        )

    financials_df.to_csv(
        CSV_OUTPUT_PATH,
        index=False,
        date_format="%Y-%m-%d",
    )

    reloaded_df = pd.read_csv(
        CSV_OUTPUT_PATH,
        dtype={"cik": "string"},
        parse_dates=DATE_COLUMNS,
    )

    validate_apple_financials_extended(reloaded_df)

    return reloaded_df


def build_billion_display(financials_df):
    display_df = financials_df[
        ["fiscal_year", *METRIC_VALUE_COLUMNS]
    ].copy()

    for column in METRIC_VALUE_COLUMNS:
        display_df[column] = (
            display_df[column]
            / 1_000_000_000
        ).round(3)

    display_df = display_df.rename(
        columns={
            column: column.replace("_usd", "_usd_bn")
            for column in METRIC_VALUE_COLUMNS
        }
    )

    return display_df


def main():
    sec_contact_email = getpass(
        "SEC User-Agent에 넣을 연락처 이메일을 입력하세요: "
    )
    sec_headers = build_sec_headers(sec_contact_email)

    companyfacts_url = SEC_COMPANYFACTS_URL_TEMPLATE.format(
        ck=APPLE_CIK
    )
    apple_companyfacts_json = get_sec_json(
        url=companyfacts_url,
        headers=sec_headers,
    )

    if int(apple_companyfacts_json.get("cik", -1)) != APPLE_CIK_INT:
        raise ValueError("companyfacts CIK가 Apple CIK와 다릅니다.")

    if "facts" not in apple_companyfacts_json:
        raise KeyError("companyfacts에서 facts를 찾지 못했습니다.")

    apple_financials_extended_df = (
        build_apple_financials_extended(
            apple_companyfacts_json
        )
    )
    validation_summary = validate_apple_financials_extended(
        apple_financials_extended_df
    )
    reloaded_financials_extended_df = save_and_reload_financials(
        apple_financials_extended_df
    )
    display_df = build_billion_display(
        reloaded_financials_extended_df
    )

    print(
        "company_name:",
        apple_companyfacts_json.get("entityName"),
    )
    print("output_path:", CSV_OUTPUT_PATH)
    print("extended_shape:", validation_summary["shape"])
    print(
        "fiscal_years:",
        validation_summary["fiscal_year"],
    )
    print(
        "duplicate_fiscal_year_count:",
        validation_summary["duplicate_fiscal_year_count"],
    )
    print(
        "missing_metric_value_count:",
        validation_summary["missing_metric_value_count"],
    )
    print(display_df.to_string(index=False))


if __name__ == "__main__":
    main()