"""Holding alone and turning share a gesture, with balanced held output."""
import copy
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import tempfile
import unittest

from PySide6.QtWidgets import QApplication, QDialog
from altclipctrl.engine import Engine
from altclipctrl.model import action, defaults, dial_map, load, new_profile, references_cycle, references_profile, save, validate
from altclipctrl.ui import BindingDialog
from tests.test_altclipctrl import FakeBackend, TEMP_ROOT


def combined(plain=None, dial=None):
    return action("hold_dial", {"without_dial": plain or action("hold_key", "Space"),
                               "with_dial": dial or action("dial_scroll", {"reverse": False})})


class HoldAndDialTests(unittest.TestCase):
    def setUp(self):
        self.settings = defaults()
        self.backend = FakeBackend()
        self.history = []
        self.engine = Engine(self.settings, self.backend, activity=self.history.append)
        self.bindings = self.engine.profile["bindings"]
        self.bindings["top_left"]["tap"] = action("shortcut", "B")
        self.bindings["top_left"]["hold"] = combined()
        self.bindings["top_left"]["tap_hold"] = combined()
        self.bindings["cw"]["tap"] = action("shortcut", "F")

    def pulse(self, key, now):
        self.engine.event(key, True, now)
        self.engine.event(key, False, now + .001)

    def start(self, second=False):
        if second:
            self.pulse("F13", 1)
            self.engine.event("F13", True, 1.05)
        else:
            self.engine.event("F13", True, 1)
            self.engine.poll(1.301)

    def test_hold_alone_pans_and_releases_without_scrolling(self):
        self.start()
        self.assertEqual(self.backend.events, [("down", "Space")])
        self.assertIsNone(self.engine.dial_layer)
        self.engine.event("F13", False, 2)
        self.engine.poll(3)
        self.assertEqual(self.backend.events, [("down", "Space"), ("up", "Space")])

    def test_first_turn_releases_pan_before_scroll_for_both_gestures(self):
        for second in (False, True):
            with self.subTest(second=second):
                self.setUp()
                self.start(second)
                self.pulse("F23", 2)
                self.assertEqual(self.backend.events, [("down", "Space"), ("up", "Space"), ("scroll", 1)])
                self.assertFalse(self.engine.held_counts)
                self.engine.poll(3)
                self.pulse("F21", 4)
                self.engine.event("F13", False, 5)
                self.engine.poll(6)
                self.assertEqual(self.backend.events[-1], ("scroll", -1))
                self.assertEqual(self.backend.events.count(("down", "Space")), 1)
                self.assertIsNone(self.engine.dial_layer)
                self.pulse("F23", 7)
                self.assertEqual(self.backend.events[-2:], [("down", "F"), ("up", "F")])

    def test_early_turn_starts_dial_without_pan_flash_or_tap(self):
        self.engine.event("F13", True, 1)
        self.pulse("F23", 1.01)
        self.engine.event("F13", False, 1.02)
        self.engine.poll(2)
        self.assertEqual(self.backend.events, [("scroll", 1)])

    def test_short_tap_still_sends_its_tap_action(self):
        self.pulse("F13", 1)
        self.engine.poll(1.2)
        self.assertEqual(self.backend.events, [("down", "B"), ("up", "B")])

    def test_late_release_without_poll_balances_plain_action(self):
        self.engine.event("F13", True, 1)
        self.engine.event("F13", False, 2)
        self.assertEqual(self.backend.events, [("down", "Space"), ("up", "Space")])
        self.assertFalse(self.engine.held_counts)
        self.assertIsNone(self.engine.states["top_left"].dial_pending)

    def test_neutral_press_does_not_switch_pan_and_pressed_turn_does(self):
        self.start()
        self.pulse("F22", 2)
        self.assertEqual(self.backend.events, [("down", "Space")])
        self.pulse("F24", 3)
        self.assertEqual(self.backend.events[-2:], [("up", "Space"), ("scroll", 1)])

    def test_plain_none_and_dial_none_work_independently(self):
        self.bindings["top_left"]["hold"] = combined(action(), action())
        self.start()
        self.pulse("F23", 2)
        self.assertEqual(self.backend.events, [])
        self.engine.event("F13", False, 3)
        self.pulse("F23", 4)
        self.assertEqual(self.backend.events, [("down", "F"), ("up", "F")])

    def test_cycles_and_five_custom_controls_work_after_transition(self):
        for mode in (action("dial_cycle", {"reverse": True, "cycle_id": "default"}),
                     action("dial_modifier", {**dial_map(), "cw": action("shortcut", "Ctrl+F1")})):
            with self.subTest(mode=mode["kind"]):
                self.setUp()
                self.bindings["top_left"]["hold"] = combined(dial=mode)
                self.start()
                self.pulse("F23", 2)
                expected = [("down", "E"), ("up", "E")] if mode["kind"] == "dial_cycle" else [
                    ("down", "Ctrl"), ("down", "F1"), ("up", "F1"), ("up", "Ctrl")]
                self.assertEqual(self.backend.events, [("down", "Space"), ("up", "Space")] + expected)

    def test_reset_and_profile_switch_release_pan_and_drop_pending_modes(self):
        for after_turn in (False, True):
            with self.subTest(after_turn=after_turn):
                self.setUp()
                self.start()
                if after_turn:
                    self.pulse("F23", 2)
                self.engine.reset()
                self.assertFalse(self.engine.held_counts)
                self.assertFalse(self.engine.states)
                self.assertEqual(self.backend.events.count(("up", "Space")), 1)
        self.start()
        other = new_profile("Other")
        self.settings["profiles"].append(other)
        self.engine.switch(other["id"])
        self.assertFalse(self.engine.states)
        self.assertFalse(self.engine.held_counts)

    def test_other_held_owner_keeps_shared_key_until_it_releases(self):
        self.bindings["top_middle"]["hold"] = action("hold_key", "Space")
        self.start()
        self.engine.event("F14", True, 2)
        self.engine.poll(2.301)
        self.pulse("F23", 3)
        self.assertNotIn(("up", "Space"), self.backend.events)
        self.engine.event("F14", False, 4)
        self.assertEqual(self.backend.events[-1], ("up", "Space"))

    def test_rapid_turns_do_not_reactivate_plain_action(self):
        self.start(True)
        for i in range(1000):
            self.pulse("F23" if i % 2 else "F21", 2 + i * .002)
        self.assertEqual(self.backend.events[:2], [("down", "Space"), ("up", "Space")])
        self.assertEqual(self.backend.events[2:], [("scroll", 1 if i % 2 else -1) for i in range(1000)])


class HoldAndDialSettingsTests(unittest.TestCase):
    def test_both_gestures_roundtrip_and_nested_references(self):
        settings = defaults()
        profile = settings["profiles"][0]
        other = new_profile("Other")
        settings["profiles"].append(other)
        mapping = dial_map()
        mapping["cw"] = action("cycle_next", {"cycle_id": "default"})
        mapping["neutral"] = action("profile", other["id"])
        output = combined(dial=action("dial_modifier", mapping))
        for gesture in ("hold", "tap_hold"):
            profile["bindings"]["top_left"][gesture] = copy.deepcopy(output)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            path = Path(directory) / "settings.json"
            save(path, settings)
            self.assertEqual(load(path), settings)
        self.assertTrue(references_profile(output, other["id"]))
        self.assertTrue(references_cycle(output, "default", "default"))

    def test_invalid_recursion_tap_and_wrong_branch_actions_are_rejected(self):
        for output in (action("hold_dial"), combined(action("shortcut", "B")),
                       combined(dial=action("hold_key", "Space")), combined(dial=combined()),
                       action("hold_dial", {"without_dial": "Space", "with_dial": action()})):
            settings = defaults()
            settings["profiles"][0]["bindings"]["top_left"]["hold"] = output
            with self.assertRaises(ValueError):
                validate(settings)
        settings = defaults()
        settings["profiles"][0]["bindings"]["top_left"]["tap"] = combined()
        with self.assertRaises(ValueError):
            validate(settings)


class HoldAndDialUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_inline_five_controls_keep_separate_actions_and_cancel_isolated(self):
        settings = defaults()
        original = copy.deepcopy(settings)
        dialog = BindingDialog(None, settings, "top_left")
        try:
            editor = dialog.editors["hold"]
            editor.kind.setCurrentIndex(editor.kind.findData("dial_modifier"))
            controls = editor.dial_controls
            self.assertEqual(len(controls.buttons), 5)
            for i, (slot, widget) in enumerate(controls.buttons.items()):
                widget.click()
                self.assertIs(controls.stack.currentWidget(), controls.editors[slot])
                output = controls.editors[slot]
                output.kind.setCurrentIndex(output.kind.findData("shortcut"))
                output.key.combo.setCurrentText(f"F{i + 1}")
            self.assertEqual([a["value"] for a in editor.read()["value"].values()], ["F1", "F2", "F3", "F4", "F5"])
            dialog.reject()
            self.assertEqual(settings, original)
        finally:
            dialog.close()

    def test_both_gestures_save_separate_branches_and_reopen(self):
        settings = defaults()
        dialog = BindingDialog(None, settings, "top_left")
        try:
            for gesture in ("hold", "tap_hold"):
                editor = dialog.editors[gesture]
                editor.kind.setCurrentIndex(editor.kind.findData("hold_dial"))
                self.assertEqual(editor.read(), combined())
                editor.split["without_dial"].key.combo.setCurrentText("Shift" if gesture == "tap_hold" else "Space")
                self.assertEqual(editor.split["without_dial"].kind.count(), 2)
                self.assertEqual(editor.split["with_dial"].kind.count(), 4)
            dialog.commit()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            reopened = BindingDialog(None, dialog.result_settings, "top_left")
            try:
                self.assertEqual(reopened.editors["tap_hold"].read(), combined(action("hold_key", "Shift")))
                self.assertEqual(reopened.editors["hold"].read(), combined())
            finally:
                reopened.close()
        finally:
            dialog.close()
