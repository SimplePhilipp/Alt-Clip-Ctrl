"""Opt-in Windows desktop integration test. All test input stays isolated.

Source keys carry a private marker and are swallowed by the test hook. Native
wheel events are captured and swallowed by the test's own low-level mouse hook.
Generated output keys are swallowed too. No user window receives test input.
Run with: python -m tests.native_scroll_integration
Exit 77 means no interactive Windows desktop was available, not a passing test.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import ctypes as C
import faulthandler
from pathlib import Path
import sys
import threading
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from altclipctrl.engine import Engine
from altclipctrl.live import LiveInput
from altclipctrl.model import action, defaults
from altclipctrl.platforms import WindowsBackend
from altclipctrl.ui import MainWindow

SOURCE, OUTPUT = 0x49504231, 0x49504232


class ReceiverBackend(WindowsBackend):
    def __init__(self, capture, report):
        super().__init__(capture, report)
        self.wheels, self.coordinates = [], []
        self.input_times, self.receive_times = [], []
        self.source_count = self.output_keys = 0
        W = self.W
        class MouseData(C.Structure):
            _fields_ = [("x", W.LONG), ("y", W.LONG), ("data", W.DWORD), ("flags", W.DWORD), ("time", W.DWORD), ("extra", C.c_size_t)]
        self.MouseData = MouseData

    def callback(self, code, msg, pointer):
        if code >= 0:
            data = C.cast(pointer, C.POINTER(self.HookData)).contents
            if data.extra == SOURCE:
                self.source_count += 1
                if msg in (0x100, 0x104) and data.vk in (self.codes["F21"], self.codes["F23"]):
                    self.input_times.append(time.perf_counter())
                super().callback(code, msg, pointer)
                return 1
            if data.extra == OUTPUT:
                self.output_keys += 1
                return 1
        return self.user.CallNextHookEx(None, code, msg, pointer)

    def foreground_token(self):
        # Only this test's receiver is addressable, independent of user focus.
        return 1

    def program_for_window(self, token, refresh=False):
        return "Receiver.exe"

    def packet(self, packet):
        if packet.type == 1:
            packet.key.extra = OUTPUT
        else:
            packet.mouse.extra = OUTPUT
        super().packet(packet)

    def receive_mouse(self, code, message, pointer):
        if code >= 0:
            data = C.cast(pointer, C.POINTER(self.MouseData)).contents
            if data.extra == OUTPUT:
                if message == 0x020A:
                    self.wheels.append(C.c_short(data.data >> 16).value)
                    self.coordinates.append((data.x, data.y))
                    self.receive_times.append(time.perf_counter())
                return 1
        return self.user.CallNextHookEx(None, code, message, pointer)

    def create_receiver(self):
        self.receiver_ready = threading.Event()
        self.receiver_thread = threading.Thread(target=self.receiver_loop, daemon=True, name="Isolated scroll receiver")
        self.receiver_thread.start()
        if not self.receiver_ready.wait(2) or not getattr(self, "receiver", None):
            raise RuntimeError("Cannot create isolated receiver")

    def receiver_loop(self):
        W = self.W
        self.WindowProc = C.WINFUNCTYPE(C.c_ssize_t, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
        class WindowClass(C.Structure):
            _fields_ = [("style", W.UINT), ("proc", self.WindowProc), ("class_extra", C.c_int),
                ("window_extra", C.c_int), ("instance", W.HINSTANCE), ("icon", W.HANDLE),
                ("cursor", W.HANDLE), ("background", W.HANDLE), ("menu", W.LPCWSTR), ("name", W.LPCWSTR)]
        self.user.DefWindowProcW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
        self.user.DefWindowProcW.restype = C.c_ssize_t
        self.user.RegisterClassW.argtypes = [C.POINTER(WindowClass)]
        self.user.CreateWindowExW.argtypes = [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD,
            C.c_int, C.c_int, C.c_int, C.c_int, W.HWND, W.HANDLE, W.HINSTANCE, C.c_void_p]
        self.user.CreateWindowExW.restype = W.HWND
        self.user.DestroyWindow.argtypes = [W.HWND]
        self.kernel.GetModuleHandleW.argtypes = [W.LPCWSTR]
        self.kernel.GetModuleHandleW.restype = W.HINSTANCE
        def receive(hwnd, message, wp, lp):
            if message == 0x0002:
                self.user.PostQuitMessage(0)
                return 0
            return self.user.DefWindowProcW(hwnd, message, wp, lp)
        self.receiver_callback = self.WindowProc(receive)
        instance = self.kernel.GetModuleHandleW(None)
        name = "AltClipCtrlTestReceiver" + str(os.getpid())
        self.receiver_class = WindowClass(proc=self.receiver_callback, instance=instance, name=name)
        if not self.user.RegisterClassW(C.byref(self.receiver_class)):
            raise RuntimeError("Cannot register isolated receiver")
        self.receiver = self.user.CreateWindowExW(0, name, name, 0, 0, 0, 0, 0, W.HWND(-3), None, instance, None)
        if not self.receiver:
            raise RuntimeError("Cannot create isolated receiver")
        self.mouse_callback_ref = self.HookProc(self.receive_mouse)
        mouse_hook = self.user.SetWindowsHookExW(14, self.mouse_callback_ref, None, 0)
        if not mouse_hook:
            raise RuntimeError("Cannot isolate native wheel output")
        self.receiver_ready.set()
        message = W.MSG()
        try:
            while self.user.GetMessageW(C.byref(message), None, 0, 0) > 0:
                self.user.TranslateMessage(C.byref(message))
                self.user.DispatchMessageW(C.byref(message))
        finally:
            self.user.UnhookWindowsHookEx(mouse_hook)

    def close_receiver(self):
        self.user.PostMessageW(self.receiver, 0x0010, 0, 0)
        self.receiver_thread.join(1)

    def source(self, key, down):
        packet = self.Input(type=1, key=self.Keyboard(vk=self.codes[key], flags=0 if down else 2, extra=SOURCE))
        if self.user.SendInput(1, C.byref(packet), C.sizeof(packet)) != 1:
            raise RuntimeError("Test source injection failed")


def main():
    if sys.platform != "win32":
        return 77
    folder = Path(__file__).resolve().parents[1] / "test-results"
    folder.mkdir(exist_ok=True)
    report_path = folder / "native-scroll-integration.txt"
    with report_path.open("w", buffering=1) as report:
        errors = []
        app = QApplication.instance() or QApplication([])
        window = MainWindow(folder / "native-integration-settings.json", diagnostic=True)
        settings = defaults()
        bindings = settings["profiles"][0]["bindings"]
        bindings["top_left"]["input"], bindings["top_right"]["input"] = "F15", "F13"
        bindings["top_left"]["tap_hold"] = action("dial_scroll", {"reverse": False})
        window.config = settings
        window.refresh()
        backend = ReceiverBackend(window.capture, errors.append)
        if WindowsBackend.foreground_token(backend) is None:
            report.write("SKIP: no interactive Windows desktop; native delivery was not tested.\n")
            window.close()
            return 77
        faulthandler.dump_traceback_later(8, file=report)
        window.backend = backend
        window.live = LiveInput(settings, backend, errors.append)
        window.engine = window.live.engine
        window.accept_input, window.preview_input = True, False
        backend.create_receiver()
        backend.start()
        window.live.start()
        finished = threading.Event()
        expected = [-120 if i % 3 == 0 else 120 for i in range(388)] + [-120] * 6 + [120] * 6
        def produce():
            try:
                backend.source("F15", True)
                time.sleep(.01)
                backend.source("F15", False)
                time.sleep(.01)
                backend.source("F15", True)
                for i in range(388):
                    key = "F21" if i % 3 == 0 else "F23"
                    backend.source(key, True)
                    backend.source(key, False)
                for key in ("F21", "F23"):
                    for _ in range(6):
                        backend.source(key, True)
                    backend.source(key, False)
                for _ in range(8):
                    backend.source("F15", True)  # Held activation repeats are not extra turns.
                backend.source("F15", False)
                backend.key_down("Shift")
                backend.key_up("Shift")
            except Exception as exc:
                errors.append(str(exc))
            finally:
                finished.set()
        producer = threading.Thread(target=produce, daemon=True)
        QTimer.singleShot(20, producer.start)
        heartbeat = QTimer()
        started, ticks = time.monotonic(), []
        def check():
            ticks.append(time.monotonic())
            complete = finished.is_set() and backend.wheels == expected and backend.output_keys == 2
            if (complete and time.monotonic() - started > .2) or time.monotonic() - started > 5:
                good = complete and not errors
                unavailable = not backend.source_count and not errors
                report.write(("SKIP" if unavailable else "PASS" if good else "FAIL") + f": {len(backend.wheels)}/400 native wheel events including overlapping presses, exact directions/order, "
                    f"{backend.output_keys}/2 isolated output keys, {len(ticks)} UI heartbeats. Errors: {errors}\n")
                window.close()
                backend.close_receiver()
                faulthandler.cancel_dump_traceback_later()
                app.exit(77 if unavailable else 0 if good else 1)
        heartbeat.timeout.connect(check)
        heartbeat.start(25)
        result = app.exec()
    print(report_path.read_text().strip())
    return result


if __name__ == "__main__":
    raise SystemExit(main())
