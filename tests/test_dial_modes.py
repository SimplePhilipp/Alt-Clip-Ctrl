import copy
import json
from pathlib import Path
import tempfile
import unittest

from altclipctrl.engine import Engine
from altclipctrl.model import DIAL_SLOTS, action, defaults, dial_map, load, new_profile, references_profile, save, validate
from tests.test_altclipctrl import FakeBackend, TEMP_ROOT


class DialModeTests(unittest.TestCase):
    def setUp(self):
        self.settings = defaults()
        self.backend = FakeBackend()
        self.events = []
        self.engine = Engine(self.settings, self.backend, activity=self.events.append)
        self.bindings = self.engine.profile["bindings"]
        self.bindings["cw"]["tap"] = action("shortcut", "B")
        self.bindings["ccw"]["tap"] = action("shortcut", "E")

    def pulse(self, signal, now=2):
        self.engine.event(signal, True, now)
        self.engine.event(signal, False, now + .001)

    def start_mode(self, kind, *, reverse=False, second=False, slot="top_left", key="F13"):
        gesture = "tap_hold" if second else "hold"
        self.bindings[slot][gesture] = action(kind, {"reverse": reverse})
        if second:
            self.pulse(key, 1)
            self.engine.event(key, True, 1.05)
        else:
            self.engine.event(key, True, 1)
            self.engine.poll(1.301)

    def test_scrolling_is_a_held_mode_and_restores_base_on_release(self):
        self.start_mode("dial_scroll")
        self.assertEqual(self.backend.events, [])
        for key in ("F23", "F24", "F21", "F20"):
            self.pulse(key)
        self.assertEqual(self.backend.events, [("scroll", 1), ("scroll", 1), ("scroll", -1), ("scroll", -1)])
        self.engine.event("F13", False, 3)
        self.assertIsNone(self.engine.dial_layer)
        self.pulse("F23", 3.1)
        self.assertEqual(self.backend.events[-2:], [("down", "B"), ("up", "B")])

    def test_action_reverse_for_both_gestures_and_each_turn_kind(self):
        for second in (False, True):
            for kind in ("dial_scroll", "dial_cycle"):
                for reverse in (False, True):
                    with self.subTest(second=second, kind=kind, reverse=reverse):
                        self.setUp()
                        self.start_mode(kind, reverse=reverse, second=second)
                        self.assertEqual(self.backend.events, [])
                        self.pulse("F23")
                        if kind == "dial_scroll":
                            self.assertEqual(self.backend.events, [("scroll", -1 if reverse else 1)])
                        else:
                            self.assertEqual(self.backend.events, [("down", "E" if reverse else "B"), ("up", "E" if reverse else "B")])
                        self.engine.event("F13", False, 3)
                        self.assertIsNone(self.engine.dial_layer)

    def test_global_scroll_amount_and_reversal_combine_with_action(self):
        self.settings.update(scroll_amount=3, reverse_scroll=True)
        self.start_mode("dial_scroll", reverse=True)
        self.pulse("F23")
        self.pulse("F21")
        self.assertEqual(self.backend.events, [("scroll", 3), ("scroll", -3)])

    def test_cycling_wraps_in_opposite_directions(self):
        self.start_mode("dial_cycle")
        self.pulse("F23")
        self.pulse("F24")
        self.pulse("F21")
        self.pulse("F20")
        downs = [key for event, key in self.backend.events if event == "down"]
        self.assertEqual(downs, ["B", "E", "B", "E"])

    def test_first_turn_starts_mode_before_hold_deadline(self):
        self.bindings["top_left"]["hold"] = action("dial_scroll")
        self.bindings["top_left"]["tap"] = action("shortcut", "T")
        self.engine.event("F13", True, 1)
        self.pulse("F23", 1.01)
        self.engine.event("F13", False, 1.03)
        self.engine.poll(3)
        self.assertEqual(self.backend.events, [("scroll", 1)])
        self.assertIsNone(self.engine.dial_layer)

    def test_neutral_can_be_the_mode_owner(self):
        self.bindings["neutral"]["hold"] = action("dial_scroll")
        self.bindings["neutral"]["tap"] = action("shortcut", "T")
        self.engine.event("F22", True, 1)
        self.pulse("F24", 1.01)
        self.engine.event("F22", False, 1.1)
        self.engine.poll(3)
        self.assertEqual(self.backend.events, [("scroll", 1)])
        self.assertIsNone(self.engine.dial_layer)

    def test_last_held_mode_wins_and_releasing_it_resumes_previous(self):
        self.start_mode("dial_scroll")
        self.bindings["top_middle"]["hold"] = action("dial_cycle")
        self.engine.event("F14", True, 2)
        self.pulse("F23", 2.01)
        self.assertEqual(self.backend.events, [("down", "B"), ("up", "B")])
        self.engine.event("F14", False, 2.1)
        self.pulse("F23", 2.2)
        self.assertEqual(self.backend.events[-1], ("scroll", 1))
        self.engine.event("F13", False, 2.3)
        self.pulse("F23", 2.4)
        self.assertEqual(self.backend.events[-2:], [("down", "B"), ("up", "B")])

    def modifier(self):
        mapping = dial_map()
        for slot, key in zip(DIAL_SLOTS, ("F1", "F2", "F3", "F4", "F5")):
            mapping[slot] = action("shortcut", key)
        self.bindings["top_left"]["hold"] = action("dial_modifier", mapping)
        self.engine.event("F13", True, 1)
        self.engine.poll(1.301)
        return mapping

    def test_custom_turn_outputs_and_neutral_then_restoration(self):
        mapping = self.modifier()
        for slot in DIAL_SLOTS:
            self.pulse(self.bindings[slot]["input"], 2)
            if slot == "neutral":
                self.engine.poll(2.2)
        self.assertEqual([key for event, key in self.backend.events if event == "down"], ["F1", "F2", "F3", "F4", "F5"])
        self.assertIn("via Top left", self.events[-1]["action"])
        self.engine.event("F13", False, 3)
        self.pulse("F23", 3.1)
        self.assertEqual(self.backend.events[-2:], [("down", "B"), ("up", "B")])
        self.assertEqual(self.bindings["cw"]["tap"], action("shortcut", "B"))

    def test_custom_press_cancelled_when_turned_while_pressed(self):
        self.modifier()
        self.engine.event("F22", True, 2)
        self.pulse("F24", 2.02)
        self.engine.event("F22", False, 2.04)
        self.engine.poll(3)
        self.assertEqual(self.backend.events, [("down", "F5"), ("up", "F5")])

    def test_temporary_neutral_action_dies_if_owner_released_before_dial(self):
        self.modifier()
        self.engine.event("F22", True, 2)
        self.engine.event("F13", False, 2.02)
        self.engine.event("F22", False, 2.04)
        self.engine.poll(3)
        self.assertEqual(self.backend.events, [])

    def test_temporary_neutral_is_one_input_even_when_held_or_double_pressed(self):
        self.modifier()
        self.engine.event("F22", True, 2)
        self.engine.poll(3)
        self.engine.event("F22", False, 3.1)
        self.pulse("F22", 3.15)
        self.assertEqual(self.backend.events, [("down", "F3"), ("up", "F3"), ("down", "F3"), ("up", "F3")])

    def test_reset_and_profile_switch_clear_all_temporary_modes(self):
        self.start_mode("dial_scroll")
        self.engine.reset()
        self.assertIsNone(self.engine.dial_layer)
        self.pulse("F23")
        self.assertEqual(self.backend.events, [("down", "B"), ("up", "B")])
        self.start_mode("dial_scroll")
        other = new_profile("Other")
        self.settings["profiles"].append(other)
        self.engine.switch(other["id"])
        self.assertIsNone(self.engine.dial_layer)


class DialModeSettingsTests(unittest.TestCase):
    def test_direction_and_five_outputs_roundtrip(self):
        settings = defaults()
        b = settings["profiles"][0]["bindings"]
        b["top_left"]["hold"] = action("dial_scroll", {"reverse": True})
        b["top_left"]["tap_hold"] = action("dial_cycle", {"reverse": False})
        b["top_middle"]["hold"] = action("dial_modifier", dial_map(settings["profiles"][0]))
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            path = Path(directory) / "settings.json"
            save(path, settings)
            self.assertEqual(load(path), settings)

    def test_old_directional_held_actions_migrate_to_modes(self):
        for old, new, reverse in (("scroll_up", "dial_scroll", False), ("scroll_down", "dial_scroll", True),
                                  ("cycle_next", "dial_cycle", False), ("cycle_previous", "dial_cycle", True)):
            settings = defaults()
            settings["profiles"][0]["bindings"]["top_left"]["hold"] = action(old)
            with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
                path = Path(directory) / "settings.json"
                path.write_text(json.dumps(settings))
                result = load(path)
            self.assertEqual(result["profiles"][0]["bindings"]["top_left"]["hold"], action(new, {"reverse": reverse}))

    def test_dial_modes_cannot_recurse_or_be_used_on_tap(self):
        for kind in ("dial_scroll", "dial_cycle", "dial_modifier"):
            settings = defaults()
            settings["profiles"][0]["bindings"]["top_left"]["tap"] = action(kind)
            with self.assertRaises(ValueError):
                validate(settings)
        settings = defaults()
        mapping = dial_map()
        mapping["cw"] = action("dial_cycle")
        settings["profiles"][0]["bindings"]["top_left"]["hold"] = action("dial_modifier", mapping)
        with self.assertRaises(ValueError):
            validate(settings)

    def test_nested_profile_reference_is_found_and_validated(self):
        settings = defaults()
        other = new_profile("Other")
        settings["profiles"].append(other)
        output = action("dial_modifier", dial_map())
        output["value"]["neutral"] = action("profile", other["id"])
        settings["profiles"][0]["bindings"]["top_left"]["hold"] = output
        validate(settings)
        self.assertTrue(references_profile(output, other["id"]))
        settings["profiles"].pop()
        with self.assertRaises(ValueError):
            validate(settings)


if __name__ == "__main__":
    unittest.main()
