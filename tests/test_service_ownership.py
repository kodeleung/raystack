import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from deployment_state import validate_unit
from deployment import Deployment
from test_mode_switch import FakeServices

COMMAND = '/usr/local/bin/xray run -config /usr/local/etc/xray/config.json'


class UnitOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, relative, text):
        p = self.root / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def test_spaced_custom_command_and_non_exec_overrides_are_rejected(self):
        for text in ('[Service]\nExecStart = /custom/server\n',
                     '[Service]\nExecStart=' + COMMAND + '\nEnvironment=LD_PRELOAD=/custom/lib.so\n',
                     '[Service]\nExecStart=' + COMMAND + '\nMemoryMax=512M\n'):
            with self.subTest(text=text):
                self.write('etc/systemd/system/xray.service', text)
                with self.assertRaises(ValueError):
                    validate_unit(self.root, 'xray.service')

    def test_custom_dropins_at_all_precedence_levels_are_rejected(self):
        self.write('etc/systemd/system/xray.service', '[Service]\nExecStart=' + COMMAND + '\n')
        for base in ('etc/systemd/system', 'run/systemd/system', 'usr/lib/systemd/system', 'usr/local/lib/systemd/system'):
            for directory in ('xray.service.d', 'service.d'):
                with self.subTest(base=base, directory=directory):
                    p = self.write(base + '/' + directory + '/99-custom.conf', '[Service]\nEnvironment=HTTP_PROXY=http://custom:8080\n')
                    with self.assertRaises(ValueError):
                        validate_unit(self.root, 'xray.service')
                    p.unlink()

    def test_runtime_fragment_and_control_overrides_are_rejected(self):
        for base in ('run/systemd/system', 'etc/systemd/system.control', 'run/systemd/system.control',
                     'run/systemd/generator', 'run/systemd/generator.early', 'run/systemd/generator.late'):
            with self.subTest(base=base):
                p = self.write(base + '/xray.service', '[Service]\nExecStart = /custom/server\n')
                with self.assertRaises(ValueError):
                    validate_unit(self.root, 'xray.service')
                p.unlink()

    def test_shadowed_vendor_unit_is_not_confused_with_effective_unit(self):
        self.write('usr/lib/systemd/system/xray.service', '[Service]\nExecStart=/custom/vendor\n')
        self.write('etc/systemd/system/xray.service', '[Service]\nExecStart = ' + COMMAND + '\n')
        validate_unit(self.root, 'xray.service')
        self.write('run/systemd/system/xray.service.d/99-custom.conf', '[Service]\nExecStart=\nExecStart=/custom/runtime\n')
        with self.assertRaises(ValueError):
            validate_unit(self.root, 'xray.service')

    def test_known_upstream_xray_reset_override_is_accepted(self):
        self.write('etc/systemd/system/xray.service', '[Service]\nExecStart=' + COMMAND + '\n')
        self.write('etc/systemd/system/xray.service.d/10-donot_touch_single_conf.conf',
                   '# upstream installer\n[Service]\nExecStart=\nExecStart=' + COMMAND + '\n')
        validate_unit(self.root, 'xray.service')

    def test_caddy_keeps_package_certificate_storage(self):
        directory = self.root / 'var/lib/caddy/.local/share/caddy/certificates'
        directory.mkdir(parents=True)
        (directory / 'saved-certificate').write_text('existing certificate')
        Deployment(self.root, FakeServices()).write_units('ws')
        unit = (self.root / 'etc/systemd/system/caddy.service').read_text()
        self.assertIn('Environment=XDG_DATA_HOME=/var/lib/caddy/.local/share\n', unit)
        self.assertIn('Environment=XDG_CONFIG_HOME=/var/lib/caddy/.config\n', unit)
        self.assertEqual((directory / 'saved-certificate').read_text(), 'existing certificate')


if __name__ == '__main__': unittest.main()
