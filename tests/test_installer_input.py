import base64
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from installer_input import collect_values


class InputTests(unittest.TestCase):
    def test_hy2_password_and_reuse(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            v = collect_values('hy2', 'hy2.example.com', 'a@example.com', root=root)
            self.assertRegex(v['hy2_password'], r'^[0-9a-f]{64}$')
            self.assertNotIn('uuid', v)
            p = root / 'etc/raystack/hy2-password'
            p.parent.mkdir(parents=True)
            p.write_text('a' * 64)
            self.assertEqual(collect_values('hy2', 'hy2.example.com', 'a@example.com', root=root)['hy2_password'], 'a' * 64)

    def test_reality_keys_without_xray_dependency(self):
        with tempfile.TemporaryDirectory() as temp:
            v = collect_values('reality', '', '', root=Path(temp))
            for name in ('reality_private_key', 'reality_public_key'):
                self.assertEqual(len(base64.urlsafe_b64decode(v[name] + '=')), 32)
            self.assertEqual(len(v['reality_short_id']), 16)

    def test_bad_input_fails_before_key_generation(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp, patch('installer_input.subprocess.check_output') as run:
            with self.assertRaises(ValueError):
                collect_values('hy2', 'https://wrong', 'email', root=Path(temp))
            run.assert_not_called()


if __name__ == '__main__': unittest.main()
