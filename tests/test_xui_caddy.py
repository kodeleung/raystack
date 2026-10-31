import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import xui_caddy as xui


class Services:
    def __init__(self):
        self.actions = []

    def state(self, name):
        return {'enabled': 'enabled', 'active': True}

    def action(self, verb, name=None):
        self.actions.append((verb, name))


class XuiCaddyTests(unittest.TestCase):
    def test_internal_ports_and_public_urls(self):
        p = xui.settings_patch({'webPort': '443', 'subPort': '443'}, 'panel.example.com', 'sub.example.com')
        self.assertEqual((p['webPort'], p['subPort']), ('38023', '2096'))
        self.assertEqual(p['subURI'], 'https://sub.example.com/sub/')
        self.assertEqual(p['subListen'], '127.0.0.1')
        self.assertEqual(p['subCertFile'], '')
        p = xui.settings_patch({'webPort': '2096', 'subPort': '2096'}, 'panel.example.com', 'sub.example.com')
        self.assertEqual(p['subPort'], '2097')

    def test_reject_invalid_input_and_domain_collisions(self):
        for domains in [('a.example.com', 'a.example.com'), ('a.example.com\n{', 'b.example.com')]:
            with self.assertRaises(ValueError):
                xui.settings_patch({}, *domains)
        with self.assertRaises(ValueError):
            xui.settings_patch({'subPath': '/bad?x/'}, 'a.example.com', 'b.example.com')
        with self.assertRaises(ValueError):
            xui.check_hosts({'route': [{'match': [{'host': ['*.example.com']}]}]}, ['sub.example.com'])

    def fixture(self, root):
        main = root / xui.FILES[0]
        main.parent.mkdir(parents=True)
        main.write_text('other.example.com {\n respond "keep me"\n}\n')
        main.chmod(0o640)
        db = root / 'etc/x-ui/x-ui.db'
        db.parent.mkdir(parents=True)
        with xui.database(db) as c:
            c.execute('CREATE TABLE settings(id INTEGER PRIMARY KEY, key TEXT UNIQUE, value TEXT)')
            c.executemany('INSERT INTO settings(key,value) VALUES (?,?)',
                          [('webPort', '38023'), ('subPort', '443'), ('webBasePath', '/private/'),
                           ('subPath', '/random/'), ('subCertFile', '/keep/cert')])
            c.execute('CREATE TABLE clients(auth TEXT)')
            c.execute("INSERT INTO clients VALUES ('keep-credential')")
        return main, db

    def test_preserves_sites_credentials_and_repeated_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            main, db = self.fixture(root)
            services = Services()
            with patch.object(xui, 'SystemServices', return_value=services), \
                 patch.object(xui, 'run', return_value=json.dumps({'apps': {}})), \
                 patch.object(xui, 'wait_local'), patch.object(xui, 'certificates', return_value={}), \
                 patch.object(xui, 'caddy_data_dir', return_value=root):
                for _ in range(2):
                    xui.configure(root, 'panel.example.com', 'sub.example.com')
            self.assertIn('respond "keep me"', main.read_text())
            self.assertEqual(main.read_text().count(xui.IMPORT), 1)
            self.assertEqual(main.stat().st_mode & 0o777, 0o640)
            with xui.database(db) as c:
                settings = dict(c.execute('SELECT key,value FROM settings'))
                self.assertEqual(settings['subURI'], 'https://sub.example.com/random/')
                self.assertEqual(c.execute('SELECT auth FROM clients').fetchone()[0], 'keep-credential')
            snippet = (root / xui.FILES[1]).read_text()
            self.assertIn('https://panel.example.com:443', snippet)
            self.assertIn('redir / /private/ 302', snippet)

    def test_failure_restores_database_files_and_services(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            main, db = self.fixture(root)
            original = main.read_bytes()
            services = Services()
            def command(args):
                if 'validate' in args:
                    raise RuntimeError('invalid staged config')
                return '{}'
            with patch.object(xui, 'SystemServices', return_value=services), \
                 patch.object(xui, 'run', side_effect=command):
                with self.assertRaisesRegex(RuntimeError, 'invalid staged config'):
                    xui.configure(root, 'panel.example.com', 'sub.example.com')
            self.assertEqual(main.read_bytes(), original)
            self.assertFalse((root / xui.FILES[1]).exists())
            with xui.database(db) as c:
                self.assertEqual(dict(c.execute('SELECT key,value FROM settings'))['subPort'], '443')
            self.assertIn(('start', 'x-ui.service'), services.actions)
            backup = next((root / 'etc/raystack/backups').iterdir())
            self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
            self.assertEqual((backup / 'x-ui.db').stat().st_mode & 0o777, 0o600)

    def test_certificate_summary_only_returns_existing_pairs(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            p = data / 'certificates/acme.example/panel.example.com/panel.example.com.crt'
            p.parent.mkdir(parents=True)
            p.write_text('certificate')
            self.assertEqual(xui.certificates(['panel.example.com'], data, timeout=0), {})
            p.with_suffix('.key').write_text('private key')
            self.assertEqual(xui.certificates(['panel.example.com'], data, timeout=0),
                             {'panel.example.com': (p, p.with_suffix('.key'))})

    def test_fresh_caddy_service_is_created(self):
        class Fresh(Services):
            def state(self, name):
                if name == 'caddy.service':
                    return {'enabled': 'not-found', 'active': False}
                return super().state(name)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            services = Fresh()
            with patch.object(xui, 'SystemServices', return_value=services), \
                 patch.object(xui, 'ensure_account') as account, \
                 patch.object(xui, 'run', return_value='{}'), \
                 patch.object(xui, 'wait_local'), patch.object(xui, 'certificates', return_value={}), \
                 patch.object(xui, 'caddy_data_dir', return_value=root):
                xui.configure(root, 'panel.example.com', 'sub.example.com')
            account.assert_called_once_with('caddy')
            unit = (root / xui.FILES[2]).read_text()
            self.assertIn('User=caddy', unit)
            self.assertIn('--config /etc/caddy/Caddyfile', unit)
            self.assertIn(('start', 'caddy.service'), services.actions)

    def test_readiness_failure_restores_original_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            main, db = self.fixture(root)
            original = main.read_bytes()
            with patch.object(xui, 'SystemServices', return_value=Services()), \
                 patch.object(xui, 'run', return_value='{}'), \
                 patch.object(xui, 'wait_local', side_effect=RuntimeError('port conflict')):
                with self.assertRaisesRegex(RuntimeError, 'port conflict'):
                    xui.configure(root, 'panel.example.com', 'sub.example.com')
            self.assertEqual(main.read_bytes(), original)
            with xui.database(db) as conn:
                self.assertEqual(dict(conn.execute('select key,value from settings'))['subPort'], '443')

    def test_existing_domain_conflict_happens_before_service_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            main, _ = self.fixture(root)
            original = main.read_bytes()
            services = Services()
            with patch.object(xui, 'SystemServices', return_value=services), \
                 patch.object(xui, 'run', return_value=json.dumps({'match': [{'host': ['panel.example.com']}]})):
                with self.assertRaisesRegex(ValueError, 'already has a site'):
                    xui.configure(root, 'panel.example.com', 'sub.example.com')
            self.assertEqual(main.read_bytes(), original)
            self.assertEqual(services.actions, [])


if __name__ == '__main__':
    unittest.main()
