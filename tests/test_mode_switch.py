import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from deployment import Deployment, snapshot_installation, restore_installation
from deployment_state import inspect_installation, SERVICES
from test_render_config import values
import test_deployment_state as state_tests


class FakeServices:
    def __init__(self):
        self.states = {}
        self.events = []
        self.fail = set()
        self.wait_failure = False

    def state(self, service):
        return dict(self.states.get(service, {'enabled': 'disabled', 'active': False}))

    def action(self, verb, service=None):
        self.events.append((verb, service))
        if (verb, service) in self.fail:
            raise RuntimeError('simulated service failure')
        if service is None:
            return
        state = self.states.setdefault(service, {'enabled': 'disabled', 'active': False})
        if verb in ('start', 'restart'):
            state['active'] = True
        elif verb == 'stop':
            state['active'] = False
        elif verb == 'enable':
            state['enabled'] = 'enabled'
        elif verb == 'disable':
            state['enabled'] = 'disabled'

    def validate(self, mode, stage):
        pass

    def wait(self, mode):
        if self.wait_failure:
            raise RuntimeError('simulated ACME timeout')

    def sockets(self, services):
        return []


class SwitchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.services = FakeServices()
        self.deploy = Deployment(self.root, self.services)

    def install(self, mode):
        self.deploy.install(mode, values(), prepare=lambda mode: None)

    def test_all_six_switches_leave_only_selected_mode(self):
        for old in ('ws', 'reality', 'hy2'):
            for new in ('ws', 'reality', 'hy2'):
                if old == new:
                    continue
                with self.subTest(old=old, new=new):
                    self.install(old)
                    self.install(new)
                    self.assertEqual(inspect_installation(self.root)['modes'], [new])
                    for mode, names in SERVICES.items():
                        for service in names:
                            expected = service in SERVICES[new]
                            self.assertEqual(self.services.state(service)['active'], expected)
                            self.assertEqual(self.services.state(service)['enabled'] == 'enabled', expected)

    def test_unknown_xray_replaced_and_backed_up(self):
        path = self.root / 'usr/local/etc/xray/config.json'
        path.parent.mkdir(parents=True)
        path.write_text('{"legacy": true}')
        self.services.states['xray.service'] = {'enabled': 'enabled', 'active': True}
        self.install('reality')
        self.assertEqual(inspect_installation(self.root)['modes'], ['reality'])
        snapshots = list((self.root / 'etc/raystack/backups').glob('*/snapshot.json'))
        snapshot = json.loads(snapshots[0].read_text())
        import base64
        self.assertEqual(base64.b64decode(snapshot['files']['usr/local/etc/xray/config.json']['data']), b'{"legacy": true}')

    def test_unmanaged_caddy_is_preserved_for_reality_and_hy2(self):
        path = self.root / 'usr/local/etc/xray/config.json'
        path.parent.mkdir(parents=True)
        path.write_text('{"legacy": true}')
        caddy = self.root / 'etc/caddy/Caddyfile'
        caddy.parent.mkdir(parents=True)
        caddy.write_text('unrelated.example { respond "hello" }')
        self.services.states['caddy.service'] = {'enabled': 'enabled', 'active': True}
        self.install('reality')
        self.assertEqual(caddy.read_text(), 'unrelated.example { respond "hello" }')
        self.assertTrue(self.services.state('caddy.service')['active'])
        self.assertNotIn(('stop', 'caddy.service'), self.services.events)
        self.install('hy2')
        self.assertEqual(caddy.read_text(), 'unrelated.example { respond "hello" }')
        self.assertTrue(self.services.state('caddy.service')['active'])

    def test_unknown_xray_restored_when_install_fails(self):
        path = self.root / 'usr/local/etc/xray/config.json'
        path.parent.mkdir(parents=True)
        path.write_text('{"legacy": true}')
        self.services.states['xray.service'] = {'enabled': 'enabled', 'active': True}
        self.services.wait_failure = True
        with self.assertRaises(RuntimeError):
            self.install('reality')
        self.assertEqual(path.read_text(), '{"legacy": true}')
        self.assertTrue(self.services.state('xray.service')['active'])

    def test_legacy_hy2_port_is_upgraded(self):
        self.install('hy2')
        path = self.root / 'etc/hysteria/config.yaml'
        cfg = json.loads(path.read_text())
        cfg['listen'] = ':443'
        path.write_text(json.dumps(cfg))
        self.install('hy2')
        self.assertEqual(json.loads(path.read_text())['listen'], ':8443')

    def test_prepare_failure_does_not_stop_old_service(self):
        self.install('ws')
        self.services.events.clear()
        def fail(mode):
            raise RuntimeError('download failed')
        with self.assertRaisesRegex(RuntimeError, 'download failed'):
            self.deploy.install('hy2', values(), prepare=fail)
        self.assertEqual(inspect_installation(self.root)['modes'], ['ws'])
        self.assertFalse(any(verb == 'stop' for verb, _ in self.services.events))

    def test_failed_switch_restores_configs_and_states(self):
        self.install('ws')
        before = (self.root / 'etc/caddy/Caddyfile').read_bytes()
        self.services.states['caddy.service'] = {'enabled': 'disabled', 'active': False}
        self.services.fail.add(('start', 'hysteria-server.service'))
        with self.assertRaises(RuntimeError):
            self.install('hy2')
        self.assertEqual(inspect_installation(self.root)['modes'], ['ws'])
        self.assertEqual((self.root / 'etc/caddy/Caddyfile').read_bytes(), before)
        self.assertEqual(self.services.state('caddy.service'), {'enabled': 'disabled', 'active': False})
        self.assertTrue(self.services.state('xray.service')['active'])
        self.assertFalse(self.services.state('hysteria-server.service')['active'])

    def test_timeout_on_fresh_install_leaves_no_marker_or_config(self):
        self.services.wait_failure = True
        with self.assertRaisesRegex(RuntimeError, 'ACME timeout'):
            self.install('hy2')
        self.assertFalse((self.root / 'etc/raystack/mode').exists())
        self.assertFalse((self.root / 'etc/hysteria/config.yaml').exists())
        self.assertFalse(self.services.state('hysteria-server.service')['active'])

    def test_reinstall_preserves_password_and_backups_are_private(self):
        self.install('hy2')
        p = self.root / 'etc/raystack/hy2-password'
        self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        self.deploy.install('hy2', dict(values(), hy2_password='b' * 64), prepare=lambda mode: None)
        self.assertEqual(p.read_text().strip(), 'a' * 64)
        for directory in (self.root / 'etc/raystack/backups').iterdir():
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)

    def test_rollback_failure_is_reported(self):
        self.install('reality')
        self.services.fail.add(('start', 'hysteria-server.service'))
        self.services.fail.add(('start', 'xray.service'))
        with self.assertRaisesRegex(RuntimeError, 'rollback also failed'):
            self.install('hy2')

    def test_legacy_mixed_install_is_consolidated(self):
        fixture = state_tests.DeploymentStateTests()
        fixture.root = self.root
        fixture.install_xray('both')
        for service in ('xray.service', 'caddy.service'):
            self.services.states[service] = {'enabled': 'enabled', 'active': True}
        self.install('hy2')
        self.assertEqual(inspect_installation(self.root)['modes'], ['hy2'])
        self.assertFalse((self.root / 'usr/local/etc/xray/config.json').exists())

    def test_lost_marker_is_adopted_and_lock_blocks_second_run(self):
        self.install('reality')
        (self.root / 'etc/raystack/mode').unlink()
        self.install('hy2')
        self.assertEqual(inspect_installation(self.root)['modes'], ['hy2'])
        with self.deploy.lock():
            with self.assertRaisesRegex(RuntimeError, 'Another raystack'):
                self.install('ws')

    def test_snapshot_restores_modes_and_absence(self):
        self.install('ws')
        path = self.root / 'etc/caddy/Caddyfile'
        path.chmod(0o640)
        backup = self.root / 'snapshot'
        snapshot_installation(self.root, inspect_installation(self.root), backup, {})
        path.write_text('wrong')
        path.chmod(0o600)
        absent = self.root / 'etc/hysteria/config.yaml'
        absent.parent.mkdir(parents=True, exist_ok=True)
        absent.write_text('new')
        restore_installation(self.root, backup)
        self.assertIn(values()['domain'], path.read_text())
        self.assertEqual(path.stat().st_mode & 0o777, 0o640)
        self.assertFalse(absent.exists())

    def test_fresh_install_rollback_skips_previously_missing_units(self):
        self.services.state = lambda service: {'enabled': 'not-found', 'active': False}
        self.services.wait_failure = True
        with self.assertRaisesRegex(RuntimeError, 'ACME timeout'):
            self.install('hy2')
        # Target is stopped before its temporary unit is removed, not afterwards.
        self.assertEqual(self.services.events.count(('stop', 'hysteria-server.service')), 1)


if __name__ == '__main__': unittest.main()
