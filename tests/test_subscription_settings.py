import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from subscription_settings import build_settings

class SubscriptionSettingsTests(unittest.TestCase):
    def test_all_modes_and_token_reuse(self):
        for mode in ('ws', 'reality', 'hy2'):
            values = {'domain': 'node.example.com', 'uuid': 'uuid', 'hy2_password': 'password'}
            a = build_settings(mode, values, '1.5', '31', 'Asia/Shanghai', 'eth0', 'both', 'sub.example.com')
            self.assertEqual(a['traffic']['quota_bytes'], 1500000000)
            self.assertEqual(a['nodes']['node_address'], 'sub.example.com' if mode == 'reality' else 'node.example.com')
            b = build_settings(mode, values, '2', '1', 'Asia/Shanghai', 'eth0', 'outbound', 'sub.example.com', a)
            self.assertEqual(a['token'], b['token'])
    def test_reject_invalid_and_changing_series(self):
        args = ('reality', {}, '1', '1', 'UTC', 'eth0', 'both', 'sub.example.com')
        previous = build_settings(*args)
        for bad in [args[:3] + ('32',) + args[4:], args[:4] + ('invalid',) + args[5:],
                    args[:5] + ('lo',) + args[6:], args[:6] + ('max',) + args[7:]]:
            with self.assertRaises(ValueError): build_settings(*bad)
        with self.assertRaises(ValueError):
            build_settings(*args[:4], 'Asia/Shanghai', *args[5:], previous=previous)
