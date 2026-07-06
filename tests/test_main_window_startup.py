import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from app.gui import main_window


class MainWindowStartupTest(unittest.TestCase):
    def test_configure_qt_application_enables_high_dpi_attributes(self):
        with patch('app.gui.main_window.QCoreApplication.setAttribute') as set_attribute_mock:
            main_window.configure_qt_application()

        set_attribute_mock.assert_any_call(Qt.AA_EnableHighDpiScaling, True)
        set_attribute_mock.assert_any_call(Qt.AA_UseHighDpiPixmaps, True)

    def test_configure_application_font_replaces_suspicious_small_default_font(self):
        class _AppStub:
            def __init__(self):
                self._font = QFont('SimSun', 6)
                self.applied_font = None

            def font(self):
                return self._font

            def setFont(self, font):
                self.applied_font = QFont(font)

        app = _AppStub()
        replacement_font = QFont('Tahoma', 9)

        with patch('app.gui.main_window._resolve_windows_message_font', return_value=replacement_font):
            main_window.configure_application_font(app)

        self.assertIsNotNone(app.applied_font)
        self.assertEqual(app.applied_font.family(), 'Tahoma')
        self.assertEqual(app.applied_font.pointSize(), 9)

    def test_configure_application_font_keeps_normal_default_font(self):
        class _AppStub:
            def __init__(self):
                self._font = QFont('Microsoft YaHei UI', 9)
                self.applied_font = None

            def font(self):
                return self._font

            def setFont(self, font):
                self.applied_font = QFont(font)

        app = _AppStub()

        with patch('app.gui.main_window._resolve_windows_message_font', return_value=QFont('Tahoma', 9)):
            main_window.configure_application_font(app)

        self.assertIsNone(app.applied_font)

    def test_run_snapshot_refresh_cycle_refreshes_libraries_in_order(self):
        calls = []

        refresh_client = SimpleNamespace(
            list_actors_snapshot=lambda **kwargs: calls.append(('actor', kwargs)),
            list_code_prefixes_snapshot=lambda **kwargs: calls.append(('code_prefix', kwargs)),
            get_data_center_summary=lambda **kwargs: calls.append(('data_center', kwargs)),
        )
        stub = SimpleNamespace(snapshot_refresh_running=False)

        main_window.VidNormApp._run_snapshot_refresh_cycle(stub, refresh_client=refresh_client)

        self.assertFalse(stub.snapshot_refresh_running)
        self.assertEqual(
            [item[0] for item in calls],
            ['actor', 'code_prefix', 'data_center'],
        )
        for _name, kwargs in calls:
            self.assertTrue(kwargs.get('force_refresh'))

    def test_schedule_snapshot_refresh_cycle_starts_runner_when_idle(self):
        started = []
        stub = SimpleNamespace(
            snapshot_refresh_running=False,
            snapshot_refresh_task_runner=None,
            snapshot_refresh_worker=None,
            backend_client=SimpleNamespace(),
            _create_snapshot_refresh_worker=lambda: object(),
            _on_snapshot_refresh_finished=lambda _result=None: None,
            _on_snapshot_refresh_failed=lambda _error=None: None,
        )

        class _Runner:
            def __init__(self, worker, success_handler, error_handler):
                started.append(('init', worker, success_handler, error_handler))

            def start(self):
                started.append('start')

        with patch('app.gui.main_window.GuiTaskRunner', _Runner):
            main_window.VidNormApp.schedule_snapshot_refresh_cycle(stub)

        self.assertTrue(stub.snapshot_refresh_running)
        self.assertEqual(started[-1], 'start')


if __name__ == '__main__':
    unittest.main()
