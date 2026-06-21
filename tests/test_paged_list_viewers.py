import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from app.gui.actor_viewer import ActorViewerWindow
from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.db_viewer import DatabaseViewerWindow


_APP = QApplication.instance() or QApplication([])


def _run_sync_async_task(self, task, success_handler, error_title=None):
    success_handler(task())
    return True


class VideoListBackendStub:
    def __init__(self):
        self.calls = []

    def list_videos_page(self, search_text='', sort_field='code', sort_order='asc', limit=200, offset=0):
        self.calls.append((search_text, sort_field, sort_order, limit, offset))
        return {
            'videos': [{'code': 'AAA-001', 'title': 'A', 'author': 'Actor A'}],
            'total_count': 500,
            'limit': limit,
            'offset': offset,
        }


class ActorListBackendStub:
    def __init__(self):
        self.calls = []

    def list_actors_page(self, search_text='', sort_field='name', sort_order='asc', limit=200, offset=0):
        self.calls.append((search_text, sort_field, sort_order, limit, offset))
        return {
            'actors': [
                {
                    'name': f'Actor-{offset}',
                    'birthday': '',
                    'age': '',
                    'enrichment_status': '',
                }
            ],
            'total_count': 500,
            'limit': limit,
            'offset': offset,
        }


class PagedListViewerTest(unittest.TestCase):
    def test_database_viewer_loads_page_and_advances_to_next_page(self):
        backend = VideoListBackendStub()
        with (
            patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task),
            patch('app.gui.db_viewer.load_video_library_settings', return_value={'sort_field': 'code', 'sort_order': 'asc'}),
            patch('app.gui.db_viewer.save_video_library_settings'),
        ):
            window = DatabaseViewerWindow(backend)
            try:
                self.assertEqual(backend.calls[0], ('', 'code', 'asc', window.page_size, 0))
                window.go_to_next_page()
                self.assertEqual(backend.calls[1], ('', 'code', 'asc', window.page_size, window.page_size))
            finally:
                window.hide()
                window.deleteLater()

    def test_actor_viewer_loads_page_and_advances_to_next_page(self):
        backend = ActorListBackendStub()
        with (
            patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task),
            patch('app.gui.actor_viewer.load_actor_library_settings', return_value={'sort_field': 'name', 'sort_order': 'asc'}),
            patch('app.gui.actor_viewer.save_actor_library_settings'),
        ):
            window = ActorViewerWindow(backend)
            try:
                self.assertEqual(backend.calls[0], ('', 'name', 'asc', window.page_size, 0))
                window.go_to_next_page()
                self.assertEqual(backend.calls[1], ('', 'name', 'asc', window.page_size, window.page_size))
            finally:
                window.hide()
                window.deleteLater()


if __name__ == '__main__':
    unittest.main()
