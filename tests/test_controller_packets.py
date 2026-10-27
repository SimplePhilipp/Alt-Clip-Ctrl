"""Controller packets are injected key pulses, not physical-key auto-repeat."""
import ctypes
import sys
import time
import unittest

from altclipctrl.live import LiveInput
from altclipctrl.model import action, defaults
from tests.test_live import LiveBackend


class ControllerPacketTests(unittest.TestCase):
    def setUp(self):
        self.settings = defaults()
        self.settings["profiles"][0]["bindings"]["top_left"]["tap_hold"] = action("dial_scroll", {"reverse": False})
        self.backend = LiveBackend()
        self.errors = []
        self.live = LiveInput(self.settings, self.backend, self.errors.append)
        self.live.start()
        now = time.monotonic()
        self.live.capture("F13", True, now, 20, injected=True)
        self.live.capture("F13", False, now + .001, 20, injected=True)
        self.live.capture("F13", True, now + .002, 20, injected=True)
        self.now = now + .003

    def tearDown(self):
        self.live.stop()
        self.assertEqual(self.errors, [])

    def test_turns_overlapping_a_130ms_key_press_are_not_lost(self):
        for index in range(5):
            self.live.capture("F23", True, self.now + index * .025, 20, injected=True)
        self.live.capture("F23", False, self.now + .130, 20, injected=True)
        self.assertEqual(self.backend.events, [("scroll", 1)] * 5)

    def test_each_direction_and_pressed_turn_counts_every_injected_down(self):
        expected = []
        for signal, direction in (("F20", -1), ("F21", -1), ("F23", 1), ("F24", 1)):
            for index in range(7):
                self.live.capture(signal, True, self.now + index * .01, 20, injected=True)
                expected.append(("scroll", direction))
            self.live.capture(signal, False, self.now + .131, 20, injected=True)
        self.assertEqual(self.backend.events, expected)

    def test_late_releases_dont_change_one_step_per_simulated_down(self):
        for pressed in (True, True, False, True, False, False, True, False):
            self.live.capture("F21", pressed, self.now, 20, injected=True)
        self.assertEqual(self.backend.events, [("scroll", -1)] * 4)

    def test_activation_button_injected_repeats_do_not_reactivate_or_scroll(self):
        initial_order = self.live.engine.dial_order
        for index in range(50):
            self.live.capture("F13", True, self.now + .5 + index / 16, 20, injected=True)
        self.assertEqual(self.live.engine.dial_order, initial_order)
        self.assertEqual(self.backend.events, [])

    def test_physical_keyboard_repeat_is_still_suppressed(self):
        for index in range(8):
            self.live.capture("F23", True, self.now + index * .01, 20, injected=False)
        self.assertEqual(self.backend.events, [("scroll", 1)])


@unittest.skipUnless(sys.platform == "win32", "Windows low-level input metadata")
class HookRepeatTests(unittest.TestCase):
    def test_hook_preserves_injected_downs_but_filters_physical_auto_repeat(self):
        from altclipctrl.platforms import WindowsBackend
        captured = []
        backend = WindowsBackend(lambda *args: captured.append(args) or True, lambda _: None)
        data = backend.HookData(vk=backend.codes["F21"], flags=0x10)
        for _ in range(5):
            self.assertEqual(backend.callback(0, 0x100, ctypes.addressof(data)), 1)
        backend.callback(0, 0x101, ctypes.addressof(data))
        self.assertEqual(len(captured), 6)
        self.assertTrue(all(event[3] for event in captured))
        captured.clear()
        data.flags = 0
        for _ in range(5):
            backend.callback(0, 0x100, ctypes.addressof(data))
        backend.callback(0, 0x101, ctypes.addressof(data))
        self.assertEqual(len(captured), 2)


if __name__ == "__main__":
    unittest.main()
