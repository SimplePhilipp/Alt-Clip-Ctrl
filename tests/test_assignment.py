import copy
import json
from pathlib import Path
import tempfile
import unittest

from altclipctrl.assignment import QuickAssignment
from altclipctrl.engine import Engine
from altclipctrl.model import action, defaults, load, save, validate
from altclipctrl.platforms import PreviewBackend
from tests.test_altclipctrl import FakeBackend, TEMP_ROOT


class AssignmentTests(unittest.TestCase):
    def setUp(self):
        self.settings = defaults()
        self.assignment = QuickAssignment(self.settings["profiles"][0])

    def pulse(self, key, now):
        self.assignment.event(key, True, now)
        self.assignment.event(key, False, now + .01)

    def turn_step(self):
        while self.assignment.slot != "ccw":
            self.assignment.skip()

    def test_button_is_one_press_and_waits_for_release(self):
        self.assignment.event("F1", True, 1)
        self.assertEqual(self.assignment.recorded, {"top_left": "F1"})
        self.assertEqual(self.assignment.slot, "top_left")
        self.assignment.event("F1", True, 1.1)
        self.assignment.event("F1", False, 1.2)
        self.assertEqual(self.assignment.slot, "top_middle")
        self.assertEqual(len(self.assignment.recorded), 1)

    def test_neutral_single_press(self):
        while self.assignment.slot != "neutral":
            self.assignment.skip()
        self.pulse("F22", 1)
        self.assertEqual(self.assignment.recorded["neutral"], "F22")
        self.assertEqual(self.assignment.slot, "ccw")

    def test_turn_requires_three_complete_matching_pulses(self):
        self.turn_step()
        self.pulse("F21", 1)
        self.pulse("F21", 1.1)
        self.assertNotIn("ccw", self.assignment.recorded)
        self.pulse("F21", 1.2)
        self.assertEqual(self.assignment.recorded["ccw"], "F21")
        self.assertEqual(self.assignment.slot, "cw")

    def test_holding_key_is_not_a_turn(self):
        self.turn_step()
        for i in range(40):
            self.assignment.event("F21", True, 1 + i / 100)
        self.assertEqual(self.assignment.slot, "ccw")
        self.assertEqual(self.assignment.recorded, {})
        self.assertEqual(len(self.assignment.samples["F21"]), 1)

    def test_separate_candidates_and_expiration(self):
        self.turn_step()
        self.pulse("F22", 1)  # initial dial press
        self.pulse("F21", 1.1)
        self.pulse("F21", 1.2)
        self.assertEqual(self.assignment.recorded, {})
        self.pulse("F21", 4)  # old samples have expired
        self.assertEqual(len(self.assignment.samples["F21"]), 1)
        self.pulse("F21", 4.1)
        self.pulse("F21", 4.2)
        self.assertEqual(self.assignment.recorded, {"ccw": "F21"})

    def test_pressed_turn_ignores_neutral_signal(self):
        self.assignment.recorded["neutral"] = "F22"
        self.assignment.index = self.assignment.ORDER.index("pressed_ccw")
        self.pulse("F22", 1)
        for i in range(3):
            self.pulse("F20", 1.1 + i / 10)
        self.assertEqual(self.assignment.recorded["pressed_ccw"], "F20")
        self.assertEqual(self.assignment.slot, "pressed_cw")

    def test_modifier_chord_and_duplicates_rejected(self):
        self.assignment.event("Ctrl", True, 1)
        self.pulse("F13", 1.1)
        self.assertEqual(self.assignment.recorded, {})
        self.assignment.event("Ctrl", False, 1.2)
        self.pulse("F13", 1.3)
        self.pulse("F13", 1.4)
        self.assertEqual(self.assignment.slot, "top_middle")
        self.assertIn("already recorded", self.assignment.message)

    def test_complete_draft_preserves_outputs_and_apply_is_atomic(self):
        self.settings["profiles"][0]["bindings"]["top_left"]["hold"] = action("hold_key", "Shift")
        before = copy.deepcopy(self.settings)
        now = 1
        for slot in self.assignment.ORDER:
            key = self.settings["profiles"][0]["bindings"][slot]["input"]
            for _ in range(3 if slot in {"ccw", "cw", "pressed_ccw", "pressed_cw"} else 1):
                self.pulse(key, now)
                now += .1
        self.assertIsNone(self.assignment.slot)
        self.assertEqual(self.settings, before)
        result = self.assignment.apply(self.settings)
        self.assertEqual(result, self.settings)
        result["profiles"][0]["name"] = "Edited draft"
        self.assertEqual(self.settings, before)

    def test_skipped_conflict_is_reported_without_mutating_settings(self):
        before = copy.deepcopy(self.settings)
        self.pulse("F14", 1)
        while self.assignment.slot:
            self.assignment.skip()
        with self.assertRaises(ValueError):
            self.assignment.apply(self.settings)
        self.assertEqual(self.settings, before)
        self.assignment.back()
        self.assertIsNotNone(self.assignment.slot)

    def test_focus_loss_does_not_leave_recording_stuck(self):
        self.assignment.event("F13", True, 1)
        self.assignment.suspend()
        self.assertEqual(self.assignment.slot, "top_middle")
        self.pulse("F14", 1.2)
        self.assertEqual(self.assignment.slot, "top_right")


class GestureMenuAndHistoryTests(unittest.TestCase):
    def test_disallowed_gesture_actions_rejected(self):
        for gesture, kind in (("hold", "shortcut"), ("tap_hold", "shortcut"), ("tap", "hold_key")):
            settings = defaults()
            settings["profiles"][0]["bindings"]["top_left"][gesture] = action(kind, "B")
            with self.assertRaises(ValueError):
                validate(settings)

    def test_older_shortcut_in_hold_migrates_without_losing_other_gestures(self):
        settings = defaults()
        binding = settings["profiles"][0]["bindings"]["left_upper"]
        binding["hold"] = action("shortcut", "Ctrl+B")
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps(settings))
            result = load(path)
        self.assertEqual(result["profiles"][0]["bindings"]["left_upper"]["hold"], action("hold_key", "Ctrl+B"))
        self.assertEqual(result["profiles"][0]["bindings"]["left_upper"]["tap"], action())

    def test_history_records_executed_action_with_source_and_resolved_cycle(self):
        settings, backend, events = defaults(), FakeBackend(), []
        binding = settings["profiles"][0]["bindings"]["cw"]
        binding["name"] = "My wheel"
        binding["tap"] = action("cycle_next")
        engine = Engine(settings, backend, activity=events.append)
        engine.event("F23", True, 1)
        self.assertEqual(events[0]["name"], "My wheel")
        self.assertEqual(events[0]["gesture"], "Turn")
        self.assertEqual(events[0]["action"], "Cycle → Pen · B · Default")
        self.assertEqual(backend.events, [("down", "B"), ("up", "B")])

    def test_preview_runs_gestures_without_calling_real_backend(self):
        settings, events = defaults(), []
        settings["profiles"][0]["bindings"]["top_left"]["hold"] = action("hold_key", "Shift")
        engine = Engine(settings, PreviewBackend(), activity=events.append)
        engine.event("F13", True, 1)
        engine.poll(1.301)
        self.assertEqual(events[0]["action"], "Hold Shift")
        engine.event("F13", False, 1.4)
        self.assertEqual(engine.held_counts, {})


if __name__ == "__main__":
    unittest.main()
