import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from traffic import cycle_bounds, quota_bytes, query_usage, StatisticsUnavailable, GB_BYTES, quota_total, saved_quota_gb
from unittest.mock import patch
import json

class BillingTests(unittest.TestCase):
    def test_decimal_quota(self):
        self.assertEqual(quota_bytes('1.5'), 1610612736)
        for value in ('0', '-1', 'NaN', 'Infinity', '0.0000000001'):
            with self.assertRaises(ValueError):
                quota_bytes(value)

    def test_month_end_and_timezone(self):
        start, end = cycle_bounds(datetime(2028, 3, 1, tzinfo=timezone.utc), 31, 'Asia/Shanghai')
        self.assertEqual(start.isoformat(), '2028-02-29T00:00:00+08:00')
        self.assertEqual(end.isoformat(), '2028-03-31T00:00:00+08:00')

    def test_reset_boundary(self):
        start, _ = cycle_bounds(datetime(2026, 10, 14, 16, tzinfo=timezone.utc), 15, 'Asia/Shanghai')
        self.assertEqual(start.isoformat(), '2026-10-15T00:00:00+08:00')

    def test_daily_usage(self):
        settings = {'reset_day': 15, 'timezone': 'UTC', 'interface': 'eth0', 'accounting': 'both', 'quota_bytes': 1000, 'quota_unit_bytes': GB_BYTES}
        fixture = {'interfaces': [{'name': 'eth0', 'traffic': {'day': [
            {'date': {'year': 2026, 'month': 10, 'day': 14}, 'rx': 100, 'tx': 100},
            {'date': {'year': 2026, 'month': 10, 'day': 15}, 'rx': 2, 'tx': 7},
        ]}}]}
        with patch('subprocess.check_output', return_value=json.dumps(fixture).encode()):
            usage = query_usage(settings, datetime(2026, 10, 16, tzinfo=timezone.utc))
            self.assertEqual((usage['upload'], usage['download']), (2, 7))
            settings['accounting'] = 'outbound'
            usage = query_usage(settings, datetime(2026, 10, 16, tzinfo=timezone.utc))
            self.assertEqual((usage['upload'], usage['download']), (0, 7))
        fixture['interfaces'][0]['traffic']['day'] = []
        with patch('subprocess.check_output', return_value=json.dumps(fixture).encode()):
            with self.assertRaises(StatisticsUnavailable):
                query_usage(settings, datetime(2026, 10, 16, tzinfo=timezone.utc))
        with patch('subprocess.check_output', return_value=b'bad json'):
            with self.assertRaises(StatisticsUnavailable):
                query_usage(settings, datetime(2026, 10, 16, tzinfo=timezone.utc))

    def test_binary_quota_and_legacy_migration(self):
        for entered in (1000, 750):
            self.assertEqual(quota_bytes(entered), entered * 1024 ** 3)
            legacy = {'quota_bytes': entered * 1000 ** 3}
            migrated = {'quota_bytes': quota_total(legacy), 'quota_unit_bytes': GB_BYTES}
            self.assertEqual(saved_quota_gb(legacy), entered)
            self.assertEqual(saved_quota_gb(migrated), entered)
            self.assertEqual(quota_total(legacy), quota_total(migrated))
        self.assertEqual(quota_bytes('0.1'), 107374182)
