"""Offline checks for prediction settings; no downloads or credentials."""

import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src import signals


ROOT = Path(__file__).resolve().parents[1]


class SignalsConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / 'config/signals.json').read_text(encoding='utf-8'))

    def test_saved_config_is_valid_and_unchanged(self):
        before = copy.deepcopy(self.config)
        self.assertEqual(signals.validate_config(self.config), before)
        self.assertEqual(self.config, before)

    def test_dataset_target_and_identifier_are_explicit(self):
        for name, value in [('data_version', 'latest'), ('target', 'target'), ('identifier', 'ticker')]:
            with self.subTest(field=name):
                config = copy.deepcopy(self.config)
                config[name] = value
                with self.assertRaises(signals.ConfigError):
                    signals.validate_config(config)

    def test_timing_and_submission_numbers_reject_booleans(self):
        for name, value in [('label_lag', True), ('label_horizon', 60.0), ('label_lag', 0)]:
            with self.subTest(field=name, value=value):
                config = copy.deepcopy(self.config)
                config[name] = value
                with self.assertRaises(signals.ConfigError):
                    signals.validate_config(config)
        self.config['submission']['minimum_tickers'] = True
        with self.assertRaises(signals.ConfigError):
            signals.validate_config(self.config)

    def test_availability_and_calendar_cannot_be_assumed(self):
        for section, name, value in [
            ('cutoff_policy', 'availability', 'latest available value'),
            ('cutoff_policy', 'timestamp_timezone', 'local'),
            ('label_calendar', 'status', 'calendar_days'),
        ]:
            with self.subTest(section=section, field=name):
                config = copy.deepcopy(self.config)
                config[section][name] = value
                with self.assertRaises(signals.ConfigError):
                    signals.validate_config(config)

    def test_submission_requires_open_bounds(self):
        self.config['submission']['bounds'] = 'inclusive'
        with self.assertRaises(signals.ConfigError):
            signals.validate_config(self.config)

    def test_current_source_decisions_are_enforced(self):
        for mutation in ('enable_macro', 'enable_fred', 'remove_sec', 'duplicate_source', 'missing_reason'):
            with self.subTest(mutation=mutation):
                config = copy.deepcopy(self.config)
                if mutation == 'enable_macro':
                    config['macro_enabled'] = True
                elif mutation == 'enable_fred':
                    config['sources'][2]['training_allowed'] = True
                elif mutation == 'remove_sec':
                    config['sources'].pop(1)
                elif mutation == 'duplicate_source':
                    config['sources'].append(copy.deepcopy(config['sources'][0]))
                else:
                    del config['sources'][1]['reason']
                with self.assertRaises(signals.ConfigError):
                    signals.validate_config(config)

    def test_missing_sections_and_bad_urls_fail(self):
        for section in ('submission', 'cutoff_policy', 'sources'):
            with self.subTest(section=section):
                config = copy.deepcopy(self.config)
                del config[section]
                with self.assertRaises(signals.ConfigError):
                    signals.validate_config(config)
        self.config['sources'][0]['reference_url'] = 'http://example.com'
        with self.assertRaises(signals.ConfigError):
            signals.validate_config(self.config)

    def test_malformed_or_ambiguous_json_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'settings.json'
            for text in ('not JSON', '[]', '{"target":"a","target":"b"}', '{"value":NaN}'):
                with self.subTest(text=text):
                    config.write_text(text, encoding='utf-8')
                    with self.assertRaises(ValueError):
                        signals.load_config(config)

    def test_cli_is_read_only_offline_and_independent_of_working_directory(self):
        config_path = ROOT / 'config/signals.json'
        before = config_path.read_bytes()
        cwd = Path.cwd()
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                with redirect_stdout(output), patch('pathlib.Path.write_text', side_effect=AssertionError('Unexpected write')), patch('socket.create_connection', side_effect=AssertionError('Unexpected network')):
                    self.assertEqual(signals.main(['validate-config']), 0)
                self.assertEqual(list(Path(directory).iterdir()), [])
            finally:
                os.chdir(cwd)
        self.assertEqual(config_path.read_bytes(), before)
        self.assertIn('Label calendar is unresolved', output.getvalue())

    def test_cli_returns_failure_for_a_missing_or_invalid_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = io.StringIO()
            with redirect_stderr(output):
                self.assertEqual(signals.main(['validate-config', '--project', str(root)]), 1)
                (root / 'broken.json').write_text('{}', encoding='utf-8')
                self.assertEqual(signals.main(['validate-config', '--project', str(root), '--config', 'broken.json']), 1)
            self.assertIn('Error:', output.getvalue())


if __name__ == '__main__':
    unittest.main()
