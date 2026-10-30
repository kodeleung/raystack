import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from deployment_state import inspect_installation, validate_listeners

REPO = Path(__file__).resolve().parents[1]


class DeploymentStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, value):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(value)
        return p

    def install_xray(self, mode):
        (self.root / 'etc/caddy/Caddyfile').unlink(missing_ok=True)
        self.write('etc/raystack/uuid', 'test-uuid')
        self.write('etc/raystack/reality-private-key', 'private')
        self.write('etc/raystack/reality-short-id', 'aabb')
        templates = ['ws', 'reality'] if mode == 'both' else [mode]
        cfg = None
        for m in templates:
            text = (REPO / f'config/xray-{m}.json').read_text()
            for key, value in {'UUID': 'test-uuid', 'REALITY_DEST': 'www.bing.com:443',
                               'REALITY_SNI': 'www.bing.com', 'REALITY_PRIVATE_KEY': 'private',
                               'REALITY_SHORT_ID': 'aabb'}.items():
                text = text.replace(f'__{key}__', value)
            part = json.loads(text)
            if cfg is None:
                cfg = part
            else:
                cfg['inbounds'] += part['inbounds']
        self.write('usr/local/etc/xray/config.json', json.dumps(cfg))
        if mode in ('ws', 'both'):
            port = '8443' if mode == 'both' else '443'
            text = (REPO / 'config/Caddyfile').read_text().replace('__DOMAIN__', 'test.example').replace('__HTTPS_PORT__', port)
            self.write('etc/caddy/Caddyfile', text)

    def test_clean_and_credentials_only(self):
        self.assertEqual(inspect_installation(self.root)['modes'], [])
        self.write('etc/raystack/uuid', 'old')
        self.assertEqual(inspect_installation(self.root)['modes'], [])

    def test_all_legacy_modes_without_marker(self):
        for mode in ('ws', 'reality', 'both'):
            with self.subTest(mode=mode):
                self.install_xray(mode)
                self.assertEqual(inspect_installation(self.root)['modes'], ['ws', 'reality'] if mode == 'both' else [mode])

    def test_custom_vless_and_malformed_config_rejected(self):
        self.install_xray('reality')
        p = self.root / 'usr/local/etc/xray/config.json'
        cfg = json.loads(p.read_text())
        cfg['inbounds'][0]['settings']['clients'].append({'id': 'someone-else'})
        p.write_text(json.dumps(cfg))
        with self.assertRaises(ValueError):
            inspect_installation(self.root)
        p.write_text('{broken')
        with self.assertRaises(ValueError):
            inspect_installation(self.root)

    def test_caddy_extra_site_symlinks_and_custom_unit_rejected(self):
        self.install_xray('ws')
        p = self.root / 'etc/caddy/Caddyfile'
        text = p.read_text()
        p.write_text(text + '\nother.example { respond "other" }')
        with self.assertRaises(ValueError):
            inspect_installation(self.root)
        p.unlink()
        target = self.write('custom-caddy', text)
        p.symlink_to(target)
        with self.assertRaises(ValueError):
            inspect_installation(self.root)
        p.unlink()
        p.write_text(text)
        self.write('etc/systemd/system/xray.service', '[Service]\nExecStart=/custom/server\n')
        with self.assertRaises(ValueError):
            inspect_installation(self.root)

    def test_unmanaged_caddy_and_inconsistent_marker_rejected(self):
        self.write('etc/caddy/Caddyfile', 'unrelated.example { respond "hello" }')
        with self.assertRaises(ValueError):
            inspect_installation(self.root)
        (self.root / 'etc/caddy/Caddyfile').unlink()
        self.install_xray('reality')
        self.write('etc/raystack/mode', 'hy2')
        with self.assertRaises(ValueError):
            inspect_installation(self.root)

    def test_experimental_subscription_caddy_is_recognized(self):
        for mode in ('ws', 'both'):
            with self.subTest(mode=mode):
                self.install_xray(mode)
                p = self.root / 'etc/caddy/Caddyfile'
                p.write_text(p.read_text().replace('  handle /ray* {', '  handle /subscription/* {\n    reverse_proxy 127.0.0.1:8765\n  }\n\n  handle /ray* {'))
                self.assertIn('caddy.service', inspect_installation(self.root)['services'])
        self.install_xray('reality')
        self.write('etc/caddy/Caddyfile', '{\n  https_port 8443\n}\ntest.example {\n  handle /subscription/* {\n    reverse_proxy 127.0.0.1:8765\n  }\n  handle {\n    respond "OK"\n  }\n}\n')
        state = inspect_installation(self.root)
        self.assertIn('caddy.service', state['services'])
        self.assertIn('etc/caddy/Caddyfile', state['managed_paths'])

    def test_unknown_xray_with_combined_caddy(self):
        self.install_xray('both')
        self.write('usr/local/etc/xray/config.json', '{"legacy": true}')
        self.assertEqual(inspect_installation(self.root, replace_xray=True)['modes'], ['ws', 'reality'])

    def test_listener_ownership(self):
        state = {'services': ['xray.service']}
        validate_listeners(state, 'hy2', [{'transport': 'tcp', 'port': 443, 'service': 'xray.service'}])
        for transport, port in [('tcp', 80), ('udp', 443)]:
            with self.assertRaises(ValueError):
                validate_listeners(state, 'hy2', [{'transport': transport, 'port': port, 'service': 'unrelated.service'}])


if __name__ == '__main__':
    unittest.main()
