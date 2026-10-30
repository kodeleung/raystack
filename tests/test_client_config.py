import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from client_config import render_profile, ROUTING

class ClientConfigTests(unittest.TestCase):
    def test_hy2_is_in_profile(self):
        profile = render_profile({'mode': 'hy2', 'domain': 'hy2.example.com', 'hy2_password': 'test-secret'}, 123, 'UTC')
        self.assertIn('type: hysteria2', profile)
        self.assertIn('server: "hy2.example.com"', profile)
        self.assertIn('password: "test-secret"', profile)
        self.assertIn('      - raystack-hy2', profile)
        self.assertIn('skip-cert-verify: false', profile)

    def test_routing_for_every_mode(self):
        for mode in ('ws', 'reality', 'hy2'):
            with self.subTest(mode=mode):
                nodes = dict(mode=mode, domain='node.example.com', node_address='node.example.com', https_port=443, uuid='11111111-1111-4111-8111-111111111111', reality_sni='www.bing.com', reality_public_key='public', reality_short_id='aabb', hy2_password='test')
                profile = render_profile(nodes, 123, 'UTC')
                self.assertIn('    port: ' + ('443' if mode == 'ws' else '8443') + '\n', profile)
                self.assertIn('mode: rule\n', profile)
                self.assertIn('  - name: PROXY\n', profile)
                self.assertIn('  - name: FINAL\n', profile)
                self.assertIn('      - raystack-' + mode, profile)
                rules = profile.split('\nrules:\n')[1].strip().splitlines()
                self.assertEqual([line.strip() for line in rules], ['- RULE-SET,' + name + ',' + target for name, target in ROUTING] + ['- MATCH,FINAL'])
                self.assertEqual(len(ROUTING), 12)
                for name, _ in ROUTING:
                    self.assertIn('  ' + name + ':\n', profile)
                    self.assertIn('/' + name + '.txt"', profile)
                self.assertEqual(profile.count('behavior: "ipcidr"'), 3)
                self.assertEqual(profile.count('interval: 86400'), 12)
