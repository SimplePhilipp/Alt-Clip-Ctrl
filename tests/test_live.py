import copy
import threading
import time
import unittest

from altclipctrl.live import LiveInput
from altclipctrl.model import action, defaults, new_profile
from tests.test_altclipctrl import FakeBackend


class LiveBackend(FakeBackend):
    def __init__(self):
        super().__init__()
        self.window = 20
        self.program = "Browser.exe"
        self.sent = threading.Event()

    def foreground_token(self):
        return self.window

    def program_for_window(self, token):
        return self.program

    def scroll(self, amount):
        super().scroll(amount)
        self.sent.set()


class LiveInputTests(unittest.TestCase):
    def setUp(self):
        self.settings = defaults()
        self.settings["profiles"][0]["bindings"]["top_left"]["tap_hold"] = action("dial_scroll", {"reverse": False})
        self.backend = LiveBackend()
        self.errors = []
        self.live = LiveInput(self.settings, self.backend, self.errors.append)
        self.live.start()

    def tearDown(self):
        self.live.stop()
        self.assertEqual(self.errors, [])

    def event(self, signal, down, now):
        return self.live.capture(signal, down, now, self.backend.window)

    def activate(self, now=None):
        now = time.monotonic() if now is None else now
        self.event("F13", True, now)
        self.event("F13", False, now + .001)
        self.event("F13", True, now + .002)
        return now + .003

    def test_first_turn_is_sent_before_capture_returns_without_ui_pumping(self):
        now = self.activate()
        self.event("F23", True, now)
        self.assertEqual(self.backend.events, [("scroll", 1)])
        self.assertEqual(self.live.snapshot()[0][-1]["action"], "Scroll up · 1 notch(es) · via Top left")

    def test_gui_can_be_busy_while_native_input_keeps_dispatching(self):
        self.activate()
        def native_input():
            self.event("F23", True, time.monotonic())
        source = threading.Thread(target=native_input)
        source.start()
        # No event loop, history update or GUI callback is run here.
        self.assertTrue(self.backend.sent.wait(.2))
        source.join(.2)
        self.assertFalse(source.is_alive())
        self.assertEqual(self.backend.events, [("scroll", 1)])

    def test_initial_steps_and_reversals_stay_one_for_one_without_acceleration(self):
        now = self.activate()
        expected = []
        for i in range(3000):
            direction = 1 if i % 4 else -1
            signal = "F23" if direction > 0 else "F21"
            self.event(signal, True, now + i * .0001)
            self.event(signal, False, now + i * .0001)
            expected.append(("scroll", direction))
        self.assertEqual(self.backend.events, expected)
        self.assertLessEqual(len(self.live.activities), 3)
        self.assertLessEqual(len(self.live.lights), 3)
        self.assertEqual(len(self.live.snapshot()[0]), 3)
        self.assertEqual(self.live.snapshot()[0], [])

    def test_dial_mode_does_not_require_hold_timer_wake_for_first_turn(self):
        self.settings["profiles"][0]["bindings"]["top_left"]["hold"] = action("dial_scroll")
        self.live.configure(self.settings)
        now = time.monotonic()
        self.event("F13", True, now)
        self.event("F21", True, now + .001)
        self.assertEqual(self.backend.events, [("scroll", -1)])

    def test_own_window_remains_preview_and_never_sends_native_output(self):
        self.backend.program = "@self"
        self.backend.window = 10
        self.assertIsNone(self.event("F13", True, time.monotonic()))
        self.assertEqual(self.backend.events, [])

    def test_focus_change_drops_mode_and_new_tap_hold_works(self):
        self.activate()
        self.backend.window = 30
        self.live.sync_scope()
        self.assertIsNone(self.live.engine.dial_layer)
        self.activate()
        self.event("F23", True, time.monotonic())
        self.assertEqual(self.backend.events, [("scroll", 1)])

    def test_settings_are_private_and_configuration_and_pause_clear_modes(self):
        self.activate()
        self.live.set_paused(True)
        self.assertFalse(self.event("F23", True, time.monotonic()))
        self.assertIsNone(self.live.engine.dial_layer)
        self.live.set_paused(False)
        result = copy.deepcopy(self.settings)
        result["profiles"][0]["name"] = "Changed"
        self.live.configure(result)
        result["profiles"][0]["name"] = "Changed again"
        self.assertEqual(self.live.engine.profile["name"], "Changed")

    def test_automatic_profile_and_button_profile_switch_need_no_gui(self):
        other = new_profile("Browser")
        other["programs"] = ["Browser.exe"]
        target = self.settings["profiles"][0]["id"]
        other["bindings"]["top_left"]["tap"] = action("profile", target)
        self.settings["profiles"].append(other)
        self.live.configure(self.settings)
        now = time.monotonic()
        self.event("F13", True, now)
        self.event("F13", False, now + .001)
        with self.live.condition:
            self.live.engine.poll(now + .2)
        self.assertEqual(self.live.engine.profile_id, target)
        self.assertEqual(self.settings["active_profile"], target)


if __name__ == "__main__":
    unittest.main()
