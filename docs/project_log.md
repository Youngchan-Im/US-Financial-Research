## 2026-07-07

- session: 02
- topic: environment setting and local execution
- output_folders:
  - data/
  - notebooks/
  - src/
  - assets/
  - docs/
- output_files:
  - requirements.txt
  - notebooks/us_finance_environment_check.ipynb
  - .gitignore
- environment_check:
  - requirements_file_exists: True
  - gitignore_file_exists: True
  - candidate_count: 10
  
## 2026-07-13

- session: 04
- topic: pandas DataFrame basic
- output_files:
  - notebooks/02_pandas_dataframe.ipynb
  - data/sample_cleaned.csv
  - docs/project_log.md
- pandas_dataframe_check:
  - raw_row_count: 4
  - raw_column_count: 11
  - research_row_count: 3
  - research_tikcer_list: AAPL, MSFT, NVDA
  - cleaned_row_count: 3
  - cleaned_column_count: 9
  - saved_csv_exists: True
  - saved_row_count: 3
  - saved_column_count: 9
  - saved_ticker_list: AAPL, MSFT, NVDA
  - large_revenue_row_count: 2
- data_note:
  - unit: USD million
  - frequency: annual_sample
  - source_note: class_sample
  - limit: 실습용 가상 값이며 실제 재무제표 데이터가 아님

  ## 2026-08-06

  - session: 09
  - topic: FRED 여러 지수 수집과 함수화
  - created: `src/fred_api.py`
  - created: `data/macro_data.csv`
  - source: FRED series observations API
  - obsercation period: `2019-01-01` to `2024-12-31`
  - series: `UNRATE`, `FEDFUNDS`, `CPIAUCSL`, `DGS10`, `T10Y2Y`
  