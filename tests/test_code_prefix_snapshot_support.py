import tempfile
import unittest
from pathlib import Path

from app.backend.client import BackendClient
from app.backend.service import BackendService


class _FilterServiceStub:
    def __init__(self, settings=None):
        self._settings = dict(settings or {})

    def load_settings(self):
        return dict(self._settings)


class BackendServiceCodePrefixSnapshotTest(unittest.TestCase):
    def _build_service(self, snapshot_file, filter_settings=None):
        service = BackendService.__new__(BackendService)
        service.ensure_database_loaded = lambda: None
        service.video_filter_service = _FilterServiceStub(filter_settings)
        service._snapshot_lock = None
        service._code_prefix_snapshot_file_lock = None
        service._code_prefix_library_snapshots = {}
        service._code_prefix_detail_snapshots = {}
        service._code_prefix_snapshot_file = Path(snapshot_file)
        service._code_prefix_snapshot_filter_fingerprint = BackendService._build_code_prefix_snapshot_filter_fingerprint(
            filter_settings
        )
        return service

    def test_list_snapshot_persists_across_service_restarts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_file = Path(temp_dir) / 'code_prefix_snapshot.json'
            first_service = self._build_service(snapshot_file)
            timestamps = iter(['2026-07-06 13:00:00'])
            first_service._current_snapshot_timestamp = lambda: next(timestamps)
            first_service.list_code_prefixes = lambda *args, **kwargs: {
                'prefixes': [{'prefix': 'ADN', 'video_count': 8}],
                'total_count': 1,
                'offset': 0,
                'limit': 200,
            }

            first = BackendService.list_code_prefixes_snapshot(first_service)

            self.assertFalse(first['cache_hit'])
            self.assertEqual(first['refreshed_at'], '2026-07-06 13:00:00')

            second_service = self._build_service(snapshot_file)
            second_service.list_code_prefixes = lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError('should reuse persisted list snapshot')
            )
            BackendService._load_code_prefix_snapshots(second_service)

            second = BackendService.list_code_prefixes_snapshot(second_service)

            self.assertTrue(second['cache_hit'])
            self.assertEqual(second['refreshed_at'], '2026-07-06 13:00:00')
            self.assertEqual(second['prefixes'][0]['prefix'], 'ADN')

    def test_detail_snapshot_persists_across_service_restarts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_file = Path(temp_dir) / 'code_prefix_snapshot.json'
            first_service = self._build_service(snapshot_file)
            timestamps = iter(['2026-07-06 13:05:00'])
            first_service._current_snapshot_timestamp = lambda: next(timestamps)
            first_service.get_code_prefix_detail = lambda prefix: {
                'prefix_detail': {
                    'prefix': prefix,
                    'video_count': 12,
                    'avfan_total_videos': 18,
                }
            }

            first = BackendService.get_code_prefix_detail_snapshot(first_service, 'ADN')

            self.assertFalse(first['cache_hit'])
            self.assertEqual(first['refreshed_at'], '2026-07-06 13:05:00')

            second_service = self._build_service(snapshot_file)
            second_service.get_code_prefix_detail = lambda prefix: (_ for _ in ()).throw(
                AssertionError('should reuse persisted detail snapshot')
            )
            BackendService._load_code_prefix_snapshots(second_service)

            second = BackendService.get_code_prefix_detail_snapshot(second_service, 'ADN')

            self.assertTrue(second['cache_hit'])
            self.assertEqual(second['refreshed_at'], '2026-07-06 13:05:00')
            self.assertEqual(second['prefix_detail']['prefix'], 'ADN')


class BackendClientCodePrefixSnapshotTest(unittest.TestCase):
    def test_list_code_prefixes_snapshot_passes_refresh_query(self):
        client = BackendClient(base_url='http://127.0.0.1:8766', timeout=30)
        calls = []

        def fake_get(path, timeout=None):
            calls.append((path, timeout))
            return {'prefixes': [], 'refreshed_at': '2026-07-06 13:10:00'}

        client._get = fake_get

        result = client.list_code_prefixes_snapshot(
            search_text='AD',
            sort_field='prefix',
            sort_order='desc',
            limit=50,
            offset=100,
            force_refresh=True,
        )

        self.assertEqual(result['refreshed_at'], '2026-07-06 13:10:00')
        self.assertEqual(
            calls,
            [('/database/code-prefixes?q=AD&sort_field=prefix&sort_order=desc&limit=50&offset=100&refresh=1', 120)],
        )

    def test_get_code_prefix_detail_snapshot_passes_refresh_query(self):
        client = BackendClient(base_url='http://127.0.0.1:8766', timeout=30)
        calls = []

        def fake_get(path, timeout=None):
            calls.append((path, timeout))
            return {'prefix_detail': {'prefix': 'ADN'}, 'refreshed_at': '2026-07-06 13:15:00'}

        client._get = fake_get

        result = client.get_code_prefix_detail_snapshot('ADN', force_refresh=True)

        self.assertEqual(result['prefix_detail']['prefix'], 'ADN')
        self.assertEqual(
            calls,
            [('/database/code-prefixes/detail?prefix=ADN&refresh=1', 120)],
        )


if __name__ == '__main__':
    unittest.main()
