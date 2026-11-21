"""Offline regression checks for translated notebooks; no credentials or API calls."""
from __future__ import annotations
import ast
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
NOTEBOOKS=ROOT/'notebooks'


def notebook(name):
    return json.loads((NOTEBOOKS/name).read_text(encoding='utf-8'))


def cell(name,index):
    value=notebook(name)['cells'][index]['source']
    return ''.join(value) if isinstance(value,list) else value


def functions(source,namespace):
    tree=ast.parse(source)
    tree.body=[node for node in tree.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))]
    exec(compile(tree,'<notebook functions>','exec'),namespace)


class NotebookChecks(unittest.TestCase):
    def test_all_sources_compile_and_have_no_saved_outputs(self):
        names=sorted(NOTEBOOKS.glob('*.ipynb'))
        self.assertEqual(len(names),9)
        for path in names:
            nb=notebook(path.name)
            for i,c in enumerate(nb['cells']):
                source=''.join(c['source'])
                self.assertFalse(re.search('[\uac00-\ud7a3]',source),f'{path.name}:{i}')
                if c['cell_type']=='code':
                    compile(source,f'{path.name}:cell{i}','exec')
                    self.assertEqual(c.get('outputs'),[])
                    self.assertIsNone(c.get('execution_count'))

    def test_personal_contact_and_log_dependency_removed(self):
        source='\n'.join(''.join(c['source']) for name in ['07_sec_structure_apple.ipynb','08_sec_apple_metric.ipynb'] for c in notebook(name)['cells'])
        self.assertNotRegex(source,r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
        self.assertNotIn('project_log',source)
        self.assertNotIn('company_candidates.md',source)
        self.assertIn('SEC_CONTACT_EMAIL',source)

    def test_sample_apple_ticker(self):
        for name in ['01_python_basics.ipynb','02_pandas_dataframe.ipynb']:
            source='\n'.join(''.join(c['source']) for c in notebook(name)['cells'])
            self.assertNotIn('APPL',source)
            self.assertIn('AAPL',source)

    def test_sec_setup_requires_configured_contact_without_prompting(self):
        contact = 'student@example.test'
        for name in ['07_sec_structure_apple.ipynb', '08_sec_apple_metric.ipynb']:
            for configured in [False, True]:
                with self.subTest(notebook=name, configured=configured):
                    values = {'SEC_CONTACT_EMAIL': contact} if configured else {}
                    output = io.StringIO()
                    with (
                        patch.dict(os.environ, values, clear=True),
                        patch('dotenv.load_dotenv', return_value=False) as load_env,
                        patch('builtins.input', side_effect=AssertionError('Unexpected prompt')),
                        patch('getpass.getpass', side_effect=AssertionError('Unexpected prompt')),
                        patch('requests.sessions.Session.request', side_effect=AssertionError('Unexpected network')),
                        patch('urllib.request.urlopen', side_effect=AssertionError('Unexpected network')),
                        redirect_stdout(output),
                    ):
                        env = {'project_root': ROOT, 'os': os, 'load_dotenv': load_env}
                        if configured:
                            exec(cell(name, 3), env)
                            self.assertEqual(
                                env['sec_headers']['User-Agent'],
                                f'U.S. Financial Research Project {contact}',
                            )
                        else:
                            with self.assertRaisesRegex(ValueError, 'SEC_CONTACT_EMAIL'):
                                exec(cell(name, 3), env)
                            self.assertNotIn('sec_headers', env)
                    self.assertNotIn(contact, output.getvalue())

    def test_fred_mask_preview(self):
        env={'json':json,'fred_api_key':'synthetic_not_a_real_key'}
        output=io.StringIO()
        with redirect_stdout(output):exec(cell('06_fred_unrate.ipynb',2),env)
        self.assertIn('safe_request_has_mask: True',output.getvalue())
        self.assertNotIn('synthetic_not_a_real_key',output.getvalue())

    def test_decline_sentence_has_positive_magnitude(self):
        frame=pd.DataFrame({'DOWN':[100.0,80.0],'UP':[100.0,120.0],'FLAT':[10.0,10.0],'MISSING':[np.nan,20.0]},index=pd.to_datetime(['2023-12-31','2024-12-31']))
        env={'pd':pd,'line_chart_df':frame}
        with redirect_stdout(io.StringIO()):exec(cell('04_basic_charts.ipynb',6),env)
        text=' '.join(env['interpretation_sentences'])
        self.assertIn('decreased by USD 20 million.',text)
        self.assertIn('increased by USD 20 million.',text)
        self.assertIn('was unchanged.',text)
        self.assertIn('a value is missing',text)
        self.assertNotIn('USD -20',text)

    def test_different_metric_end_dates_fail(self):
        frame=pd.DataFrame({'fiscal_year':[2024],'revenue_period_start':pd.to_datetime(['2024-01-01']),'net_income_period_start':pd.to_datetime(['2024-01-01']),'revenue_period_end':pd.to_datetime(['2024-12-31']),'net_income_period_end':pd.to_datetime(['2024-12-30'])})
        with redirect_stdout(io.StringIO()),self.assertRaisesRegex(ValueError,'different reporting periods'):
            exec(cell('08_sec_apple_metric.ipynb',18),{'merged_financials_df':frame,'display':lambda value:None})
        frame['net_income_period_end']=frame['revenue_period_end']
        with redirect_stdout(io.StringIO()):exec(cell('08_sec_apple_metric.ipynb',18),{'merged_financials_df':frame,'display':lambda value:None})

    def test_billion_units(self):
        frame=pd.DataFrame({'fiscal_year':[2021,2025],'revenue_usd':[1_000_000_000,2_000_000_000],'net_income_usd':[200_000_000,100_000_000]})
        env={'apple_financials_df':frame}
        with redirect_stdout(io.StringIO()):exec(cell('08_sec_apple_metric.ipynb',26),env)
        self.assertIn('USD 1.000 billion',env['summary_sentence'])
        self.assertIn('USD 2.000 billion',env['summary_sentence'])
        self.assertIn('USD -0.100 billion',env['summary_sentence'])
        self.assertNotIn('1000.000',env['summary_sentence'])

    def test_macro_months_and_coverage(self):
        env={'pd':pd,'np':np,'MONTHLY_SERIES_IDS':['UNRATE','FEDFUNDS','CPIAUCSL'],'DAILY_SERIES_IDS':['DGS10','T10Y2Y'],'MACRO_SERIES_COLUMNS':['UNRATE','FEDFUNDS','CPIAUCSL','DGS10','T10Y2Y']}
        for index in [3,4,5]:functions(cell('09_company_macro_merge.ipynb',index),env)
        raw=pd.DataFrame({'date':pd.to_datetime(['2024-01-01','2024-01-02','2024-02-01']),'UNRATE':[3.0,np.nan,4.0],'FEDFUNDS':[5.0,np.nan,5.1],'CPIAUCSL':[100.0,np.nan,101.0],'DGS10':[2.0,4.0,6.0],'T10Y2Y':[0.1,0.3,0.4]})
        monthly=env['build_monthly_macro'](raw)
        self.assertAlmostEqual(monthly.iloc[0]['DGS10'],3.0)
        self.assertAlmostEqual(monthly.iloc[0]['T10Y2Y'],0.2)
        expected=env['expected_months_for_period'](pd.Timestamp('2024-01-15'),pd.Timestamp('2024-03-15'))
        self.assertEqual(list(map(str,expected)),['2024-02','2024-03'])
        partial=env['summarize_macro_window']({'period_start':pd.Timestamp('2024-02-01'),'period_end':pd.Timestamp('2024-03-31')},monthly)
        self.assertEqual(partial['macro_coverage_status'],'partial')
        self.assertEqual(partial['macro_observed_month_count'],1)
        missing=env['summarize_macro_window']({'period_start':pd.Timestamp('2025-01-01'),'period_end':pd.Timestamp('2025-12-31')},monthly)
        self.assertEqual(missing['macro_coverage_status'],'missing')
        self.assertTrue(np.isnan(missing['unrate_mean_pct']))
        raw.loc[1,'UNRATE']=3.1
        with self.assertRaisesRegex(ValueError,'multiple observations'):env['build_monthly_macro'](raw)


if __name__=='__main__':unittest.main(verbosity=2)
