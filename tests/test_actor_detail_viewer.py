import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication, QWidget

from app.gui.actor_detail_viewer import ActorDetailViewerWindow


_APP = QApplication.instance() or QApplication([])


class _ParentThatFailsRefresh(QWidget):
    def load_data(self):
        raise RuntimeError('refresh exploded')

    def neighbor_detail_key(self, *_args):
        return ''


class _BackendStub:
    def get_actor_detail(self, actor_name):
        return {
            'name': actor_name,
            'birthday': '2000-01-01',
            'age': '26',
            'matched': True,
            'actor_id': 'avfan-1',
            'binghuo_person_id': 'binghuo-1',
            'binghuo_height': '170',
            'binghuo_bust': '88',
            'binghuo_cup': 'F',
            'binghuo_waist': '60',
            'binghuo_hip': '90',
            'appearance_code_count': 3,
            'code_prefix_library_count': 2,
            'web_url': '',
            'ladder_tier': 'A',
            'update_status': 'inactive',
            'local_video_count': 0,
            'local_prefix_distribution': [],
            'local_year_distribution': [],
            'web_enrichment_status': '并火: 已补全',
            'web_total_pages': 0,
            'web_total_videos': 0,
            'eligible_video_count': 0,
            'eligible_enriched_video_count': 0,
            'web_last_enriched_at': '',
            'web_earliest_release_date': '',
            'web_latest_release_date': '',
            'web_prefix_distribution': [],
            'web_year_distribution': [],
            'web_video_category_distribution': [],
            'local_videos': [],
            'web_movies': [],
        }

    def admit_ladder_entry(self, *_args):
        return {}


class ActorDetailViewerWindowTest(unittest.TestCase):
    def test_load_data_formats_binghuo_fields_and_code_counts(self):
        parent = QWidget()
        window = ActorDetailViewerWindow(_BackendStub(), 'Actor A', parent)
        try:
            self.assertEqual(window.basic_grid.value_labels['actor_id'].text(), 'avfan-1')
            self.assertEqual(window.basic_grid.value_labels['binghuo_person_id'].text(), 'binghuo-1')
            self.assertEqual(window.basic_grid.value_labels['binghuo_height'].text(), '170 cm')
            self.assertEqual(window.basic_grid.value_labels['appearance_code_count'].text(), '3')
            self.assertEqual(window.basic_grid.value_labels['code_prefix_library_count'].text(), '2')
            self.assertEqual(window.basic_measurements_grid.value_labels['cup'].text(), 'F')
            self.assertEqual(
                window.basic_measurements_grid.value_labels['measurements'].text(),
                '胸围：88 cm 腰围：60 cm 臀围：90 cm',
            )
        finally:
            window.hide()
            window.deleteLater()
            parent.deleteLater()

    def test_update_ladder_tier_does_not_raise_when_parent_refresh_fails(self):
        parent = _ParentThatFailsRefresh()
        window = ActorDetailViewerWindow(_BackendStub(), 'Actor A', parent)
        try:
            with patch('PyQt5.QtWidgets.QMessageBox.warning') as warning_mock, patch(
                'PyQt5.QtWidgets.QMessageBox.information'
            ):
                window.update_ladder_tier()

            self.assertTrue(warning_mock.called)
            self.assertEqual(window.detail['ladder_tier'], 'A')
        finally:
            window.hide()
            window.deleteLater()
            parent.deleteLater()


if __name__ == '__main__':
    unittest.main()
