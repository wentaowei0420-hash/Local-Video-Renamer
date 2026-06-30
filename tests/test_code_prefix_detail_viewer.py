import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication, QWidget

from app.gui.code_prefix_detail_viewer import CodePrefixDetailViewerWindow


_APP = QApplication.instance() or QApplication([])


class _BackendStub:
    def get_code_prefix_detail(self, prefix):
        return {
            'prefix': prefix,
            'ladder_tier': 'S',
            'update_status': 'active',
            'video_count': 12,
            'avfan_total_pages': 3,
            'avfan_total_videos': 24,
            'eligible_video_count': 6,
            'eligible_enriched_video_count': 5,
            'earliest_release_date': '2024-01-01',
            'latest_release_date': '2024-02-03',
            'last_enriched_at': '',
            'update_frequency': {
                'video_count': 6,
                'month_count': 2,
                'videos_per_month': 3.0,
            },
            'year_distribution': [],
            'top_actors': [],
            'video_category_distribution': [],
            'uncategorized_eligible_video_count': 0,
            'local_videos': [],
            'movies': [],
            'web_url': '',
        }

    def admit_ladder_entry(self, *_args):
        return {}


class CodePrefixDetailViewerWindowTest(unittest.TestCase):
    def test_load_data_shows_update_frequency(self):
        parent = QWidget()
        window = CodePrefixDetailViewerWindow(_BackendStub(), 'ROE', parent)
        try:
            self.assertEqual(window.summary_grid.value_labels['prefix'].text(), 'ROE')
            self.assertEqual(window.last_enriched_grid.value_labels['update_frequency'].text(), '3.00 部/月')
        finally:
            window.hide()
            window.deleteLater()
            parent.deleteLater()


if __name__ == '__main__':
    unittest.main()
