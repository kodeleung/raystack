import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from client_config import render_profile

class ClientConfigTests(unittest.TestCase):
    def test_hy2_is_in_profile(self):
        profile = render_profile({'mode': 'hy2', 'domain': 'hy2.example.com', 'hy2_password': 'test-secret'}, 123, 'UTC')
        self.assertIn('type: hysteria2', profile)
        self.assertIn('server: "hy2.example.com"', profile)
        self.assertIn('password: "test-secret"', profile)
        self.assertIn('      - raystack-hy2', profile)
        self.assertIn('skip-cert-verify: false', profile)
