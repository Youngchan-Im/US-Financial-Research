# U.S. Financial Research

A research project combining SEC company financials with FRED macroeconomic data. It follows Apple, Microsoft, JPMorgan Chase, Tesla and Walmart across their fiscal periods, with source metadata and coverage checks kept alongside the numbers.

The annual panel is descriptive. The Numerai Signals extension builds a separate forecasting workflow.

## Set up with conda

From the project root in a macOS terminal:

```bash
conda env create -f environment.yml
conda activate financial-research
python -m pip check
python -m ipykernel install --sys-prefix --name financial-research --display-name "Python (financial-research)"
```

The environment uses Python 3.12. `requirements.txt` pins the direct research and competition packages; pip resolves their dependencies for the current platform. If you already use a Python 3.12 conda environment, activate it and run `python -m pip install -r requirements.txt` instead of creating another one. Register the kernel in that active environment with the command above.

## Configure API access

Notebooks 05 and 06 need `FRED_API_KEY`. Notebooks 07 and 08 need `SEC_CONTACT_EMAIL` for the SEC User-Agent. Set them in a local `.env` file using the names in `.env.example`:

```bash
[ -f .env ] || cp .env.example .env
open -e .env
```

Fill in both values before running the API notebooks. Keep `.env` local; it is excluded from Git. These notebooks make live requests, so they also need an internet connection. A missing setting raises an error before requesting data.

## Run all notebooks

Run the notebooks in number order. In VS Code or Jupyter, select `Python (financial-research)` and use Run All for each notebook. The same sequence can run from the terminal:

```bash
python -m nbconvert --to notebook --execute \
  --ExecutePreprocessor.kernel_name=financial-research \
  --output-dir TEMP/executed \
  notebooks/0[1-9]_*.ipynb
```

This runs every code cell from 01 through 09, including the live requests in 05 through 08. Execution stops on an error. The executed copies, tables and plots are saved in `TEMP/executed/`. Source notebooks keep their outputs clear for Git.

| Notebook | Work | Result |
|---|---|---|
| `01_python_basics.ipynb` | Python values and control flow | Printed examples |
| `02_pandas_dataframe.ipynb` | DataFrame filtering and CSV I/O | `data/sample_cleaned.csv` |
| `03_datetime_missing_values.ipynb` | Dates, numeric conversion and missing values | Tables and checks |
| `04_basic_charts.ipynb` | Revenue and operating-income charts | `assets/basic_chart.png` and notebook plots |
| `05_api_json_fred_intro.ipynb` | Live FRED request and JSON structure | Five UNRATE observations from 2023 |
| `06_fred_unrate.ipynb` | UNRATE collection, validation and plotting | `data/unrate.csv`, 72 months from 2019 through 2024 |
| `07_sec_structure_apple.ipynb` | Apple identifiers, filings and companyfacts | SEC response tables |
| `08_sec_apple_metric.ipynb` | Annual Apple revenue and net income | `data/apple_financials.csv`, 5 rows and 19 columns |
| `09_company_macro_merge.ipynb` | Company financials joined to fiscal-period macro summaries | `data/company_macro_panel.csv`, 25 rows and 56 columns |

To rerun only notebook 08:

```bash
python -m nbconvert --to notebook --execute \
  --ExecutePreprocessor.kernel_name=financial-research \
  --output-dir TEMP/executed \
  notebooks/08_sec_apple_metric.ipynb
```

Notebook 09 reads `company_financials.csv` and `macro_data.csv`. It does not read the Apple-only CSV from notebook 08. Those two source files are included, so notebook 09 can also run without API access.

## Collect the five-company data

The collectors produce the source files used by notebook 09:

```bash
python src/fred_api.py
python src/sec_api.py
python -m nbconvert --to notebook --execute \
  --ExecutePreprocessor.kernel_name=financial-research \
  --output-dir TEMP/executed \
  notebooks/09_company_macro_merge.ipynb
```

Responses are cached in `data/cache/`. Use `--refresh` on a collector to request new responses, or `--verbose` for collection diagnostics. The configured periods are 2019-2024 for FRED and fiscal years 2021-2025 for company financials. Rerun notebook 09 after changing either source CSV.

## Check the result

```bash
python scripts/check_project.py
python scripts/plot_macro.py
python -m src.signals validate-config
python -m unittest discover -s tests -v
```

The saved-data check recomputes the panel summaries without contacting SEC or FRED. The included panel has macro coverage of 20 complete, 3 partial and 2 missing rows. The chart is saved to `assets/macro_charts.png`.

The [company list](docs/company_list.md) explains the CIKs and revenue concepts. The [data dictionary](docs/data_dictionary.md) describes the fields, fiscal calendars and incomplete coverage. A fiscal-period value was not necessarily public at a historical prediction date.

## Numerai Signals

`config/signals.json` defines the dataset, target, feature availability policy and submission constraints. Configuration validation and the research environment are implemented. Competition data ingestion and model evaluation are the next steps; their commands are not available yet.

Label calendar resolution is pending. Historical filing availability must be reconstructed before using the annual research data as prediction features, and macro inputs remain disabled until source use is resolved.

See [Signals data](https://docs.numer.ai/numerai-signals/data) and the [target definition](https://docs.numer.ai/numerai-signals/signals-overview).
