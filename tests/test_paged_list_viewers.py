import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from app.gui.actor_viewer import ActorViewerWindow
from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.code_prefix_viewer import CodePrefixViewerWindow
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


class CodePrefixListBackendStub:
    def __init__(self):
        self.calls = []
        self.snapshot_calls = []

    def list_code_prefixes_page(self, search_text='', sort_field='prefix', sort_order='asc', limit=200, offset=0):
        self.calls.append((search_text, sort_field, sort_order, limit, offset))
        return {
            'prefixes': [
                {
                    'prefix': f'PFX-{offset}',
                    'video_count': 1,
                    'enrichment_status': '',
                    'avfan_total_videos': 0,
                    'earliest_release_date': '',
                    'latest_release_date': '',
                }
            ],
            'total_count': 500,
            'limit': limit,
            'offset': offset,
        }

    def list_code_prefixes_snapshot(
        self,
        search_text='',
        sort_field='prefix',
        sort_order='asc',
        limit=200,
        offset=0,
        force_refresh=False,
    ):
        self.snapshot_calls.append((search_text, sort_field, sort_order, limit, offset, bool(force_refresh)))
        return {
            'prefixes': [
                {
                    'prefix': f'PFX-{offset}',
                    'video_count': 1,
                    'enrichment_status': '',
                    'avfan_total_videos': 0,
                    'earliest_release_date': '',
                    'latest_release_date': '',
                }
            ],
            'total_count': 500,
            'limit': limit,
            'offset': offset,
            'refreshed_at': '2026-07-06 14:00:00' if force_refresh else '2026-07-06 13:59:00',
            'cache_hit': not force_refresh,
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

    def test_code_prefix_viewer_loads_page_and_advances_to_next_page(self):
        backend = CodePrefixListBackendStub()
        with (
            patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task),
            patch(
                'app.gui.code_prefix_viewer.load_code_prefix_library_settings',
                return_value={'sort_field': 'prefix', 'sort_order': 'asc'},
            ),
            patch('app.gui.code_prefix_viewer.save_code_prefix_library_settings'),
        ):
            window = CodePrefixViewerWindow(backend)
            try:
                self.assertEqual(backend.snapshot_calls[0], ('', 'prefix', 'asc', window.page_size, 0, False))
                window.go_to_next_page()
                self.assertEqual(
                    backend.snapshot_calls[-1],
                    ('', 'prefix', 'asc', window.page_size, window.page_size, False),
                )
            finally:
                window.hide()
                window.deleteLater()


if __name__ == '__main__':
    unittest.main()
