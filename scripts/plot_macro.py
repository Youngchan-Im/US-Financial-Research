"""Plot the saved macro observations without requesting or changing source data."""
from __future__ import annotations
import argparse
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
SERIES = {'UNRATE': ('Unemployment rate', 'Percent'), 'FEDFUNDS': ('Effective federal funds rate', 'Percent'), 'CPIAUCSL': ('Consumer price index', 'Index (1982-1984=100)'), 'DGS10': ('10-year Treasury yield', 'Percent'), 'T10Y2Y': ('10-year minus 2-year Treasury yield', 'Percentage points')}

def plot_macro(project):
    path = project / 'data/macro_data.csv'
    data = pd.read_csv(path, parse_dates=['date'])
    if list(data.columns) != ['date', *SERIES]:
        raise ValueError('Unexpected macro columns')
    if data['date'].isna().any() or data['date'].duplicated().any():
        raise ValueError('Macro dates are missing or duplicated')
    data = data.sort_values('date')
    (figure, axes) = plt.subplots(3, 2, figsize=(14, 12), constrained_layout=True)
    for (axis, (series, (title, unit))) in zip(axes.flat, SERIES.items()):
        observations = data[['date', series]].dropna()
        if observations.empty:
            raise ValueError(f'No observations for {series}')
        axis.plot(observations['date'], observations[series], linewidth=1.5)
        axis.set_title(f'{series}: {title}')
        axis.set_xlabel('Date')
        axis.set_ylabel(unit)
        axis.grid(True, alpha=0.3)
        if series == 'T10Y2Y':
            axis.axhline(0, linewidth=1, color='grey')
    axes.flat[-1].axis('off')
    (first, last) = (data['date'].min().year, data['date'].max().year)
    figure.suptitle(f'U.S. macroeconomic indicators, {first}-{last}', fontsize=16)
    output = project / 'assets/macro_charts.png'
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=150, bbox_inches='tight')
    plt.close(figure)
    return output

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        output = plot_macro(args.project.resolve())
    except (OSError, ValueError) as error:
        parser.exit(1, f'Cannot plot macro data: {error}\n')
    print(f'Saved {output}')
    return 0
if __name__ == '__main__':
    raise SystemExit(main())
