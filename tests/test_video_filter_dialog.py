import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication, QDialogButtonBox, QMessageBox

from app.gui.video_filter_dialog import VideoFilterDialog


_APP = QApplication.instance() or QApplication([])


class VideoFilterDialogLayoutTest(unittest.TestCase):
    def test_keyword_editors_are_arranged_in_one_row_with_equal_width(self):
        with patch('app.gui.video_filter_dialog.load_video_filter_settings', return_value={'rules': {}}):
            dialog = VideoFilterDialog()
        try:
            self.assertIs(dialog.editor_grid.itemAtPosition(0, 0).widget(), dialog.code_editor)
            self.assertIs(dialog.editor_grid.itemAtPosition(0, 1).widget(), dialog.title_editor)
            self.assertIs(dialog.editor_grid.itemAtPosition(0, 2).widget(), dialog.tags_editor)
            self.assertIs(dialog.editor_grid.itemAtPosition(0, 3).widget(), dialog.co_star_code_editor)
            self.assertEqual(dialog.editor_grid.columnStretch(0), 1)
            self.assertEqual(dialog.editor_grid.columnStretch(1), 1)
            self.assertEqual(dialog.editor_grid.columnStretch(2), 1)
            self.assertEqual(dialog.editor_grid.columnStretch(3), 1)

            dialog.show()
            _APP.processEvents()

            widths = [
                dialog.code_editor.width(),
                dialog.title_editor.width(),
                dialog.tags_editor.width(),
                dialog.co_star_code_editor.width(),
            ]
            self.assertLessEqual(max(widths) - min(widths), 4)

            self.assertTrue(dialog.code_editor.hint_label.wordWrap())
            self.assertTrue(dialog.title_editor.hint_label.wordWrap())
            self.assertTrue(dialog.tags_editor.hint_label.wordWrap())
            self.assertTrue(dialog.co_star_code_editor.hint_label.wordWrap())
        finally:
            dialog.hide()
            dialog.deleteLater()

    def test_save_keeps_dialog_open_and_clears_unsaved_changes(self):
        with patch('app.gui.video_filter_dialog.load_video_filter_settings', return_value={'rules': {}}):
            dialog = VideoFilterDialog()
        try:
            dialog.show()
            _APP.processEvents()

            dialog.code_editor.keyword_input.setText('ABCD')
            dialog.code_editor.add_keyword()
            self.assertTrue(dialog.has_unsaved_changes())

            button_box = dialog.findChild(QDialogButtonBox)
            save_button = button_box.button(QDialogButtonBox.Save)
            with patch('app.gui.video_filter_dialog.save_video_filter_settings') as save_settings, \
                    patch('app.gui.video_filter_dialog.QMessageBox.information'):
                save_button.click()
                _APP.processEvents()

                save_settings.assert_called_once()
            self.assertTrue(dialog.isVisible())
            self.assertFalse(dialog.has_unsaved_changes())
        finally:
            dialog.hide()
            dialog.deleteLater()

    def test_close_prompts_when_unsaved_changes_exist(self):
        with patch('app.gui.video_filter_dialog.load_video_filter_settings', return_value={'rules': {}}):
            dialog = VideoFilterDialog()
        try:
            dialog.show()
            _APP.processEvents()

            dialog.code_editor.keyword_input.setText('ABCD')
            dialog.code_editor.add_keyword()

            with patch('app.gui.video_filter_dialog.QMessageBox.question', return_value=QMessageBox.No) as question:
                dialog.close()
                _APP.processEvents()

            question.assert_called_once()
            self.assertTrue(dialog.isVisible())
        finally:
            dialog.hide()
            dialog.deleteLater()

    def test_close_without_unsaved_changes_hides_dialog(self):
        with patch('app.gui.video_filter_dialog.load_video_filter_settings', return_value={'rules': {}}):
            dialog = VideoFilterDialog()
        try:
            dialog.show()
            _APP.processEvents()

            dialog.close()
            _APP.processEvents()

            self.assertFalse(dialog.isVisible())
        finally:
            dialog.hide()
            dialog.deleteLater()

    def test_close_after_confirming_unsaved_changes_hides_dialog(self):
        with patch('app.gui.video_filter_dialog.load_video_filter_settings', return_value={'rules': {}}):
            dialog = VideoFilterDialog()
        try:
            dialog.show()
            _APP.processEvents()

            dialog.code_editor.keyword_input.setText('ABCD')
            dialog.code_editor.add_keyword()

            with patch('app.gui.video_filter_dialog.QMessageBox.question', return_value=QMessageBox.Yes) as question:
                dialog.close()
                _APP.processEvents()

            question.assert_called_once()
            self.assertFalse(dialog.isVisible())
        finally:
            dialog.hide()
            dialog.deleteLater()


if __name__ == '__main__':
    unittest.main()
