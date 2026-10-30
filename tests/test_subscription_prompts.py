import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from subscription_prompts import collect

class PromptTests(unittest.TestCase):
    def test_reality_settings(self):
        answers = io.StringIO('y\nsub.example.com\n1000\n15\n1\neth0\n2\n')
        with patch('sys.stdin', answers), patch('sys.stderr', io.StringIO()), patch('subprocess.check_output', return_value='default via 10.0.0.1 dev eth0'):
            result = collect('reality', '')
        self.assertEqual(result['subscription_domain'], 'sub.example.com')
        self.assertEqual(result['reset_day'], '15')
        self.assertEqual(result['accounting'], 'both')
    def test_opt_out(self):
        with patch('sys.stdin', io.StringIO('n\n')), patch('sys.stderr', io.StringIO()):
            self.assertIsNone(collect('reality', ''))

    def test_saved_defaults(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg = root / 'etc/raystack/traffic.json'
            cfg.parent.mkdir(parents=True)
            cfg.write_text(json.dumps({'subscription_domain': 'saved.example.com', 'traffic': {'quota_bytes': 2000000000, 'reset_day': 20, 'timezone': 'UTC', 'interface': 'ens3', 'accounting': 'both'}}))
            with patch('sys.stdin', io.StringIO('\n' * 7)), patch('sys.stderr', io.StringIO()), patch('subprocess.check_output', return_value=''):
                result = collect('reality', '', root=root)
            self.assertEqual((result['quota'], result['reset_day'], result['timezone'], result['interface'], result['accounting']), ('2', '20', 'UTC', 'ens3', 'both'))
