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
        self.assertIsNone(self.window.inspector)
        self.assertFalse(any(b.selected or b.input_held or b.flash for b in self.window.map.buttons.values()))
        self.window.edit_binding('right_lower')

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

    def test_selection_defers_unused_controls_and_retains_later_edits(self):
        from altclipctrl.ui import DialControlsEditor
        window = self.window
        self.assertEqual(window.inspector.findChildren(DialControlsEditor), [])
        same_editor = window.inspector
        window.inspector.name.setText('Draft name')
        window.edit_binding('right_lower')
        self.assertIs(window.inspector, same_editor)
        self.assertEqual(window.inspector.name.text(), 'Draft name')
        editor = window.inspector.editors['hold'].split['with_dial']
        editor.kind.setCurrentIndex(editor.kind.findData('dial_modifier'))
        controls = editor.dial_controls
        output = controls.editors['cw']
        output.kind.setCurrentIndex(output.kind.findData('shortcut'))
        output.key.combo.setCurrentText('F24')
        editor.kind.setCurrentIndex(editor.kind.findData('none'))
        editor.kind.setCurrentIndex(editor.kind.findData('dial_modifier'))
        self.assertIs(editor.dial_controls, controls)
        self.assertEqual(editor.read()['value']['cw'], action('shortcut', 'F24'))
        self.assertTrue(window.save_inspector())
        self.assertEqual(load(window.path)['profiles'][0]['bindings']['right_lower']['hold']['value']['cw'], action('shortcut', 'F24'))

    def test_physical_press_is_grey_and_release_restores_selection(self):
        from altclipctrl.ui import THEME
        window = self.window
        for theme in ('dark', 'light'):
            window.apply_theme(theme, remember=False)
            accent, pressed = THEME['accent'], THEME['pressed']
            for slot in ('right_lower', 'top_left'):
                window.edit_binding(slot)
                widget = window.map.buttons[slot]
                def fill():
                    image = widget.grab().toImage()
                    return image.pixelColor(image.width() // 2, image.height() // 2).name()
                self.assertEqual(fill(), accent)
                window.map.set_held(widget.signal, True)
                self.assertEqual(fill(), pressed)
                window.map.set_held(widget.signal, False)
                window.map.unpulse(widget)
                self.assertEqual(fill(), accent)
                self.assertTrue(widget.selected)
            other = window.map.buttons['left_lower']
            window.map.set_held(other.signal, True)
            image = other.grab().toImage()
            self.assertEqual(image.pixelColor(image.width() // 2, image.height() // 2).name(), pressed)
            self.assertFalse(other.selected)
            window.map.set_held(other.signal, False)
            window.map.unpulse(other)
        window.apply_theme('dark', remember=False)

    def test_inspector_fits_without_scrolling(self):
        """Every gesture page, including nested dial modifiers, fits the window's minimum height."""
        from PySide6.QtWidgets import QScrollArea, QTabWidget
        window = self.window
        window.resize(window.minimumSize())
        window.show()
        self.app.processEvents()
        self.assertEqual(window.findChildren(QScrollArea), [])
        editor = window.inspector
        for gesture in ('hold', 'tap_hold'):
            split = editor.editors[gesture].split['with_dial']
            split.kind.setCurrentIndex(split.kind.findData('dial_modifier'))
            for slot in ('cw', 'neutral'):
                split.dial_controls.select(slot)
                output = split.dial_controls.editors[slot]
                output.kind.setCurrentIndex(output.kind.findData('cycle_next'))
        tabs = editor.findChild(QTabWidget)
        for index in range(tabs.count()):
            tabs.setCurrentIndex(index)
            self.app.processEvents()
            needed = editor.minimumSizeHint().height()
            self.assertLessEqual(needed, window.inspector_area.height(), f'tab {index} needs {needed}px')
        window.hide()

    def test_theme_choice_is_remembered_per_settings_file(self):
        window = self.window
        window.toggle_theme()
        self.assertTrue(window.preferences_path.exists())
        again = MainWindow(window.path, diagnostic=True)
        try:
            from altclipctrl.ui import THEME
            self.assertEqual(THEME['name'], 'light')
        finally:
            again.close()
            window.apply_theme('dark')
