from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from desktop import start_mica


class StartMicaTests(unittest.TestCase):
    def test_existing_credentials_and_configuration_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'backend').mkdir()
            (root / 'desktop/config').mkdir(parents=True)
            env = root / 'backend/.env'
            env.write_text("MICA_DATA_DIR=C:/existing-data\nMICA_LAN_PASSWORD_HASH=existing-hash\nMICA_MODELS_DIR=C:/existing-models\nMICA_LAYA_ENABLED=1\n", encoding='utf-8')
            mapping = {'MICA_API_TOKEN': 'CUSTOM_API_TOKEN', 'MICA_APPROVAL_SECRET': 'CUSTOM_APPROVAL', 'GEMINI_API_KEY': 'CUSTOM_GEMINI'}
            (root / 'desktop/config/credential-names.json').write_text(json.dumps(mapping), encoding='utf-8')
            with patch.object(start_mica, 'ROOT', root), patch.object(start_mica, 'get_secret', return_value='existing-secret'), patch.object(start_mica, 'set_secret') as save:
                settings = start_mica.prepare_local_config()
            self.assertEqual(settings['MICA_DATA_DIR'], 'C:/existing-data')
            self.assertEqual(settings['MICA_MODELS_DIR'], 'C:/existing-models')
            self.assertEqual(settings['MICA_LAYA_ENABLED'], '1')
            self.assertEqual(json.loads((root / 'desktop/config/credential-names.json').read_text()), mapping)
            save.assert_called_once_with('MICA_API_TOKEN', 'existing-secret')
            self.assertNotIn('existing-secret', env.read_text())

    def test_failed_core_start_does_not_open_an_offline_ui(self):
        with patch.object(start_mica, 'start_core', side_effect=RuntimeError('Backend unavailable')), patch.object(start_mica.subprocess, 'run') as run:
            self.assertEqual(start_mica.main(console=True), 1)
            run.assert_not_called()

    def test_healthy_docker_is_reused(self):
        with patch.object(start_mica.shutil, 'which', return_value='docker'), patch.object(start_mica, 'docker_ready', return_value=True), patch.object(start_mica.subprocess, 'Popen') as spawn:
            start_mica.ensure_docker()
            spawn.assert_not_called()

    def test_closing_startup_does_not_launch_desktop(self):
        with patch('desktop.startup_window.run_startup', return_value=False), patch.object(start_mica.subprocess, 'run') as run:
            self.assertEqual(start_mica.main(), 1)
            run.assert_not_called()

    def test_successful_startup_uses_existing_desktop_entrypoint(self):
        with patch('desktop.startup_window.run_startup', return_value=True), patch.object(start_mica.subprocess, 'run') as run:
            run.return_value.returncode = 0
            self.assertEqual(start_mica.main(), 0)
            run.assert_called_once_with(
                [start_mica.sys.executable, str(start_mica.ROOT / 'desktop/local_main.py')],
                cwd=start_mica.ROOT / 'desktop',
            )


if __name__ == '__main__':
    unittest.main()
