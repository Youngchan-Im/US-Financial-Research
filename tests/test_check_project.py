"""Checks against saved inputs, with failures exercised on temporary copies."""
import csv
import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('check_project', ROOT / 'scripts/check_project.py')
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)

class SavedInputChecks(unittest.TestCase):

    def setUp(self):
        self.area = tempfile.TemporaryDirectory(prefix='financial_input_check_')
        self.addCleanup(self.area.cleanup)
        self.project = Path(self.area.name)
        (self.project / 'data').mkdir()
        for name in ['company_financials.csv', 'macro_data.csv', 'company_macro_panel.csv']:
            shutil.copyfile(ROOT / 'data' / name, self.project / 'data' / name)

    def change(self, name, update):
        path = self.project / 'data' / name
        with path.open(encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream)
            fields = reader.fieldnames
            rows = list(reader)
        update(rows)
        with path.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def test_saved_inputs_reproduce_panel(self):
        before = {p.name: p.read_bytes() for p in (self.project / 'data').glob('*.csv')}
        result = CHECK.check(self.project)
        self.assertGreater(result['company_rows'], 0)
        self.assertEqual(before, {p.name: p.read_bytes() for p in (self.project / 'data').glob('*.csv')})

    def test_modified_summary_is_rejected(self):
        self.change('company_macro_panel.csv', lambda rows: rows[0].update(unrate_mean_pct=str(float(rows[0]['unrate_mean_pct']) + 1)))
        with self.assertRaisesRegex(ValueError, 'unrate_mean_pct'):
            CHECK.check(self.project)

    def test_source_changes_require_rebuilding_panel(self):

        def update(rows):
            for row in rows:
                if row['UNRATE']:
                    row['UNRATE'] = str(float(row['UNRATE']) + 1)
        self.change('macro_data.csv', update)
        with self.assertRaisesRegex(ValueError, 'unrate_mean_pct'):
            CHECK.check(self.project)

    def test_missing_panel_row_is_rejected(self):
        self.change('company_macro_panel.csv', lambda rows: rows.pop())
        with self.assertRaisesRegex(ValueError, 'lost company-year'):
            CHECK.check(self.project)

    def test_source_cik_leading_zeros_are_required(self):
        self.change('company_financials.csv', lambda rows: rows[0].update(cik=str(int(rows[0]['cik']))))
        with self.assertRaisesRegex(ValueError, 'CIK'):
            CHECK.check(self.project)

    def test_panel_cik_leading_zeros_are_required(self):
        self.change('company_macro_panel.csv', lambda rows: rows[0].update(cik=str(int(rows[0]['cik']))))
        with self.assertRaisesRegex(ValueError, 'cik'):
            CHECK.check(self.project)

    def test_duplicate_macro_date_is_rejected(self):
        self.change('macro_data.csv', lambda rows: rows.append(rows[0].copy()))
        with self.assertRaisesRegex(ValueError, 'unique and ascending'):
            CHECK.check(self.project)

    def test_multiple_monthly_observations_are_rejected(self):
        self.change('macro_data.csv', lambda rows: rows[1].update(UNRATE='4'))
        with self.assertRaisesRegex(ValueError, 'multiple observations'):
            CHECK.check(self.project)

    def test_non_finite_financial_value_is_rejected(self):
        self.change('company_financials.csv', lambda rows: rows[0].update(revenue_usd='inf'))
        with self.assertRaisesRegex(ValueError, 'non-finite'):
            CHECK.check(self.project)
if __name__ == '__main__':
    unittest.main()
