"""Offline collector checks. All request responses are synthetic."""
from __future__ import annotations
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import traceback
import unittest
from unittest import mock

import pandas as pd
import requests

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT


def load(name):
    spec=importlib.util.spec_from_file_location(name,WORK/'src'/f'{name}.py')
    module=importlib.util.module_from_spec(spec)
    with mock.patch('requests.sessions.Session.request',side_effect=AssertionError('Network requests are forbidden in tests')):
        spec.loader.exec_module(module)
    return module


FRED=load('fred_api')
SEC=load('sec_api')


class CollectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.financial_path=WORK/'data/company_financials.csv'
        cls.input_hash=hashlib.sha256(cls.financial_path.read_bytes()).hexdigest()
        cls.financials=SEC.reload_company_financials(cls.financial_path)

    @classmethod
    def tearDownClass(cls):
        assert hashlib.sha256(cls.financial_path.read_bytes()).hexdigest()==cls.input_hash

    def temporary(self):
        directory=tempfile.TemporaryDirectory(prefix='synthetic_collectors_')
        self.addCleanup(directory.cleanup)
        return Path(directory.name)

    def fred_fetch(self,refresh=False):
        return FRED.fetch_fred_series('UNRATE','synthetic-secret','2020-01-01','2020-02-01',mock.Mock(),refresh_cache=refresh)

    def test_invalid_sec_response_does_not_replace_cache(self):
        cache=self.temporary()/'sec.json'
        original=b'{"cik":320193,"facts":{"us-gaap":{}}}'
        cache.write_bytes(original)
        url=SEC.SEC_COMPANYFACTS_URL_TEMPLATE.format(cik='0000320193')
        with mock.patch.object(SEC,'request_sec_json',return_value={'cik':789019,'facts':{}}):
            with self.assertRaisesRegex(ValueError,'requested CIK'):
                SEC.get_sec_json(mock.Mock(),url,{},cache,refresh_cache=True)
        self.assertEqual(cache.read_bytes(),original)

    def test_current_saved_financial_data_passes(self):
        SEC.validate_combined_financials(self.financials)

    def test_empty_fred_series_list(self):
        with self.assertRaisesRegex(ValueError,'At least one'):
            FRED.merge_fred_series({},[])

    def test_fred_http_error_hides_key_from_traceback(self):
        response=mock.Mock(status_code=400)
        response.raise_for_status.side_effect=requests.HTTPError('bad URL?api_key=synthetic-secret')
        session=mock.Mock();session.get.return_value=response
        with mock.patch.object(FRED.time,'sleep'):
            try:FRED.request_fred_json(session,{'api_key':'synthetic-secret'})
            except requests.HTTPError:
                self.assertNotIn('api_key=synthetic-secret',traceback.format_exc())
            else:self.fail('Expected an HTTP error')

    def test_fred_connection_error_hides_key(self):
        session=mock.Mock();session.get.side_effect=requests.ConnectionError('URL?api_key=synthetic-secret')
        with mock.patch.object(FRED.time,'sleep'):
            try:FRED.request_fred_json(session,{'api_key':'synthetic-secret'})
            except FRED.TransientRequestError:
                self.assertNotIn('api_key=synthetic-secret',traceback.format_exc())
            else:self.fail('Expected a temporary request error')
        self.assertEqual(session.get.call_count,FRED.MAX_RETRIES)

    def test_invalid_fred_response_does_not_replace_cache(self):
        directory=self.temporary()
        with mock.patch.object(FRED,'CACHE_DIR',directory):
            cache=FRED.fred_cache_path('UNRATE','2020-01-01','2020-02-01')
            original=b'{"observations":[{"date":"2020-01-01","value":"3.5"}]}'
            cache.write_bytes(original)
            with mock.patch.object(FRED,'request_fred_json',return_value={'observations':[]}):
                with self.assertRaises(ValueError):self.fred_fetch(refresh=True)
            self.assertEqual(cache.read_bytes(),original)

    def test_fred_error_payload_hides_key(self):
        with mock.patch.object(FRED,'CACHE_DIR',self.temporary()),mock.patch.object(FRED,'request_fred_json',return_value={'error_message':'bad key synthetic-secret'}):
            try:self.fred_fetch(refresh=True)
            except ValueError as error:self.assertNotIn('synthetic-secret',str(error))
            else:self.fail('Expected an invalid response')

    def test_fred_missing_observation_stays_missing(self):
        payload={'observations':[{'date':'2020-01-01','value':'3.5'},{'date':'2020-02-01','value':'.'}]}
        with mock.patch.object(FRED,'CACHE_DIR',self.temporary()),mock.patch.object(FRED,'request_fred_json',return_value=payload):
            result=self.fred_fetch(refresh=True)
        self.assertEqual(len(result),2)
        self.assertTrue(pd.isna(result.loc[1,'UNRATE']))

    def test_fred_nonfinite_value_is_rejected(self):
        payload={'observations':[{'date':'2020-01-01','value':'inf'}]}
        directory=self.temporary()
        with mock.patch.object(FRED,'CACHE_DIR',directory),mock.patch.object(FRED,'request_fred_json',return_value=payload):
            with self.assertRaisesRegex(ValueError,'non-finite'):self.fred_fetch(refresh=True)
        self.assertEqual(list(directory.iterdir()),[])

    def test_transient_fred_failure_can_use_stale_cache(self):
        directory=self.temporary()
        with mock.patch.object(FRED,'CACHE_DIR',directory):
            cache=FRED.fred_cache_path('UNRATE','2020-01-01','2020-02-01')
            payload='{"observations":[{"date":"2020-01-01","value":"3.5"}]}'
            cache.write_text(payload,encoding='utf-8')
            with mock.patch.object(FRED,'request_fred_json',side_effect=FRED.TransientRequestError('temporary')):
                with self.assertLogs(FRED.LOGGER,level='WARNING') as logged:result=self.fred_fetch(refresh=True)
            self.assertEqual(result.loc[0,'UNRATE'],3.5)
            self.assertTrue(any('stale FRED cache' in message for message in logged.output))
            self.assertEqual(cache.read_text(encoding='utf-8'),payload)

    def test_macro_failed_roundtrip_preserves_old_file(self):
        output=self.temporary()/'macro.csv';output.write_bytes(b'previous valid dataset\n')
        frame=pd.DataFrame({'date':pd.to_datetime(['2020-01-01','2020-01-01']),'UNRATE':[3.5,4.]})
        with self.assertRaises(ValueError):FRED.save_and_check_macro_data(frame,output)
        self.assertEqual(output.read_bytes(),b'previous valid dataset\n')
        self.assertEqual([p.name for p in output.parent.iterdir()],['macro.csv'])

    def test_macro_successful_roundtrip(self):
        output=self.temporary()/'macro.csv'
        frame=pd.DataFrame({'date':pd.to_datetime(['2020-01-01','2020-02-01']),'UNRATE':[3.5,float('nan')]})
        saved=FRED.save_and_check_macro_data(frame,output)
        pd.testing.assert_frame_equal(saved,frame)

    def test_missing_cik_is_rejected(self):
        frame=self.financials.copy();frame.loc[0,'cik']=pd.NA
        with self.assertRaisesRegex(ValueError,'CIKs'):SEC.validate_combined_financials(frame)

    def test_non_ascii_cik_is_rejected(self):
        frame=self.financials.copy();frame.loc[0,'cik']='٠٠٠٠٣٢٠١٩٣'
        with self.assertRaisesRegex(ValueError,'CIKs'):SEC.validate_combined_financials(frame)

    def test_wrong_year_with_same_row_count_is_rejected(self):
        frame=self.financials.copy();frame.loc[0,'fiscal_year']=2020
        with self.assertRaisesRegex(ValueError,'fiscal years'):SEC.validate_combined_financials(frame)

    def test_nonfinite_financial_value_is_rejected(self):
        frame=self.financials.copy()
        frame['revenue_usd']=frame['revenue_usd'].astype(float)
        frame.loc[0,'revenue_usd']=float('inf')
        with self.assertRaisesRegex(ValueError,'finite'):SEC.validate_combined_financials(frame)

    def test_negative_net_income_is_valid(self):
        frame=self.financials.copy();frame.loc[0,'net_income_usd']=-100.
        SEC.validate_combined_financials(frame)

    def test_financial_csv_roundtrip_preserves_ciks(self):
        output=self.temporary()/'financials.csv'
        SEC.save_company_financials(self.financials,output)
        reloaded=SEC.reload_company_financials(output)
        self.assertTrue(reloaded['cik'].str.fullmatch('[0-9]{10}').all())
        pd.testing.assert_frame_equal(reloaded,self.financials,check_dtype=False)

    def test_financial_reload_failure_preserves_old_file(self):
        output=self.temporary()/'financials.csv';output.write_bytes(b'previous valid dataset\n')
        with mock.patch.object(SEC,'reload_company_financials',side_effect=ValueError('synthetic reload failure')):
            with self.assertRaises(ValueError):SEC.save_company_financials(self.financials,output)
        self.assertEqual(output.read_bytes(),b'previous valid dataset\n')
        self.assertEqual([p.name for p in output.parent.iterdir()],['financials.csv'])

    def test_latest_filing_selection_remains_descriptive(self):
        frame=pd.DataFrame({'fiscal_year':[2021,2021,2022],'end':pd.to_datetime(['2021-12-31','2021-12-31','2022-12-31']),'filed':pd.to_datetime(['2022-02-01','2023-02-01','2023-02-01']),'accn':['a','b','c']})
        selected=SEC.select_latest_record_per_fiscal_year(frame)
        self.assertEqual(selected['accn'].tolist(),['b','c'])

    def test_verbose_cli_option_does_not_collect(self):
        for module in [FRED,SEC]:
            with mock.patch('sys.argv',['collector','--verbose','--refresh']):
                args=module.parse_args()
            self.assertTrue(args.verbose and args.refresh)


if __name__=='__main__':unittest.main()
