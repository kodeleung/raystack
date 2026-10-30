import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from render_config import render_configs, validate_values


def values():
    return {'domain': 'hy2.example.com', 'email': 'me@example.com', 'uuid': 'test-uuid',
            'reality_dest': 'www.bing.com:443', 'reality_sni': 'www.bing.com',
            'reality_private_key': 'private', 'reality_short_id': 'aabb',
            'hy2_password': 'a' * 64}


class RenderTests(unittest.TestCase):
    def test_hy2_uses_verified_acme_and_persistent_state(self):
        files = render_configs('hy2', values())
        self.assertEqual(list(files), ['etc/hysteria/config.yaml'])
        cfg = json.loads(files['etc/hysteria/config.yaml'])
        self.assertEqual(cfg['listen'], ':8443')
        self.assertEqual(cfg['acme']['ca'], 'letsencrypt')
        self.assertEqual(cfg['acme']['type'], 'http')
        self.assertEqual(cfg['acme']['dir'], '/var/lib/hysteria/acme')
        self.assertEqual(cfg['auth'], {'type': 'password', 'password': 'a' * 64})

    def test_xray_single_modes_and_force_ipv4(self):
        for mode in ('ws', 'reality'):
            files = render_configs(mode, values())
            cfg = json.loads(files['usr/local/etc/xray/config.json'])
            self.assertEqual(len(cfg['inbounds']), 1)
            self.assertEqual(cfg['outbounds'][0]['settings']['domainStrategy'], 'ForceIPv4')
            self.assertEqual('etc/caddy/Caddyfile' in files, mode == 'ws')
            if mode == 'ws':
                self.assertIn('https_port 443', files['etc/caddy/Caddyfile'])

    def test_bad_domains_email_and_removed_mode(self):
        for domain in ['https://bad.com', '*.bad.com', 'a.com\nfoo', 'a.com;foo', '-bad.com', '127.0.0.1']:
            with self.subTest(domain=domain), self.assertRaises(ValueError):
                render_configs('hy2', dict(values(), domain=domain))
        for email in ['no-at', 'a@b\nboom', 'a@']:
            with self.assertRaises(ValueError):
                render_configs('hy2', dict(values(), email=email))
        with self.assertRaises(ValueError):
            render_configs('both', values())
        with self.assertRaises(ValueError):
            render_configs('hy2', dict(values(), hy2_password=''))

    def test_normalization_and_safe_json(self):
        v = dict(values(), domain='HY2.Example.Com.', email='a+hy2@example.com')
        cfg = json.loads(render_configs('hy2', v)['etc/hysteria/config.yaml'])
        self.assertEqual(cfg['acme']['domains'], ['hy2.example.com'])
        v = dict(values(), uuid='quote"\\test')
        cfg = json.loads(render_configs('ws', v)['usr/local/etc/xray/config.json'])
        self.assertEqual(cfg['inbounds'][0]['settings']['clients'][0]['id'], v['uuid'])


if __name__ == '__main__':
    unittest.main()
