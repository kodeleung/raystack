import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import runtime_install as runtime


class RuntimeTests(unittest.TestCase):
    def test_hy2_only_prepares_its_runtime(self):
        with patch.object(runtime, 'ensure_binary') as binary, patch.object(runtime, 'ensure_account') as account:
            runtime.prepare_runtime('hy2')
        binary.assert_called_once_with('hy2')
        account.assert_called_once_with('hysteria')

    def test_invalid_existing_binary_is_not_overwritten(self):
        with patch.object(runtime, 'BINARY', {'hy2': '/bin/sh'}), patch.object(runtime, 'capture', return_value='not hysteria'), patch.object(runtime, 'download_asset') as download:
            with self.assertRaises(RuntimeError):
                runtime.ensure_binary('hy2')
            download.assert_not_called()

    def test_download_requires_digest_and_expected_asset(self):
        with patch.object(runtime, 'capture', return_value=json.dumps({'assets': []})):
            with tempfile.TemporaryDirectory() as temp, self.assertRaises(RuntimeError):
                runtime.download_asset('hy2', Path(temp))

    def test_no_service_commands_in_preparation(self):
        calls = []
        def binary(mode):
            calls.append(mode)
        with patch.object(runtime, 'ensure_binary', side_effect=binary), patch.object(runtime, 'ensure_account'), patch('subprocess.run') as run:
            runtime.prepare_runtime('ws')
        self.assertEqual(calls, ['reality', 'ws'])
        run.assert_not_called()

    def test_hy2_uses_current_official_repository(self):
        self.assertEqual(runtime.REPO['hy2'], 'HyNetworks/hysteria')


if __name__ == '__main__': unittest.main()
