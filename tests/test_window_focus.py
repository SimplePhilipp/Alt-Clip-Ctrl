"""Regression coverage for the real-output/window-switch boundary."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import ctypes
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from altclipctrl.engine import Engine
from altclipctrl.live import LiveInput
from altclipctrl.model import action
from altclipctrl.ui import MainWindow
from tests.test_altclipctrl import FakeBackend, TEMP_ROOT


class FocusBackend(FakeBackend):
    def __init__(self):
        super().__init__()
        self.running = True
        self.window = 10
        self.program = "@self"

    def foreground_token(self):
        return self.window

    def foreground(self):
        return self.program


class WindowFocusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.window = MainWindow(Path(self.folder.name) / "settings.json", diagnostic=True)
        self.window.clock.stop()
        self.backend = FocusBackend()
        self.window.backend = self.backend
        self.window.diagnostic = False
        self.window.engine = Engine(self.window.config, self.backend, self.window.engine_switched, self.window.record_activity)
        b = self.window.active_profile()["bindings"]
        b["top_left"]["tap_hold"] = action("dial_scroll", {"reverse": False})
        self.window.refresh_scope()

    def tearDown(self):
        self.window.close()
        self.folder.cleanup()

    def source(self, signal, down, now):
        self.window.input_event(signal, down, now, self.window.generation,
                                self.window.preview_input, self.backend.window)

    def test_first_button_after_preview_routes_to_live_engine_without_poll_wait(self):
        self.assertTrue(self.window.preview_input)
        old_generation = self.window.generation
        self.backend.window, self.backend.program = 20, "Other.exe"
        self.window.input_event("F13", True, 1, old_generation, True, 20)
        self.assertTrue(self.window.accept_input)
        self.assertFalse(self.window.preview_input)
        self.assertTrue(self.window.engine.states["top_left"].down)
        self.source("F13", False, 1.01)
        self.source("F13", True, 1.04)
        self.source("F23", True, 1.05)
        self.source("F23", False, 1.06)
        self.assertEqual(self.backend.events, [("scroll", 1)])
        self.assertFalse(self.window.history_entries[0]["preview"])

    def test_late_program_name_does_not_reset_live_dial_mode(self):
        self.backend.window, self.backend.program = 20, ""
        with patch("altclipctrl.ui.QApplication.applicationState", return_value=Qt.ApplicationState.ApplicationInactive):
            self.window.refresh_scope()
            self.source("F13", True, 1)
            self.source("F13", False, 1.01)
            self.source("F13", True, 1.04)
            self.backend.program = "Other.exe"
            self.window.refresh_scope()
            self.source("F21", True, 1.05)
            self.source("F21", False, 1.06)
        self.assertEqual(self.backend.events, [("scroll", -1)])

    def test_queued_first_press_survives_focus_notification_before_delivery(self):
        previous_generation = self.window.generation
        self.backend.window, self.backend.program = 20, "Other.exe"
        self.window.refresh_scope()
        self.window.input_event("F13", True, 1, previous_generation, True, 20)
        self.assertTrue(self.window.engine.states["top_left"].down)

    def test_same_program_new_window_clears_previous_mode(self):
        self.backend.window, self.backend.program = 20, "Other.exe"
        self.window.refresh_scope()
        self.source("F13", True, 1)
        self.source("F13", False, 1.01)
        self.source("F13", True, 1.04)
        self.assertIsNotNone(self.window.engine.dial_layer)
        self.backend.window = 30
        self.window.refresh_scope()
        self.assertIsNone(self.window.engine.dial_layer)

    def test_events_for_previous_window_or_old_settings_are_dropped(self):
        old_generation = self.window.generation
        self.backend.window, self.backend.program = 20, "Other.exe"
        self.window.input_event("F13", True, 1, old_generation, False, 10)
        self.assertEqual(self.window.engine.states, {})
        self.window.generation += 1
        self.window.input_event("F13", True, 1, old_generation, False, 20)
        self.assertEqual(self.window.engine.states, {})

    def test_foreground_lookup_failure_pauses_instead_of_escaping_timer(self):
        self.backend.foreground = lambda: (_ for _ in ()).throw(OSError("target vanished"))
        self.window.refresh_scope()
        self.assertFalse(self.window.config["enabled"])
        self.assertIn("target vanished", self.window.status.text())

    def attach_live_view(self):
        self.window.live = LiveInput(self.window.config, self.backend, self.fail)
        self.window.engine = self.window.live.engine

    def test_live_refresh_does_not_clear_a_held_preview_button(self):
        self.attach_live_view()
        self.assertTrue(self.window.preview_input)
        widget = self.window.map.buttons["top_left"]
        self.window.input_event("F13", True, 1, self.window.generation, True)
        for index in range(15):
            # Expiring a flash and refreshing background input must not unset
            # the preview press. Controller repeats must stay a single hold.
            self.window.map.unpulse(widget)
            self.window.drain_live_view()
            self.assertTrue(widget.input_held)
            self.window.input_event("F13", True, 1.1 + index * .06, self.window.generation, True)
        self.window.input_event("F13", False, 2.2, self.window.generation, True)
        self.window.map.unpulse(widget)
        self.window.drain_live_view()
        self.assertFalse(widget.input_held)
        self.assertEqual(self.backend.events, [])

    def test_old_live_press_does_not_relight_a_released_preview_button(self):
        self.attach_live_view()
        self.window.live.lights["F13"] = (True, 1)
        widget = self.window.map.buttons["top_left"]
        self.window.input_event("F13", True, 2, self.window.generation, True)
        self.window.input_event("F13", False, 2.01, self.window.generation, True)
        self.window.map.unpulse(widget)
        self.window.drain_live_view()
        self.assertFalse(widget.input_held)

    def test_live_lighting_still_tracks_press_and_release_outside_preview(self):
        self.attach_live_view()
        self.window.preview_input = False
        widget = self.window.map.buttons["top_left"]
        for down in (True, True, False):
            self.window.live.lights["F13"] = (down, 1)
            self.window.drain_live_view()
            self.assertEqual(widget.input_held, down)


@unittest.skipUnless(sys.platform == "win32", "Windows native output")
class WindowsOutputWorkerTests(unittest.TestCase):
    def backend(self):
        from altclipctrl.platforms import WindowsBackend
        errors = []
        backend = WindowsBackend(lambda *_: False, errors.append)
        backend.foreground_token = lambda: 20
        backend.send_wheel = lambda *_: self.fail("Test wheel output must be replaced by a fake")
        return backend, errors

    def run_worker(self, backend):
        backend.output_thread = threading.Thread(target=backend.output_loop, daemon=True)
        backend.output_thread.start()

    def finish_worker(self, backend):
        backend.output_queue.put(None)
        backend.output_thread.join(1)
        self.assertFalse(backend.output_thread.is_alive())

    def test_wheel_delivery_never_uses_synchronous_sendinput(self):
        backend, errors = self.backend()
        actual = []
        backend.send_wheel = lambda packet: actual.append(ctypes.c_int32(packet.mouse.data).value)
        backend.send_packet = lambda *_: self.fail("Scrolling must not call SendInput")
        self.run_worker(backend)
        for amount in (1, -1, 3, -2):
            backend.scroll(amount)
        self.assertTrue(backend.flush_output())
        self.finish_worker(backend)
        self.assertEqual(actual, [120, -120, 360, -240])
        self.assertEqual(errors, [])

    def test_blocked_keyboard_output_does_not_block_caller(self):
        backend, errors = self.backend()
        entered, release = threading.Event(), threading.Event()
        def block(_):
            entered.set()
            release.wait(1)
        backend.send_packet = block
        self.run_worker(backend)
        before = time.monotonic()
        backend.key_down("F24")
        self.assertLess(time.monotonic() - before, .1)
        self.assertTrue(entered.wait(.5))
        release.set()
        self.assertTrue(backend.flush_output())
        self.finish_worker(backend)

    def test_old_window_scroll_dropped_but_key_cleanup_preserved(self):
        backend, errors = self.backend()
        posted, releases = [], []
        backend.send_wheel = lambda *_: posted.append(True)
        backend.send_packet = lambda packet: releases.append(packet.key.flags)
        backend.output_thread = object()  # Queue jobs before starting the worker.
        backend.key_down("Shift")  # A queued key requires the following wheel to keep order.
        backend.scroll(1)
        backend.key_up("Shift")
        backend.foreground_token = lambda: 30
        self.run_worker(backend)
        self.assertTrue(backend.flush_output())
        self.finish_worker(backend)
        self.assertEqual(posted, [])
        self.assertEqual(releases, [2])

    def test_native_wheel_uses_normal_mouse_stream_and_exact_delta(self):
        backend, errors = self.backend()
        messages = []
        backend.user = type("User", (), {"mouse_event": staticmethod(lambda *args: messages.append(args))})()
        packet = backend.Input(type=0, mouse=backend.Mouse(data=(-240) & 0xFFFFFFFF, flags=0x800, extra=123))
        from altclipctrl.platforms import WindowsBackend
        WindowsBackend.send_wheel(backend, packet)
        self.assertEqual(messages, [(0x800, 0, 0, (-240) & 0xFFFFFFFF, 123)])

    def test_failed_output_still_allows_held_key_cleanup(self):
        backend, errors = self.backend()
        releases = []
        backend.send_packet = lambda packet: releases.append(packet.key.vk)
        self.run_worker(backend)
        backend.output_failed = True
        with self.assertRaises(OSError):
            backend.key_down("Shift")
        backend.key_up("Shift")
        self.assertTrue(backend.flush_output())
        self.finish_worker(backend)
        self.assertEqual(releases, [0xA0])

    def test_wheel_returns_without_native_injection_inside_keyboard_hook(self):
        backend, errors = self.backend()
        posted = []
        backend.output_thread = object()
        backend.send_wheel = lambda packet: posted.append(ctypes.c_int32(packet.mouse.data).value)
        backend.scroll(1)
        self.assertEqual(posted, [])
        self.assertEqual(backend.output_queue.unfinished_tasks, 1)
        self.assertEqual(backend.output_queue.get_nowait()[0].mouse.data, 120)

    def test_wheel_drops_if_its_input_window_is_no_longer_active(self):
        backend, errors = self.backend()
        posted = []
        backend.output_thread = object()
        backend.set_output_focus(20)
        backend.foreground_token = lambda: 30
        backend.scroll(1)
        self.assertEqual(backend.output_queue.unfinished_tasks, 0)


if __name__ == "__main__":
    unittest.main()
