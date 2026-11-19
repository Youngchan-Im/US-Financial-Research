# U.S. Financial Research

A small research project combining SEC company financials with FRED macroeconomic data. It follows Apple, Microsoft, JPMorgan Chase, Tesla and Walmart across their fiscal periods, with source metadata and coverage checks kept alongside the numbers.

The current workflow collects the source data, builds a panel for each company and fiscal year and compares financial results with macro conditions. The saved annual panel is descriptive; the Numerai Signals extension is separate work.

## Run locally

From the project root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts/check_project.py
```

The check uses saved files and does not contact SEC or FRED. It also recomputes the saved fiscal-period macro summaries. Run the offline regression tests with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

To rebuild the macro chart from the saved CSV:

```powershell
.\.venv\Scripts\python.exe scripts/plot_macro.py
```

Open `notebooks/09_company_macro_merge.ipynb` in Jupyter or VS Code, select the same environment, restart the kernel and run all cells to rebuild `data/company_macro_panel.csv`. The notebook reads the two saved source CSVs. The earlier numbered notebooks contain the Python, pandas and API exercises used to build this workflow; the API exercises need network access and local credentials.

If `nbconvert` is installed, the merge can also run from the terminal:

```powershell
.\.venv\Scripts\python.exe -m jupyter nbconvert --to notebook --execute --inplace notebooks/09_company_macro_merge.ipynb
.\.venv\Scripts\python.exe scripts/check_project.py
```

## Refresh source data

The collectors use `FRED_API_KEY` and `SEC_CONTACT_EMAIL` from the project's local `.env`. The required names are listed in `.env.example`. Keep credentials and contact details out of version control.

```powershell
.\.venv\Scripts\python.exe src/fred_api.py
.\.venv\Scripts\python.exe src/sec_api.py
```

These commands collect data and write the source CSVs. Responses are cached in `data/cache/`; `--refresh` requests fresh responses. Add `--verbose` when you need collection diagnostics. The configured periods are 2019-2024 for FRED and fiscal years 2021-2025 for company financials. After refreshing, rerun the merge and check the coverage before interpreting the panel.

## Files

| Location | Contents |
|---|---|
| `src/fred_api.py` | FRED collection, validation and caching |
| `src/sec_api.py` | SEC companyfacts collection and financial-period checks |
| `data/macro_data.csv` | Five macro series joined on observation date |
| `data/company_financials.csv` | Annual financials and filing metadata for five companies |
| `data/company_macro_panel.csv` | Financials joined to macro summaries over each fiscal period |
| `notebooks/09_company_macro_merge.ipynb` | Panel construction and descriptive analysis |
| `docs/company_list.md` | Company selection, CIKs and revenue concepts |
| `docs/data_dictionary.md` | Fields, units, coverage and interpretation limits |
| `assets/` | Saved charts |

The [data dictionary](docs/data_dictionary.md) explains the mixed frequencies, fiscal calendars and incomplete macro coverage. Do not treat the annual panel as information that was necessarily available at a historical prediction date.

## Numerai Signals

The forecasting extension currently defines the dataset, target, feature availability policy and submission constraints in `config/signals.json`. Validate the configuration with:

```powershell
.\.venv\Scripts\python.exe -m src.signals validate-config
```

An isolated competition environment, data ingestion and model evaluation are the next steps. Label calendar resolution is still pending. The annual research panel needs historical filing availability before it can supply prediction features, and macro inputs remain disabled until source use is resolved.

See [Signals data](https://docs.numer.ai/numerai-signals/data) and the [target definition](https://docs.numer.ai/numerai-signals/signals-overview).
