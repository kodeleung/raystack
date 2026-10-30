import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from deployment import Deployment
from deployment_state import inspect_installation
from test_mode_switch import FakeServices
from test_render_config import values

OPTIONS = dict(quota='1000', reset_day='15', timezone='Asia/Shanghai', interface='eth0', accounting='both', subscription_domain='test.example.com')

class SubscriptionDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.services = FakeServices()
        self.deploy = Deployment(self.root, self.services)
    def install(self, mode, enabled=True):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = self.deploy.install(mode, values(), prepare=lambda mode: None, subscription=OPTIONS if enabled else None)
        return result, output.getvalue()
    def test_all_modes_switch_reuse_token_and_emit_url(self):
        token = None
        for mode in ('reality', 'ws', 'hy2', 'reality'):
            _, output = self.install(mode)
            config = json.loads((self.root / 'etc/raystack/traffic.json').read_text())
            if token: self.assertEqual(config['token'], token)
            token = config['token']
            self.assertIn('Subscription URL: https://test.example.com:9443/subscription/', output)
            caddy_text = (self.root / 'etc/caddy/Caddyfile').read_text()
            self.assertNotIn('https_port', caddy_text)
            self.assertIn('test.example.com:9443 {', caddy_text)
            if mode == 'reality':
                self.assertEqual(json.loads((self.root / 'usr/local/etc/xray/config.json').read_text())['inbounds'][0]['port'], 8443)
            self.assertEqual(config['nodes']['mode'], mode)
            self.assertIn('caddy.service', inspect_installation(self.root)['services'])
            self.assertTrue(self.services.state('raystack-subscription.service')['active'])
            if mode == 'hy2':
                cfg = json.loads((self.root / 'etc/hysteria/config.yaml').read_text())
                self.assertEqual(cfg['acme']['http']['altPort'], 8888)
    def test_previous_subscription_ports_can_be_upgraded(self):
        from subscription_deployment import legacy_caddy_config
        self.install('reality')
        saved = json.loads((self.root / 'etc/raystack/traffic.json').read_text())
        caddy = self.root / 'etc/caddy/Caddyfile'
        caddy.write_text(legacy_caddy_config('reality', saved['subscription_domain']))
        xray = self.root / 'usr/local/etc/xray/config.json'
        config = json.loads(xray.read_text())
        config['inbounds'][0]['port'] = 443
        xray.write_text(json.dumps(config))
        self.install('reality')
        self.assertIn(':9443 {', caddy.read_text())
        self.assertEqual(json.loads(xray.read_text())['inbounds'][0]['port'], 8443)

    def test_enabled_caddy_with_legacy_explicit_port_is_adopted(self):
        xray = self.root / 'usr/local/etc/xray/config.json'
        xray.parent.mkdir(parents=True)
        xray.write_text('{"legacy": true}')
        caddy = self.root / 'etc/caddy/Caddyfile'
        caddy.parent.mkdir(parents=True)
        old = '# Package header\nlegacy.example.com:8443 {\n handle /ray* { reverse_proxy 127.0.0.1:10000 }\n handle { respond "OK" }\n}\n'
        caddy.write_text(old)
        self.services.states['caddy.service'] = {'enabled': 'enabled', 'active': True}
        self.services.states['xray.service'] = {'enabled': 'enabled', 'active': True}
        _, output = self.install('reality')
        self.assertIn('Subscription URL:', output)
        self.assertTrue(self.services.state('caddy.service')['active'])
        snapshot = next((self.root / 'etc/raystack/backups').glob('*/snapshot.json'))
        import base64
        record = json.loads(snapshot.read_text())['files']['etc/caddy/Caddyfile']
        self.assertEqual(base64.b64decode(record['data']).decode(), old)

    def test_failure_restores_previous_profile_and_services(self):
        self.install('reality')
        previous = (self.root / 'etc/raystack/traffic.json').read_bytes()
        previous_caddy = (self.root / 'etc/caddy/Caddyfile').read_bytes()
        self.services.wait_failure = True
        with self.assertRaises(RuntimeError): self.install('hy2')
        self.assertEqual((self.root / 'etc/raystack/traffic.json').read_bytes(), previous)
        self.assertEqual((self.root / 'etc/caddy/Caddyfile').read_bytes(), previous_caddy)
        self.assertTrue(self.services.state('raystack-subscription.service')['active'])
    def test_unrelated_caddy_and_custom_overrides_are_preserved(self):
        caddy = self.root / 'etc/caddy/Caddyfile'
        caddy.parent.mkdir(parents=True)
        caddy.write_text('unrelated.example { respond "hello" }')
        with self.assertRaisesRegex(ValueError, 'unrelated Caddy'):
            self.install('reality')
        self.assertEqual(caddy.read_text(), 'unrelated.example { respond "hello" }')
        caddy.unlink()
        drop = self.root / 'run/systemd/system/raystack-subscription.service.d/custom.conf'
        drop.parent.mkdir(parents=True)
        drop.write_text('[Service]\nExecStart=/custom\n')
        with self.assertRaisesRegex(ValueError, 'custom systemd overrides'):
            self.install('reality')
        self.assertTrue(drop.exists())

    def test_usrmerge_lib_symlink(self):
        for target in ('usr/lib', '/usr/lib'):
            with self.subTest(target=target):
                lib = self.root / 'lib'
                lib.symlink_to(target)
                try:
                    self.install('reality')
                finally:
                    lib.unlink()

    def test_unrecognized_lib_symlink_still_rejected(self):
        (self.root / 'lib').symlink_to('custom-lib')
        with self.assertRaisesRegex(ValueError, '/lib symlink'):
            self.install('reality')

    def test_disabling_subscription_stops_services(self):
        self.install('reality')
        self.install('reality', False)
        self.assertFalse(self.services.state('raystack-subscription.service')['active'])
        self.assertFalse(json.loads((self.root / 'etc/raystack/traffic.json').read_text())['enabled'])
        token = json.loads((self.root / 'etc/raystack/traffic.json').read_text())['token']
        self.install('reality')
        self.assertEqual(json.loads((self.root / 'etc/raystack/traffic.json').read_text())['token'], token)
