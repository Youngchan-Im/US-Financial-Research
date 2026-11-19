"""Check the dataset, target timing and source policy for Signals research."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit


class ConfigError(ValueError):
    """The prediction settings are incomplete or inconsistent."""


def require_value(settings, name, expected):
    actual = settings.get(name)
    if type(actual) is not type(expected) or actual != expected:
        raise ConfigError(f'{name} must be {expected!r}')


def require_url(value, name):
    if not isinstance(value, str):
        raise ConfigError(f'{name} must be an HTTPS source URL')
    url = urlsplit(value)
    if url.scheme != 'https' or not url.hostname or url.username or url.password:
        raise ConfigError(f'{name} must be an HTTPS source URL')


def validate_config(config):
    if not isinstance(config, dict):
        raise ConfigError('The prediction config must be a JSON object')
    for name, expected in {
        'data_version': 'signals/v3.1',
        'target': 'target_jupiter_60',
        'identifier': 'numerai_ticker',
        'label_lag': 2,
        'label_horizon': 60,
        'macro_enabled': False,
    }.items():
        require_value(config, name, expected)

    sections = {
        'label_calendar': {'status': 'unresolved'},
        'cutoff_policy': {
            'feature_date': 'market_close_date',
            'availability': 'available_at <= prediction_cutoff',
            'unknown_release_time': 'next_exchange_session',
            'timestamp_timezone': 'UTC',
        },
        'submission': {
            'minimum_tickers': 100,
            'signal_column': 'signal',
            'lower_bound': 0,
            'upper_bound': 1,
            'bounds': 'exclusive',
        },
    }
    for section, expected in sections.items():
        settings = config.get(section)
        if not isinstance(settings, dict):
            raise ConfigError(f'{section} must be a JSON object')
        for name, value in expected.items():
            try:
                require_value(settings, name, value)
            except ConfigError as error:
                raise ConfigError(f'{section}.{error}') from None

    sources = config.get('sources')
    if not isinstance(sources, list):
        raise ConfigError('sources must list the current data-use decisions')
    decisions = {}
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get('id'), str):
            raise ConfigError('Each source needs an ID')
        identifier = source['id']
        if identifier in decisions:
            raise ConfigError(f'Duplicate source: {identifier}')
        require_url(source.get('reference_url'), f'{identifier}.reference_url')
        if type(source.get('training_allowed')) is not bool:
            raise ConfigError(f'{identifier}.training_allowed must be Boolean')
        if not isinstance(source.get('use'), str) or not source['use'].strip():
            raise ConfigError(f'{identifier}.use must describe its current use')
        reason = source.get('reason')
        if not source['training_allowed'] and (not isinstance(reason, str) or not reason.strip()):
            raise ConfigError(f'{identifier} needs a reason for excluding training')
        decisions[identifier] = source
    policy = {'numerai_signals': True, 'sec_companyfacts': False, 'fred': False}
    if set(decisions) != set(policy):
        raise ConfigError('sources must identify Numerai, SEC and FRED')
    for identifier, allowed in policy.items():
        if decisions[identifier]['training_allowed'] is not allowed:
            raise ConfigError(f'{identifier}: training differs from the current source policy')
    require_url(config.get('target_definition_url'), 'target_definition_url')
    return config


def load_config(path):
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ConfigError(f'Duplicate JSON key: {key}')
            result[key] = value
        return result

    def reject_constant(value):
        raise ConfigError(f'Non-finite JSON value: {value}')

    with Path(path).open(encoding='utf-8-sig') as stream:
        config = json.load(stream, object_pairs_hook=unique_keys, parse_constant=reject_constant)
    return validate_config(config)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('validate-config')
    command.add_argument('--project', type=Path, default=Path(__file__).resolve().parents[1])
    command.add_argument('--config', type=Path, default=Path('config/signals.json'))
    args = parser.parse_args(argv)
    try:
        config = load_config(args.project / args.config)
    except (OSError, ValueError, TypeError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1
    print(f'Config valid: {config["data_version"]}, {config["target"]}. Label calendar is unresolved.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
