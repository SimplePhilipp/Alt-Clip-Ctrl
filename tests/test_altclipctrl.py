import copy
import ctypes
import json
import tempfile
import unittest
from pathlib import Path

from altclipctrl.engine import Engine
from altclipctrl.model import SLOTS, action, chord, defaults, import_legacy, load, new_profile, save, validate
from altclipctrl.platforms import Backend

TEMP_ROOT = Path(__file__).resolve().parents[1] / "test-results"
TEMP_ROOT.mkdir(exist_ok=True)


class FakeBackend(Backend):
    def __init__(self):
        super().__init__(lambda *_: False, lambda *_: None)
        self.events = []

    def key_down(self, key):
        self.events.append(("down", key))

    def key_up(self, key):
        self.events.append(("up", key))

    def scroll(self, amount):
        self.events.append(("scroll", amount))


class ModelTests(unittest.TestCase):
    def test_all_function_keys_input_and_output(self):
        for number in range(1, 25):
            self.assertEqual(chord(f"Ctrl+Shift+F{number}"), ("Ctrl", "Shift", f"F{number}"))
            settings = defaults()
            # Rotate assignments so no input is duplicated.
            for i, binding in enumerate(settings["profiles"][0]["bindings"].values()):
                binding["input"] = f"F{(number + i - 1) % 24 + 1}"
                binding["tap"] = action("shortcut", f"F{number}")
            validate(settings)

    def test_signal_order_unique_and_no_modifier_inputs(self):
        settings = defaults()
        bindings = settings["profiles"][0]["bindings"]
        self.assertEqual([s for s, _ in SLOTS][-5:], ["pressed_ccw", "ccw", "neutral", "cw", "pressed_cw"])
        self.assertEqual(len(set(b["input"] for b in bindings.values())), 12)
        for value in ("Ctrl", "Alt", "Shift", "Ctrl+F13", "F25", "Meta", "WheelUp"):
            bad = copy.deepcopy(settings)
            bad["profiles"][0]["bindings"]["top_left"]["input"] = value
            with self.assertRaises(ValueError, msg=value):
                validate(bad)
        bindings["top_left"]["input"] = bindings["top_right"]["input"]
        with self.assertRaises(ValueError):
            validate(settings)

    def test_profile_references_program_conflicts(self):
        settings = defaults()
        other = new_profile("Drawing")
        settings["profiles"].append(other)
        settings["profiles"][0]["bindings"]["top_left"]["tap"] = action("profile", other["id"])
        validate(settings)
        settings["profiles"].pop()
        with self.assertRaises(ValueError):
            validate(settings)
        settings = defaults()
        settings["profiles"][0]["programs"] = ["Paint.exe"]
        other["programs"] = ["paint.EXE"]
        settings["profiles"].append(other)
        with self.assertRaises(ValueError):
            validate(settings)

    def test_atomic_roundtrip_and_failed_validation_retains_file(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            path = Path(directory) / "settings.json"
            settings = defaults()
            settings["profiles"][0]["name"] = "Pén · 绘画"
            save(path, settings)
            self.assertEqual(load(path), settings)
            before = path.read_bytes()
            settings["hold_ms"] = -1
            with self.assertRaises(ValueError):
                save(path, settings)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_legacy_import_keeps_source_separate_and_reuses_cycles(self):
        original = defaults()
        result, notes = import_legacy(Path(__file__).resolve().parents[1] / "AltClipCtrl.settings.example.xml", original)
        self.assertEqual(len(original["profiles"]), 1)
        self.assertEqual(len(result["profiles"]), 4)
        self.assertEqual(len(result["profiles"][1]["cycle"]), 20)
        self.assertTrue(notes)
        validate(result)
        self.assertEqual(result["profiles"][1]["bindings"]["neutral"]["input"], "F22")

    def test_xml_entities_rejected(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            path = Path(directory) / "bad.xml"
            path.write_text('<!DOCTYPE a [<!ENTITY x "bad">]><AppSettings/>')
            with self.assertRaises(ValueError):
                import_legacy(path, defaults())


class GestureTests(unittest.TestCase):
    def setUp(self):
        self.settings = defaults()
        self.backend = FakeBackend()
        self.engine = Engine(self.settings, self.backend)
        self.bindings = self.engine.profile["bindings"]
        self.bindings["top_left"]["tap"] = action("shortcut", "B")
        self.bindings["top_left"]["hold"] = action("hold_key", "Ctrl+Space")
        self.bindings["top_left"]["tap_hold"] = action("hold_key", "Shift+E")

    def tap(self, key="F13", now=1):
        self.engine.event(key, True, now)
        self.engine.event(key, False, now + .02)

    def test_tap_wait_and_double_press(self):
        self.tap()
        self.engine.poll(1.119)
        self.assertEqual(self.backend.events, [])
        self.engine.poll(1.121)
        self.assertEqual(self.backend.events, [("down", "B"), ("up", "B")])
        self.backend.events.clear()
        self.tap(now=2)
        self.engine.event("F13", True, 2.05)
        self.assertEqual(self.backend.events, [("down", "Shift"), ("down", "E")])
        self.engine.event("F13", False, 2.06)
        self.engine.poll(3)
        self.assertEqual(self.backend.events[-2:], [("up", "E"), ("up", "Shift")])
        self.assertNotIn(("down", "B"), self.backend.events)

    def test_hold_repeat_and_release(self):
        self.engine.event("F13", True, 1)
        for i in range(100):
            self.engine.event("F13", True, 1.01 + i / 1000)
        self.engine.poll(1.301)
        self.assertEqual(self.backend.events, [("down", "Ctrl"), ("down", "Space")])
        self.engine.event("F13", False, 1.4)
        self.engine.poll(2)
        self.assertEqual(self.backend.events[-2:], [("up", "Space"), ("up", "Ctrl")])
        self.assertEqual(len(self.backend.events), 4)

    def test_late_keyup_still_runs_hold_and_releases(self):
        self.engine.event("F13", True, 1)
        self.engine.event("F13", False, 2)
        self.assertEqual(self.backend.events, [("down", "Ctrl"), ("down", "Space"), ("up", "Space"), ("up", "Ctrl")])

    def test_expired_tap_before_new_press(self):
        self.tap()
        self.engine.event("F13", True, 1.2)
        self.assertEqual(self.backend.events, [("down", "B"), ("up", "B")])
        self.engine.poll(1.501)
        self.assertEqual(self.backend.events[-2:], [("down", "Ctrl"), ("down", "Space")])

    def test_shared_held_keys_refcount(self):
        self.bindings["top_middle"]["hold"] = action("hold_key", "Ctrl+E")
        self.engine.event("F13", True, 1)
        self.engine.event("F14", True, 1)
        self.engine.poll(1.301)
        self.engine.event("F13", False, 1.4)
        self.assertNotIn(("up", "Ctrl"), self.backend.events)
        self.engine.event("F14", False, 1.5)
        self.assertEqual(self.backend.events.count(("down", "Ctrl")), 1)
        self.assertEqual(self.backend.events.count(("up", "Ctrl")), 1)

    def test_reset_releases_all_and_cancels_tap(self):
        self.engine.event("F13", True, 1)
        self.engine.poll(1.301)
        self.engine.reset()
        self.engine.poll(9)
        self.assertEqual(self.backend.events[-2:], [("up", "Space"), ("up", "Ctrl")])
        self.assertEqual(self.engine.states, {})
        self.assertEqual(self.engine.held_counts, {})

    def test_profile_action_and_independent_cycles(self):
        other = new_profile("Painting")
        self.settings["profiles"].append(other)
        self.bindings["top_right"]["tap"] = action("profile", other["id"])
        self.engine.execute(action("cycle_next"))
        self.engine.execute(action("cycle_next"))
        self.assertEqual(self.engine.positions[self.engine.profile_id], 1)
        self.tap("F15")
        self.engine.poll(1.121)
        self.assertEqual(self.engine.profile_id, other["id"])
        self.engine.execute(action("cycle_previous"))
        self.assertEqual(self.engine.positions[other["id"]], 1)
        self.engine.switch(self.settings["profiles"][0]["id"])
        self.engine.execute(action("cycle_next"))
        self.assertEqual(self.engine.positions[self.engine.profile_id], 0)

    def test_rapid_reversals_do_not_coalesce(self):
        self.bindings["cw"]["tap"] = action("scroll_up")
        self.bindings["ccw"]["tap"] = action("scroll_down")
        expected = []
        for i in range(12000):
            signal, amount = ("F23", 1) if i % 3 else ("F21", -1)
            now = i / 1000
            self.engine.event(signal, True, now)
            self.engine.event(signal, False, now)
            expected.append(("scroll", amount))
        self.assertEqual(self.backend.events, expected)

    def test_pressed_turn_cancels_neutral_tap(self):
        self.bindings["neutral"]["tap"] = action("shortcut", "N")
        self.bindings["pressed_ccw"]["tap"] = action("shortcut", "X")
        self.engine.event("F22", True, 1)
        self.engine.event("F20", True, 1.02)
        self.engine.event("F20", False, 1.03)
        self.engine.event("F22", False, 1.04)
        self.engine.poll(2)
        self.assertEqual(self.backend.events, [("down", "X"), ("up", "X")])

    def test_disabled_gestures_and_scroll_options(self):
        self.bindings["cw"]["tap"] = action()
        self.engine.event("F23", True, 1)
        self.engine.event("F23", False, 1)
        self.assertEqual(self.backend.events, [])
        self.settings["scroll_amount"], self.settings["reverse_scroll"] = 4, True
        self.engine.execute(action("scroll_down"))
        self.assertEqual(self.backend.events, [("scroll", 4)])

    def test_direct_shortcut_tracking_and_foreign_signal(self):
        self.engine.track("E")
        self.assertEqual(self.engine.positions[self.engine.profile_id], 1)
        self.engine.event("Alt", True, 1)
        self.engine.event("F1", True, 1)
        self.engine.poll(10)
        self.assertEqual(self.backend.events, [])

    def test_shortcut_does_not_release_borrowed_hold(self):
        self.engine.event("F13", True, 1)
        self.engine.poll(1.301)
        self.engine.execute(action("shortcut", "Ctrl+B"))
        self.assertEqual(self.backend.events[-2:], [("down", "B"), ("up", "B")])

    def test_cleanup_continues_after_one_failure(self):
        self.engine.event("F13", True, 1)
        self.engine.poll(1.301)
        def fail(key):
            self.backend.events.append(("up", key))
            if key == "Space":
                raise OSError("device gone")
        self.backend.key_up = fail
        with self.assertRaises(OSError):
            self.engine.reset()
        self.assertEqual(self.backend.events[-1], ("up", "Ctrl"))
        self.assertEqual(self.engine.held_counts, {})

    def test_real_modifier_is_borrowed_and_preserved(self):
        physical = {"Ctrl"}
        self.backend.physical_down = lambda key: key in physical
        self.engine.event("F13", True, 1)
        self.engine.poll(1.301)
        self.assertEqual(self.backend.events, [("down", "Space")])
        physical.remove("Ctrl")
        self.engine.physical_release("Ctrl")
        self.assertEqual(self.backend.events[-1], ("down", "Ctrl"))
        physical.add("Ctrl")
        self.engine.reset()
        self.assertNotIn(("up", "Ctrl"), self.backend.events)
        self.assertEqual(self.backend.events[-1], ("up", "Space"))


class WindowsAdapterTests(unittest.TestCase):
    @unittest.skipUnless(__import__("sys").platform == "win32", "Windows native adapter")
    def test_tagged_output_layout_f1_f24_and_hook_filter(self):
        from altclipctrl.platforms import MARKER, WindowsBackend
        captured, packets = [], []
        backend = WindowsBackend(lambda *args: captured.append(args) or True, print)
        backend.packet = packets.append  # Inspect packets without sending real input.
        self.assertEqual(ctypes.sizeof(backend.Input), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
        for i in range(1, 25):
            backend.key_down(f"F{i}")
            backend.key_up(f"F{i}")
            self.assertEqual(packets[-2].key.vk, 0x6F + i)
            self.assertEqual(packets[-2].key.extra, MARKER)
            self.assertEqual(packets[-1].key.flags & 2, 2)
        backend.scroll(-3)
        self.assertEqual(packets[-1].mouse.data, (-360) & 0xFFFFFFFF)
        data = backend.HookData(vk=0x7C, extra=0)
        self.assertEqual(backend.callback(0, 0x100, ctypes.addressof(data)), 1)
        self.assertEqual(backend.callback(0, 0x100, ctypes.addressof(data)), 1)
        self.assertEqual(len(captured), 1, "autorepeat should not reenter the gesture engine")
        self.assertEqual(backend.callback(0, 0x101, ctypes.addressof(data)), 1)
        self.assertEqual(len(captured), 2)
        data.extra = MARKER
        backend.callback(0, 0x100, ctypes.addressof(data))
        self.assertEqual(len(captured), 2, "own output must be ignored")


if __name__ == "__main__":
    unittest.main()
