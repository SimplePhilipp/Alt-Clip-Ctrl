"""Inline edits preserve drafts and merge safely into current settings."""
import copy
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from PySide6.QtWidgets import QApplication, QMessageBox
from unittest.mock import patch
from altclipctrl.model import action, load, new_profile
from altclipctrl.ui import MainWindow

class WorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        root = Path(__file__).resolve().parents[1] / 'test-results'
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.window = MainWindow(Path(self.temp.name) / 'settings.json', diagnostic=True)

    def tearDown(self):
        self.window.close_inspector()
        self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def test_save_merges_control_with_latest_unrelated_settings(self):
        window = self.window
        editor = window.inspector
        editor.name.setText('Pan and scroll')
        held = editor.editors['hold']
        held.split['without_dial'].kind.setCurrentIndex(held.split['without_dial'].kind.findData('hold_key'))
        held.split['without_dial'].key.combo.setCurrentText('Space')
        held.split['with_dial'].kind.setCurrentIndex(held.split['with_dial'].kind.findData('dial_scroll'))
        result = copy.deepcopy(window.config)
        result['scroll_acceleration'] = True
        window.persist(result)
        self.assertTrue(window.save_inspector())
        saved = load(window.path)
        self.assertTrue(saved['scroll_acceleration'])
        binding = saved['profiles'][0]['bindings']['right_lower']
        self.assertEqual(binding['name'], 'Pan and scroll')
        self.assertEqual(binding['hold']['kind'], 'hold_dial')
        self.assertFalse(window.inspector_is_dirty())

    def test_cancel_leaves_configuration_untouched(self):
        window = self.window
        original = copy.deepcopy(window.config)
        window.inspector.name.setText('Discard this')
        window.close_inspector()
        self.assertEqual(window.config, original)
        self.assertIsNone(window.inspector)

    def test_cancel_switch_preserves_draft_and_discard_opens_new_control(self):
        window = self.window
        window.inspector.name.setText('Draft')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Cancel):
            window.edit_binding('top_left')
        self.assertEqual(window.inspector.slot, 'right_lower')
        self.assertEqual(window.inspector.name.text(), 'Draft')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Discard):
            window.edit_binding('top_left')
        self.assertEqual(window.inspector.slot, 'top_left')
        self.assertEqual(window.config['profiles'][0]['bindings']['right_lower']['name'], 'Right lower')

    def test_conflicting_control_is_not_overwritten(self):
        window = self.window
        window.inspector.name.setText('Old draft')
        result = copy.deepcopy(window.config)
        result['profiles'][0]['bindings']['right_lower']['name'] = 'Newer change'
        window.persist(result)
        with patch('altclipctrl.ui.error') as show_error:
            self.assertFalse(window.save_inspector())
        show_error.assert_called_once()
        self.assertEqual(window.config['profiles'][0]['bindings']['right_lower']['name'], 'Newer change')
