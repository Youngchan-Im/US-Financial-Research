# Data dictionary

## Saved datasets

| File | Row unit | Bundled snapshot |
|---|---|---|
| `data/macro_data.csv` | FRED observation date | 1,585 rows, six columns, January 2019 through December 2024 |
| `data/company_financials.csv` | Company and fiscal year | 25 rows, 39 columns, fiscal years 2021-2025 |
| `data/company_macro_panel.csv` | Company and fiscal year | 25 rows, 56 columns: the financial fields plus 17 macro fields |

These dimensions describe the saved files. A new source range can change the counts and coverage. `date` is an observation date, not a release timestamp.

## Macro series

The source file outer-joins all five series on `date`. Monthly series therefore have empty cells on most daily rows. Weekend, holiday and unavailable observations can also be missing. Missing values are not zeros and are not automatically carried forward.

| Column | Meaning | Unit | Native frequency | Source |
|---|---|---|---|---|
| `UNRATE` | Unemployment rate | Percent | Monthly, seasonally adjusted | U.S. Bureau of Labor Statistics |
| `FEDFUNDS` | Federal funds effective rate, monthly average | Percent | Monthly, not seasonally adjusted | Board of Governors of the Federal Reserve System |
| `CPIAUCSL` | All-items consumer price index | Index, 1982-1984 = 100 | Monthly, seasonally adjusted | U.S. Bureau of Labor Statistics |
| `DGS10` | Ten-year Treasury constant maturity market yield | Percent | Daily, not seasonally adjusted | Board of Governors of the Federal Reserve System |
| `T10Y2Y` | Ten-year minus two-year Treasury yield spread | Percentage points | Daily, not seasonally adjusted | Federal Reserve Bank of St. Louis |

The snapshot has 72 observations for each monthly series and 1,501 for each daily series. Monthly observations run from January 1, 2019 through December 1, 2024; daily observations run from January 2, 2019 through December 31, 2024.

A rate moving from 4% to 5% rises by one percentage point. `CPIAUCSL` is an index level, not an inflation rate. To calculate year-on-year inflation, align CPI to a calendar-month index, retain any missing months and use `pct_change(12, fill_method=None) * 100`. `FEDFUNDS` is not the FOMC target range. FRED labels the spread unit as Percent; a difference between two percentage rates is read in percentage points. A negative yield spread does not, by itself, establish when a recession occurs.

Series definitions and source notes: [UNRATE](https://fred.stlouisfed.org/series/UNRATE), [FEDFUNDS](https://fred.stlouisfed.org/series/FEDFUNDS), [CPIAUCSL](https://fred.stlouisfed.org/series/CPIAUCSL), [DGS10](https://fred.stlouisfed.org/series/DGS10), [T10Y2Y](https://fred.stlouisfed.org/series/T10Y2Y).

## Company financials

`ticker` and `fiscal_year` identify a row. The collector labels the year from `period_end.year`; it does not use the XBRL fact's reported `fy` field as the observation year. Monetary values are in USD. Preserve `cik` as a ten-character string when loading CSVs.

| Fields | Meaning |
|---|---|
| `company_name`, `ticker`, `cik`, `sector` | Company identifiers and the project's business grouping |
| `fiscal_year` | Fiscal-year label |
| `period_start`, `period_end` | Annual income and cash-flow period |
| `balance_sheet_date` | Date for assets and liabilities |
| `revenue_usd`, `net_income_usd`, `operating_cash_flow_usd` | Values over the annual reporting period |
| `assets_usd`, `liabilities_usd` | Values at the balance-sheet date |
| `form`, `unit`, `source` | Filing form, measurement unit and source |
| `*_concept` | XBRL concept selected for each financial metric |
| `*_duration_days` | Length of the selected duration metric's reporting period |
| `*_filed`, `*_accn` | Filing date and accession number for each metric |
| `duration_dates_match`, `instant_dates_match` | Whether the selected metrics share the expected dates |
| `period_end_matches_balance_sheet_date` | Whether the annual period ends on the selected balance-sheet date |
| `metric_coverage_count`, `missing_metrics` | Available financial metrics and any missing metrics |

Concepts, filing dates and accession numbers belong to individual metrics. Do not assume every value in a row comes from the same filing. The [company list](company_list.md) records the revenue fallback rules.

## Fiscal-period macro summaries

The merge notebook keeps native monthly observations for unemployment, the federal funds rate and CPI. It averages valid daily yield and spread observations by calendar month, then summarizes the selected months over each company's fiscal period.

A month is included when `period_start <= month_start <= period_end`. This approximates partial fiscal months without weighting them by days. Companies with the same fiscal-year label can consequently have different macro windows.

| Added column | Meaning |
|---|---|
| `fiscal_year_end_month` | Month in which the fiscal period ends |
| `fiscal_year_spans_two_calendar_years` | Whether the period crosses a calendar-year boundary |
| `macro_window_start_month`, `macro_window_end_month` | First and last expected calendar months |
| `macro_expected_month_count` | Months expected under the fiscal-window rule |
| `macro_observed_month_count` | Expected months present in the saved macro table |
| `macro_missing_value_count` | Missing cells across the five series in the selected months |
| `macro_coverage_ratio` | Observed month count divided by expected month count |
| `macro_coverage_status` | `complete`, `partial` or `missing` |
| `unrate_mean_pct`, `fedfunds_mean_pct` | Fiscal-period averages of the monthly rates |
| `cpi_start_index`, `cpi_end_index` | First and last observed CPI index in the window |
| `cpi_change_pct` | Percent change between those CPI values |
| `dgs10_mean_pct`, `t10y2y_mean_pct` | Fiscal-period averages of the calendar-month yield and spread means |
| `macro_source` | Macro data source |

The saved panel contains 20 `complete`, three `partial` and two `missing` rows. Financials extend through fiscal 2025, while the macro source ends in December 2024. Retain incomplete rows and distinguish them from complete comparisons. `cpi_change_pct` is a change over the selected fiscal window; it is not automatically a year-on-year inflation measure.

## Interpretation and sample data

The collectors select reported financial facts for descriptive comparison. Later filings and revised macro values can alter historical numbers. A fiscal period end does not tell a forecaster when the information became public. Forecasting needs separate availability cutoffs, filing history, release timing and revision handling.

Five companies over five fiscal years provide a small, dependent sample: companies share macro conditions and differ in business model. Co-movement is a starting point for investigation, rather than a causal or validated predictive result. Plot series with different units on separate axes.

`data/sample_cleaned.csv` and the early Python/pandas notebooks use illustrative company data. Those sample monetary values are in USD millions; they are not collected financial statements. The SEC financial columns above are in USD.
