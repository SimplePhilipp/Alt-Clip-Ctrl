"""Dial speed changes distance immediately, without dropping or delaying turns."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from altclipctrl.engine import Engine
from altclipctrl.model import action, defaults, dial_map, load, new_profile, save, validate
from tests.test_altclipctrl import FakeBackend, TEMP_ROOT


class AccelerationTests(unittest.TestCase):
    def setUp(self):
        self.settings = defaults()
        self.settings["scroll_acceleration"] = True
        self.bindings = self.settings["profiles"][0]["bindings"]
        self.bindings["cw"]["tap"] = action("scroll_up")
        self.bindings["ccw"]["tap"] = action("scroll_down")
        self.bindings["pressed_cw"]["tap"] = action("scroll_up")
        self.backend = FakeBackend()
        self.history = []
        self.engine = Engine(self.settings, self.backend, activity=self.history.append)

    def turn(self, at, slot="cw"):
        signal = self.bindings[slot]["input"]
        self.engine.event(signal, True, at, repeated=True)
        self.engine.event(signal, False, at + .001)

    def test_disabled_is_one_fixed_output_per_turn_at_every_speed(self):
        self.settings["scroll_acceleration"] = False
        self.settings["scroll_amount"] = 4
        for at in (0, .001, .002, .1, .5, .501):
            self.turn(at)
        self.assertEqual(self.backend.events, [("scroll", 4)] * 6)

    def test_first_and_slow_turns_use_base_amount(self):
        for at in (0, .2, .4, .6):
            self.turn(at)
        self.assertEqual(self.backend.events, [("scroll", 1)] * 4)

    def test_speed_changes_immediately_with_no_cumulative_ramp(self):
        for at in (0, .06, .12, .14, .16, .36, .42):
            self.turn(at)
        self.assertEqual(self.backend.events, [("scroll", n) for n in (1, 2, 2, 3, 3, 1, 2)])
        self.assertIn("2 notch(es)", self.history[-1]["action"])

    def test_factor_controls_multiplier_and_respects_base_step_size(self):
        self.settings["scroll_acceleration_factor"] = 5
        self.settings["scroll_amount"] = 2
        self.turn(0)
        self.turn(.03)
        self.assertEqual(self.backend.events, [("scroll", 2), ("scroll", 8)])
        self.settings["scroll_acceleration_factor"] = 1
        self.turn(.04)
        self.assertEqual(self.backend.events[-1], ("scroll", 2))

    def test_reversing_and_pausing_restart_at_base_with_global_reverse(self):
        self.settings["reverse_scroll"] = True
        for at, slot in ((0, "cw"), (.02, "cw"), (.04, "ccw"), (.06, "ccw"), (.3, "ccw")):
            self.turn(at, slot)
        self.assertEqual(self.backend.events, [("scroll", n) for n in (-1, -3, 1, 3, 1)])

    def test_pressed_and_unpressed_turns_share_speed_when_direction_is_same(self):
        self.turn(0)
        self.turn(.02, "pressed_cw")
        self.assertEqual(self.backend.events, [("scroll", 1), ("scroll", 3)])

    def test_layer_release_and_reactivation_restart_at_base(self):
        self.bindings["top_left"]["hold"] = action("dial_scroll", {"reverse": True})
        self.engine.event("F13", True, 0)
        self.turn(.01)
        self.turn(.03)
        self.engine.event("F13", False, .04)
        self.turn(.05)
        self.engine.event("F13", True, .06)
        self.turn(.07)
        self.assertEqual(self.backend.events, [("scroll", n) for n in (-1, -3, 1, -1)])

    def test_reset_and_profile_switch_clear_speed(self):
        self.turn(0)
        self.turn(.02)
        self.engine.reset()
        self.turn(.04)
        other = new_profile("Other")
        other["bindings"]["cw"]["tap"] = action("scroll_up")
        self.settings["profiles"].append(other)
        self.engine.switch(other["id"])
        self.turn(.06)
        self.assertEqual(self.backend.events, [("scroll", n) for n in (1, 3, 1, 1)])

    def test_non_scroll_turns_break_the_speed_sequence(self):
        self.turn(0)
        self.turn(.02)
        self.bindings["cw"]["tap"] = action("cycle_next")
        self.turn(.04)
        self.bindings["cw"]["tap"] = action("scroll_up")
        self.turn(.06)
        self.assertEqual(self.backend.events[-1], ("scroll", 1))

    def test_tapped_button_scroll_is_always_fixed(self):
        self.bindings["top_left"]["tap"] = action("scroll_up")
        self.turn(0)
        self.turn(.02)
        self.engine.invoke("top_left", "tap", now=.03)
        self.engine.invoke("top_left", "tap", now=.04)
        self.assertEqual(self.backend.events, [("scroll", n) for n in (1, 3, 1, 1)])

    def test_temporary_dial_mapping_uses_acceleration(self):
        mapping = dial_map()
        mapping["cw"] = action("scroll_down")
        self.bindings["top_left"]["hold"] = action("dial_modifier", mapping)
        self.engine.event("F13", True, 0)
        self.turn(.01)
        self.turn(.03)
        self.assertEqual(self.backend.events, [("scroll", -1), ("scroll", -3)])

    def test_zero_or_backwards_intervals_do_not_amplify(self):
        for at in (1, 1, 0, .2):
            self.turn(at)
        self.assertEqual(self.backend.events, [("scroll", 1)] * 4)

    def test_maximum_settings_stay_in_native_wheel_delta_range(self):
        self.settings.update(scroll_amount=20, scroll_acceleration_factor=10)
        for index in range(100):
            self.turn(index * .001)
        self.assertEqual(len(self.backend.events), 100)
        self.assertEqual(self.backend.events[-1], ("scroll", 199))
        self.assertTrue(all(0 < amount * 120 <= 32767 for _, amount in self.backend.events))


class AccelerationSettingsTests(unittest.TestCase):
    def test_default_disabled_and_older_files_migrate_without_changing_bindings(self):
        settings = defaults()
        self.assertFalse(settings.pop("scroll_acceleration"))
        settings.pop("scroll_acceleration_factor")
        settings["profiles"][0]["bindings"]["cw"]["tap"] = action("scroll_up")
        before = copy.deepcopy(settings["profiles"])
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps(settings), encoding="utf-8")
            migrated = load(path)
            self.assertFalse(migrated["scroll_acceleration"])
            self.assertEqual(migrated["scroll_acceleration_factor"], 3)
            self.assertEqual(migrated["profiles"], before)
            migrated.update(scroll_acceleration=True, scroll_acceleration_factor=4.25)
            save(path, migrated)
            self.assertEqual(load(path), migrated)

    def test_rejects_invalid_values(self):
        for field, values in (("scroll_acceleration", (0, 1, "yes", None)),
                              ("scroll_acceleration_factor", (0, .5, 10.01, True, "3", None, float("nan"), float("inf")))):
            for value in values:
                with self.subTest(field=field, value=value):
                    settings = defaults()
                    settings[field] = value
                    with self.assertRaises(ValueError):
                        validate(settings)


if __name__ == "__main__":
    unittest.main()
