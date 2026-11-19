"""Check saved financial inputs and recompute the company-macro panel offline."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import csv
from datetime import date
from decimal import Decimal, InvalidOperation
import math
from pathlib import Path
import sys
SERIES = ('UNRATE', 'FEDFUNDS', 'CPIAUCSL', 'DGS10', 'T10Y2Y')
MONTHLY = SERIES[:3]
CIKS = {'AAPL': '0000320193', 'MSFT': '0000789019', 'JPM': '0000019617', 'TSLA': '0001318605', 'WMT': '0000104169'}
METRICS = ('revenue_usd', 'net_income_usd', 'assets_usd', 'liabilities_usd', 'operating_cash_flow_usd')
MACRO_FIELDS = ('fiscal_year_end_month', 'fiscal_year_spans_two_calendar_years', 'macro_window_start_month', 'macro_window_end_month', 'macro_expected_month_count', 'macro_observed_month_count', 'macro_missing_value_count', 'macro_coverage_ratio', 'macro_coverage_status', 'unrate_mean_pct', 'fedfunds_mean_pct', 'cpi_start_index', 'cpi_end_index', 'cpi_change_pct', 'dgs10_mean_pct', 't10y2y_mean_pct', 'macro_source')

def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream, strict=True)
        fields = reader.fieldnames or []
        rows = list(reader)
    if not fields or len(set(fields)) != len(fields) or any((not name.strip() for name in fields)):
        raise ValueError(f'{path.name}: missing or duplicate headers')
    if not rows or any((None in row or any((value is None for value in row.values())) for row in rows)):
        raise ValueError(f'{path.name}: empty data or inconsistent row widths')
    return (fields, rows)

def number(value, field):
    if str(value).strip().lower() in {'', 'nan', 'na', 'none', 'null', '.'}:
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f'{field}: non-finite numeric value')
    return result

def month_range(start, end):
    (year, month) = (start.year, start.month)
    result = []
    while (year, month) <= (end.year, end.month):
        current = date(year, month, 1)
        if start <= current <= end:
            result.append(current)
        (year, month) = (year + 1, 1) if month == 12 else (year, month + 1)
    if not result:
        raise ValueError('Fiscal period contains no month starts')
    return result

def monthly_macro(rows):
    grouped = defaultdict(lambda : defaultdict(list))
    dates = []
    for row in rows:
        current = date.fromisoformat(row['date'])
        dates.append(current)
        for series in SERIES:
            value = number(row[series], series)
            if value is not None:
                grouped[date(current.year, current.month, 1)][series].append(value)
    if dates != sorted(set(dates)):
        raise ValueError('Macro dates must be unique and ascending')
    if not grouped:
        raise ValueError('No macro observations')
    months = sorted(grouped)
    if months != month_range(months[0], months[-1]):
        raise ValueError('Macro calendar months are not contiguous')
    result = {}
    for (month, values) in grouped.items():
        result[month] = {}
        for series in SERIES:
            observed = values.get(series, [])
            if series in MONTHLY and len(observed) > 1:
                raise ValueError(f'{series}: multiple observations in {month:%Y-%m}')
            result[month][series] = sum(observed) / len(observed) if observed else None
    return (result, dates)

def summarize(company, monthly):
    start = date.fromisoformat(company['period_start'])
    end = date.fromisoformat(company['period_end'])
    if start > end:
        raise ValueError('Fiscal period starts after its end')
    expected = month_range(start, end)
    window = [monthly[month] for month in expected if month in monthly]
    missing = sum((row[series] is None for row in window for series in SERIES))
    status = 'missing' if not window else 'complete' if len(window) == len(expected) and missing == 0 else 'partial'

    def mean(series):
        values = [row[series] for row in window if row[series] is not None]
        return sum(values) / len(values) if values else None
    cpi = [row['CPIAUCSL'] for row in window if row['CPIAUCSL'] is not None]
    (first, last) = (cpi[0], cpi[-1]) if cpi else (None, None)
    change = (last / first - 1) * 100 if first not in (None, 0) else None
    return dict(zip(MACRO_FIELDS, [end.month, start.year != end.year, str(expected[0]), str(expected[-1]), len(expected), len(window), missing, len(window) / len(expected), status, mean('UNRATE'), mean('FEDFUNDS'), first, last, change, mean('DGS10'), mean('T10Y2Y'), 'FRED']))

def equivalent(left, right):
    if left == right:
        return True
    try:
        return Decimal(left) == Decimal(right)
    except InvalidOperation:
        return False

def check(project):
    (company_fields, companies) = read_csv(project / 'data/company_financials.csv')
    (macro_fields, macro) = read_csv(project / 'data/macro_data.csv')
    (panel_fields, panel) = read_csv(project / 'data/company_macro_panel.csv')
    required = {'ticker', 'cik', 'fiscal_year', 'period_start', 'period_end', 'metric_coverage_count', *METRICS}
    if not required.issubset(company_fields):
        raise ValueError('Company CSV is missing required financial fields')
    if macro_fields != ['date', *SERIES]:
        raise ValueError('Unexpected macro column order')
    if panel_fields != company_fields + list(MACRO_FIELDS):
        raise ValueError('Panel columns do not preserve the company schema plus macro fields')
    if {row['ticker'] for row in companies} != set(CIKS):
        raise ValueError('Unexpected company universe')
    by_key = {}
    for row in companies:
        key = (row['ticker'], int(row['fiscal_year']))
        if key in by_key:
            raise ValueError(f'Duplicate company-year key: {key}')
        if row['cik'] != CIKS[row['ticker']]:
            raise ValueError(f"{row['ticker']}: incorrect CIK or lost leading zeros")
        values = [number(row[field], field) for field in METRICS]
        if int(row['metric_coverage_count']) != sum((v is not None for v in values)):
            raise ValueError(f'{key}: incorrect metric coverage count')
        by_key[key] = row
    year_sets = [{key[1] for key in by_key if key[0] == ticker} for ticker in CIKS]
    if any((years != year_sets[0] for years in year_sets)):
        raise ValueError('Companies do not share the same fiscal-year labels')
    (monthly, dates) = monthly_macro(macro)
    seen = set()
    for row in panel:
        key = (row['ticker'], int(row['fiscal_year']))
        if key in seen or key not in by_key:
            raise ValueError(f'Unexpected or duplicate panel key: {key}')
        seen.add(key)
        company = by_key[key]
        for field in company_fields:
            match = row[field] == company[field] if field == 'cik' else equivalent(row[field], company[field])
            if not match:
                raise ValueError(f'{key}: panel changed company field {field}')
        for (field, expected) in summarize(company, monthly).items():
            actual = row[field]
            if isinstance(expected, bool):
                match = actual.lower() == str(expected).lower()
            elif isinstance(expected, (int, float)) or expected is None:
                parsed = number(actual, field)
                match = parsed is None if expected is None else parsed is not None and math.isclose(parsed, expected, rel_tol=1e-10, abs_tol=5.1e-05)
            else:
                match = actual == expected
            if not match:
                raise ValueError(f'{key}: {field} is {actual!r}, expected {expected!r}')
    if seen != set(by_key):
        raise ValueError('Panel lost company-year rows')
    return {'macro_rows': len(macro), 'macro_dates': (str(dates[0]), str(dates[-1])), 'company_rows': len(companies), 'company_columns': len(company_fields), 'panel_columns': len(panel_fields), 'coverage': dict(sorted(Counter((row['macro_coverage_status'] for row in panel)).items()))}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result = check(args.project.resolve())
    except (OSError, ValueError, csv.Error, KeyError) as error:
        print(f'Check failed: {error}', file=sys.stderr)
        return 1
    print(f"Macro data: {result['macro_rows']:,} rows, {result['macro_dates'][0]} to {result['macro_dates'][1]}")
    print(f"Financials: {result['company_rows']} rows, {result['company_columns']} columns; panel: {result['panel_columns']} columns")
    print('Macro coverage: ' + ', '.join((f'{key}={value}' for (key, value) in result['coverage'].items())))
    print('Saved inputs and panel calculations agree.')
    return 0
if __name__ == '__main__':
    raise SystemExit(main())
