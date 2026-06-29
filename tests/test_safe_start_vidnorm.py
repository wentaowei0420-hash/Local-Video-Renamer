import tempfile
import unittest
from pathlib import Path

from app.core.backend_protocol import BACKEND_API_REVISION, BACKEND_PROCESS_CODE_FINGERPRINT
from app.core.project_paths import PROJECT_ROOT
from safe_start_vidnorm import (
    BACKEND_INSTANCE_TOKEN_ENV,
    BACKEND_OWNED_ENV,
    build_gui_environment,
    choose_gui_interpreter,
    format_backend_failure,
    is_expected_backend,
    is_project_backend,
)


class SafeStartVidnormTest(unittest.TestCase):
    def test_is_project_backend_accepts_same_project_health(self):
        health = {
            'backend_revision': BACKEND_API_REVISION,
            'backend_code_fingerprint': BACKEND_PROCESS_CODE_FINGERPRINT,
            'project_root': str(PROJECT_ROOT),
            'backend_instance_token': 'token-1',
        }

        self.assertTrue(is_project_backend(health))

    def test_is_expected_backend_requires_matching_token(self):
        health = {
            'backend_revision': BACKEND_API_REVISION,
            'backend_code_fingerprint': BACKEND_PROCESS_CODE_FINGERPRINT,
            'project_root': str(PROJECT_ROOT),
            'backend_instance_token': 'token-1',
        }

        self.assertTrue(is_expected_backend(health, 'token-1'))
        self.assertFalse(is_expected_backend(health, 'token-2'))

    def test_build_gui_environment_marks_owned_backend(self):
        base_env = {'EXAMPLE': '1'}

        gui_env = build_gui_environment(base_env, 'abc123', owns_backend=True)

        self.assertEqual(gui_env['EXAMPLE'], '1')
        self.assertEqual(gui_env[BACKEND_INSTANCE_TOKEN_ENV], 'abc123')
        self.assertEqual(gui_env[BACKEND_OWNED_ENV], '1')

    def test_choose_gui_interpreter_prefers_pythonw_sibling(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scripts_dir = Path(temp_dir)
            python_exe = scripts_dir / 'python.exe'
            pythonw_exe = scripts_dir / 'pythonw.exe'
            python_exe.write_text('', encoding='utf-8')
            pythonw_exe.write_text('', encoding='utf-8')

            resolved = choose_gui_interpreter(str(python_exe))

            self.assertEqual(resolved, str(pythonw_exe))

    def test_choose_gui_interpreter_falls_back_to_console_python(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scripts_dir = Path(temp_dir)
            python_exe = scripts_dir / 'python.exe'
            python_exe.write_text('', encoding='utf-8')

            resolved = choose_gui_interpreter(str(python_exe))

            self.assertEqual(resolved, str(python_exe))

    def test_format_backend_failure_prefers_initializing_message(self):
        message = format_backend_failure(process_alive=True, stale_backend_cleaned=False)

        self.assertIn('后端仍在初始化', message)


if __name__ == '__main__':
    unittest.main()
