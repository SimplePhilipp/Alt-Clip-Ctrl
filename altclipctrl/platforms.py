"""Small native adapters. Only configured input keys are consumed.

Windows SendInput layout/own-event marking follow the original Input.cs.
Linux grabs only the chosen controller, replaying unrelated events via uinput.
macOS uses one Quartz event tap and tagged CGEvents.
"""
from __future__ import annotations

import ctypes as C
import os
import queue
from pathlib import Path
import select
import subprocess
import sys
import threading
import time

MARKER = 0x43535043


class Backend:
    def __init__(self, capture, report):
        self.capture, self.report = capture, report
        self.running = False

    def shortcut(self, keys, held=frozenset()):
        acquired = []
        try:
            for key in keys:
                if key not in held and not self.physical_down(key):
                    self.key_down(key)
                    acquired.append(key)
        finally:
            failure = None
            for key in reversed(acquired):
                try:
                    self.key_up(key)
                except Exception as error:
                    failure = error
            if failure:
                raise failure

    def physical_down(self, key):
        return False

    def foreground(self):
        return ""

    def foreground_token(self):
        return None

    def supports(self, key):
        return True

    def start(self):
        raise NotImplementedError

    def stop(self):
        self.running = False


class PreviewBackend(Backend):
    """Exercises the gesture engine without sending any native input."""
    def __init__(self):
        super().__init__(lambda *_: False, lambda *_: None)

    def key_down(self, key):
        pass

    def key_up(self, key):
        pass

    def scroll(self, amount):
        pass


class WindowsBackend(Backend):
    def __init__(self, capture, report):
        super().__init__(capture, report)
        from ctypes import wintypes as W
        self.W = W
        self.user = C.WinDLL("user32", use_last_error=True)
        self.kernel = C.WinDLL("kernel32", use_last_error=True)
        self.codes = {chr(i): i for i in range(65, 91)} | {str(i): 48 + i for i in range(10)}
        self.codes.update({f"F{i}": 0x6F + i for i in range(1, 25)})
        self.codes.update(dict(Ctrl=0xA2, Alt=0xA4, Shift=0xA0, Meta=0x5B, Space=32, Tab=9,
            Enter=13, Escape=27, Backspace=8, Delete=46, Insert=45, Home=36, End=35,
            PageUp=33, PageDown=34, Left=37, Right=39, Up=38, Down=40, Minus=189, Plus=187,
            Comma=188, Period=190, Slash=191, Backslash=220, Semicolon=186, Quote=222,
            Grave=192, CapsLock=20))
        self.codes.update({"[": 219, "]": 221})
        self.names = {v: k for k, v in self.codes.items()}
        self.names.update({0xA3: "Ctrl", 0xA5: "Alt", 0xA1: "Shift", 0x5C: "Meta",
                           0x11: "Ctrl", 0x12: "Alt", 0x10: "Shift"})
        ULONG_PTR = C.c_size_t
        class Keyboard(C.Structure):
            _fields_ = [("vk", W.WORD), ("scan", W.WORD), ("flags", W.DWORD),
                        ("time", W.DWORD), ("extra", ULONG_PTR)]
        class Mouse(C.Structure):
            _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("data", W.DWORD),
                        ("flags", W.DWORD), ("time", W.DWORD), ("extra", ULONG_PTR)]
        class Payload(C.Union):
            _fields_ = [("key", Keyboard), ("mouse", Mouse)]
        class Input(C.Structure):
            _anonymous_ = ("payload",)
            _fields_ = [("type", W.DWORD), ("payload", Payload)]
        class HookData(C.Structure):
            _fields_ = [("vk", W.DWORD), ("scan", W.DWORD), ("flags", W.DWORD),
                        ("time", W.DWORD), ("extra", ULONG_PTR)]
        self.Input, self.Keyboard, self.Mouse, self.HookData = Input, Keyboard, Mouse, HookData
        self.HookProc = C.WINFUNCTYPE(C.c_ssize_t, C.c_int, W.WPARAM, W.LPARAM)
        self.user.SetWindowsHookExW.argtypes = [C.c_int, self.HookProc, W.HINSTANCE, W.DWORD]
        self.user.SetWindowsHookExW.restype = W.HANDLE
        self.user.CallNextHookEx.argtypes = [W.HANDLE, C.c_int, W.WPARAM, W.LPARAM]
        self.user.CallNextHookEx.restype = C.c_ssize_t
        self.user.UnhookWindowsHookEx.argtypes = [W.HANDLE]
        self.user.SendInput.argtypes = [W.UINT, C.POINTER(Input), C.c_int]
        self.user.mouse_event.argtypes = [W.DWORD, W.DWORD, W.DWORD, W.DWORD, C.c_size_t]
        self.user.mouse_event.restype = None
        self.user.GetForegroundWindow.restype = W.HWND
        self.user.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
        self.user.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
        self.kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        self.kernel.OpenProcess.restype = W.HANDLE
        self.kernel.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
        self.kernel.CloseHandle.argtypes = [W.HANDLE]
        self.user.PostThreadMessageW.argtypes = [W.DWORD, W.UINT, W.WPARAM, W.LPARAM]
        self.thread_id = 0
        self.blocked = set()
        self.physical_keys = set()
        self.ready = threading.Event()
        self.error = None
        self.output_queue = queue.Queue()
        self.output_thread = None
        self.output_failed = False
        self._program_window = None
        self._program_name = ""
        self.output_context = threading.local()

    def packet(self, packet):
        release = packet.type == 1 and bool(packet.key.flags & 2)
        if self.output_failed and not release:
            raise OSError("Windows output is paused. Enable the driver to retry.")
        if self.output_thread is None:
            raise OSError("The Windows output worker is not running.")
        focus = getattr(self.output_context, "focus", self.foreground_token())
        if not release and focus != self.foreground_token():
            return
        if not release and focus != self.foreground_token():
            return
        # Native wheel injection must happen after the keyboard hook returns.
        # The worker never waits for Qt and preserves the exact input order.
        self.output_queue.put((packet, focus, None))

    def set_output_focus(self, token):
        self.output_context.focus = token

    def send_packet(self, packet):
        if self.user.SendInput(1, C.byref(packet), C.sizeof(packet)) != 1:
            raise OSError("Windows blocked the output. Run the target app and Alt Clip Ctrl at the same privilege level.")

    def send_wheel(self, packet):
        # Use the OS mouse-input stream, including its normal routing and timing.
        # Posting WM_MOUSEWHEEL directly is not equivalent to a real wheel event.
        self.user.mouse_event(0x0800, 0, 0, packet.mouse.data, packet.mouse.extra)

    def output_loop(self):
        while True:
            job = self.output_queue.get()
            try:
                if job is None:
                    return
                packet, focus, target = job
                release = packet.type == 1 and bool(packet.key.flags & 2)
                if self.output_failed and not release:
                    continue
                if not release and focus != self.foreground_token():
                    continue
                if packet.type == 0:
                    self.send_wheel(packet)
                else:
                    self.send_packet(packet)
            except Exception as error:
                self.output_failed = True
                self.report(str(error))
            finally:
                self.output_queue.task_done()

    def flush_output(self, timeout=1.0):
        deadline = time.monotonic() + timeout
        while self.output_queue.unfinished_tasks and time.monotonic() < deadline:
            threading.Event().wait(.005)
        return self.output_queue.unfinished_tasks == 0

    def key(self, name, down):
        vk = self.codes[name]
        extended = name in {"Meta", "Left", "Right", "Up", "Down", "Insert", "Delete", "Home", "End", "PageUp", "PageDown"}
        self.packet(self.Input(type=1, key=self.Keyboard(vk=vk, flags=(0 if down else 2) | int(extended), extra=MARKER)))

    def key_down(self, name):
        self.key(name, True)

    def key_up(self, name):
        self.key(name, False)

    def physical_down(self, key):
        family = {"Ctrl": {0x11, 0xA2, 0xA3}, "Alt": {0x12, 0xA4, 0xA5},
                  "Shift": {0x10, 0xA0, 0xA1}, "Meta": {0x5B, 0x5C}}
        return bool(self.physical_keys & family.get(key, {self.codes[key]}))

    def scroll(self, amount):
        self.packet(self.Input(type=0, mouse=self.Mouse(data=(amount * 120) & 0xFFFFFFFF, flags=0x800, extra=MARKER)))

    def foreground(self):
        return self.program_for_window(self.foreground_token(), refresh=True)

    def program_for_window(self, window, refresh=False):
        if not refresh and window == self._program_window:
            return self._program_name
        pid = self.W.DWORD()
        self.user.GetWindowThreadProcessId(window, C.byref(pid))
        name = ""
        if pid.value == os.getpid():
            name = "@self"
        elif pid.value:
            handle = self.kernel.OpenProcess(0x1000, False, pid.value)
            if handle:
                try:
                    size = self.W.DWORD(32768)
                    buffer = C.create_unicode_buffer(size.value)
                    if self.kernel.QueryFullProcessImageNameW(handle, 0, buffer, C.byref(size)):
                        name = Path(buffer.value).name
                finally:
                    self.kernel.CloseHandle(handle)
        self._program_window, self._program_name = window, name
        return name

    def foreground_token(self):
        return self.user.GetForegroundWindow()

    def callback(self, code, msg, address):
        if code >= 0:
            data = C.cast(address, C.POINTER(self.HookData)).contents
            if data.extra != MARKER:
                name = self.names.get(data.vk)
                down = msg in (0x100, 0x104)
                if name:
                    try:
                        injected = bool(data.flags & 0x10)
                        if down and data.vk in self.blocked and not injected:
                            return 1
                        consume = self.capture(name, down, time.monotonic(), injected)
                        if down and consume:
                            self.blocked.add(data.vk)
                        if not down and data.vk in self.blocked:
                            self.blocked.remove(data.vk)
                            consume = True
                        if consume:
                            return 1
                        if down:
                            self.physical_keys.add(data.vk)
                        else:
                            self.physical_keys.discard(data.vk)
                    except Exception as error:
                        self.report(str(error))
        return self.user.CallNextHookEx(None, code, msg, address)

    def run(self):
        self.thread_id = self.kernel.GetCurrentThreadId()
        self.callback_ref = self.HookProc(self.callback)
        hook = self.user.SetWindowsHookExW(13, self.callback_ref, None, 0)
        if not hook:
            self.error = OSError(C.get_last_error(), "Cannot start the Windows input listener.")
            self.ready.set()
            return
        self.running = True
        self.physical_keys = {vk for vk in self.names if self.user.GetAsyncKeyState(vk) & 0x8000}
        message = self.W.MSG()
        # Force the thread's message queue to exist before stop() can post WM_QUIT.
        self.user.PeekMessageW(C.byref(message), None, 0, 0, 0)
        self.ready.set()
        try:
            while self.user.GetMessageW(C.byref(message), None, 0, 0) > 0:
                self.user.TranslateMessage(C.byref(message))
                self.user.DispatchMessageW(C.byref(message))
        finally:
            self.user.UnhookWindowsHookEx(hook)
            self.running = False

    def start(self):
        self.output_failed = False
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        if not self.ready.wait(3):
            raise RuntimeError("The input listener did not start.")
        if self.error:
            raise self.error
        self.output_thread = threading.Thread(target=self.output_loop, daemon=True, name="Alt Clip Ctrl Windows output")
        self.output_thread.start()

    def stop(self):
        if self.output_thread:
            self.output_queue.put(None)
            self.output_thread.join(.5)
            self.output_thread = None
        if self.running:
            self.user.PostThreadMessageW(self.thread_id, 0x12, 0, 0)
            self.thread.join(2)
        self.running = False


class LinuxBackend(Backend):
    def __init__(self, capture, report, device=""):
        super().__init__(capture, report)
        import evdev
        self.evdev = evdev
        self.path = device
        special = {"Ctrl": "LEFTCTRL", "Alt": "LEFTALT", "Shift": "LEFTSHIFT", "Meta": "LEFTMETA",
            "Escape": "ESC", "PageUp": "PAGEUP", "PageDown": "PAGEDOWN", "Plus": "EQUAL",
            "Minus": "MINUS", "[": "LEFTBRACE", "]": "RIGHTBRACE", "Grave": "GRAVE",
            "Quote": "APOSTROPHE", "Backslash": "BACKSLASH"}
        from .model import KEYS, MODIFIERS
        self.codes = {k: getattr(evdev.ecodes, "KEY_" + special.get(k, k.upper())) for k in KEYS + list(MODIFIERS)}
        self.names = {v: k for k, v in self.codes.items()}
        self.device = self.virtual = None

    @staticmethod
    def devices():
        import evdev
        result = []
        for path in evdev.list_devices():
            try:
                with evdev.InputDevice(path) as device:
                    if evdev.ecodes.EV_KEY in device.capabilities():
                        result.append((path, device.name))
            except OSError:
                pass
        return result

    def start(self):
        if not self.path:
            raise RuntimeError("Choose your controller in Options → Device. Linux needs access to that device and /dev/uinput.")
        self.device = self.evdev.InputDevice(self.path)
        try:
            capabilities = self.device.capabilities()
            capabilities.pop(self.evdev.ecodes.EV_SYN, None)
            capabilities.pop(self.evdev.ecodes.EV_FF, None)
            capabilities[self.evdev.ecodes.EV_KEY] = sorted(set(capabilities.get(self.evdev.ecodes.EV_KEY, [])) | set(self.codes.values()))
            relatives = set(capabilities.get(self.evdev.ecodes.EV_REL, []))
            relatives.add(self.evdev.ecodes.REL_WHEEL)
            capabilities[self.evdev.ecodes.EV_REL] = sorted(relatives)
            self.virtual = self.evdev.UInput(capabilities, name="Alt Clip Ctrl output")
            self.device.grab()
        except Exception:
            self.stop()
            raise
        self.running = True
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        blocked = set()
        try:
            while self.running:
                if not select.select([self.device.fd], [], [], .1)[0]:
                    continue
                for event in self.device.read():
                    consume = False
                    if event.type == self.evdev.ecodes.EV_KEY and event.code in self.names:
                        consume = event.value == 2 and event.code in blocked
                        if not consume:
                            consume = self.capture(self.names[event.code], event.value != 0, time.monotonic())
                        if consume and event.value:
                            blocked.add(event.code)
                        if event.value == 0 and event.code in blocked:
                            blocked.remove(event.code)
                            consume = True
                    if not consume:
                        self.virtual.write_event(event)
        except Exception as error:
            if self.running:
                self.report(f"Controller disconnected: {error}")
        finally:
            self.running = False

    def key_down(self, name):
        self.virtual.write(self.evdev.ecodes.EV_KEY, self.codes[name], 1)
        self.virtual.syn()

    def key_up(self, name):
        if self.virtual:
            self.virtual.write(self.evdev.ecodes.EV_KEY, self.codes[name], 0)
            self.virtual.syn()

    def scroll(self, amount):
        self.virtual.write(self.evdev.ecodes.EV_REL, self.evdev.ecodes.REL_WHEEL, amount)
        self.virtual.syn()

    def foreground(self):
        # X11/EWMH works without another dependency. Wayland has no universal focus API.
        if os.environ.get("XDG_SESSION_TYPE") == "wayland":
            return ""
        try:
            window = subprocess.check_output(["xprop", "-root", "_NET_ACTIVE_WINDOW"], timeout=.3, text=True).split()[-1]
            prop = subprocess.check_output(["xprop", "-id", window, "WM_CLASS"], timeout=.3, text=True)
            return prop.split('"')[1] if '"' in prop else ""
        except (OSError, subprocess.SubprocessError):
            return ""

    def stop(self):
        self.running = False
        if hasattr(self, "thread") and self.thread is not threading.current_thread():
            self.thread.join(1)
        if self.device:
            try:
                self.device.ungrab()
            except OSError:
                pass
            self.device.close()
            self.device = None
        if self.virtual:
            self.virtual.close()
            self.virtual = None


class MacBackend(Backend):
    def __init__(self, capture, report):
        super().__init__(capture, report)
        import Quartz as Q
        self.Q = Q
        letters = dict(zip("ASDFHGZXCVBQWERYT123465=97-80]OU[IPLJ'K;\\,/.`NM", [
            0,1,2,3,4,5,6,7,8,9,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,37,38,39,40,41,42,43,44,47,50,45,46]))
        self.codes = {k: v for k, v in letters.items() if k.isalnum() or k in "[]"}
        self.codes.update(dict(Plus=24, Minus=27, Quote=39, Semicolon=41, Backslash=42,
            Comma=43, Slash=44, Period=47, Grave=50, Enter=36, Tab=48, Space=49,
            Backspace=51, Escape=53, Meta=55, Shift=56, CapsLock=57, Alt=58, Ctrl=59,
            Insert=114, Home=115, PageUp=116, Delete=117, End=119, PageDown=121,
            Left=123, Right=124, Down=125, Up=126))
        self.codes.update({f"F{i+1}": code for i, code in enumerate([
            122,120,99,118,96,97,98,100,101,109,103,111,105,107,113,106,64,79,80,90])})
        self.names = {v: k for k, v in self.codes.items()}
        self.names.update({54: "Meta", 60: "Shift", 61: "Alt", 62: "Ctrl"})
        self.flags = {"Meta": Q.kCGEventFlagMaskCommand, "Shift": Q.kCGEventFlagMaskShift,
                      "Alt": Q.kCGEventFlagMaskAlternate, "Ctrl": Q.kCGEventFlagMaskControl}
        self.active_keys = set()
        self.tap = self.loop = None
        self.blocked = set()

    def key(self, name, down):
        Q = self.Q
        if down:
            self.active_keys.add(name)
        else:
            self.active_keys.discard(name)
        event = Q.CGEventCreateKeyboardEvent(None, self.codes.get(name, 0), down)
        flags = 0
        for key in self.active_keys:
            flags |= self.flags.get(key, 0)
        if name.startswith("F") and int(name[1:]) >= 21:
            # AppKit defines F21–F35 function characters; Quartz has no F21+ virtual keycodes.
            Q.CGEventKeyboardSetUnicodeString(event, 1, chr(0xF703 + int(name[1:])))
            flags |= Q.kCGEventFlagMaskSecondaryFn
        Q.CGEventSetFlags(event, flags)
        Q.CGEventSetIntegerValueField(event, Q.kCGEventSourceUserData, MARKER)
        Q.CGEventPost(Q.kCGHIDEventTap, event)

    def key_down(self, name):
        self.key(name, True)

    def key_up(self, name):
        self.key(name, False)

    def scroll(self, amount):
        Q = self.Q
        event = Q.CGEventCreateScrollWheelEvent(None, Q.kCGScrollEventUnitLine, 1, amount)
        Q.CGEventSetIntegerValueField(event, Q.kCGEventSourceUserData, MARKER)
        Q.CGEventPost(Q.kCGHIDEventTap, event)

    def foreground(self):
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return "@self" if app.processIdentifier() == os.getpid() else str(app.bundleIdentifier() or app.localizedName())

    def intercept(self, proxy, kind, event, context):
        Q = self.Q
        if kind in (Q.kCGEventTapDisabledByTimeout, Q.kCGEventTapDisabledByUserInput):
            Q.CGEventTapEnable(self.tap, True)
            return event
        if Q.CGEventGetIntegerValueField(event, Q.kCGEventSourceUserData) == MARKER:
            return event
        try:
            code = Q.CGEventGetIntegerValueField(event, Q.kCGKeyboardEventKeycode)
            name = self.names.get(code)
            _, chars = Q.CGEventKeyboardGetUnicodeString(event, 8, None, None)
            if chars and 0xF718 <= ord(chars[0]) <= 0xF71B:
                name = f"F{ord(chars[0]) - 0xF703}"
            down = kind == Q.kCGEventKeyDown
            if kind == Q.kCGEventFlagsChanged:
                down = bool(Q.CGEventGetFlags(event) & self.flags.get(name, 0))
            if name:
                if down and name in self.blocked:
                    return None
                consume = self.capture(name, down, time.monotonic())
                if consume and down:
                    self.blocked.add(name)
                if not down and name in self.blocked:
                    self.blocked.remove(name)
                    consume = True
                if consume:
                    return None
        except Exception as error:
            self.report(str(error))
        return event

    def start(self):
        Q = self.Q
        mask = sum(1 << k for k in (Q.kCGEventKeyDown, Q.kCGEventKeyUp, Q.kCGEventFlagsChanged))
        self.callback_ref = self.intercept
        self.tap = Q.CGEventTapCreate(Q.kCGSessionEventTap, Q.kCGHeadInsertEventTap, 0, mask, self.callback_ref, None)
        if not self.tap:
            raise RuntimeError("Allow Alt Clip Ctrl in macOS Privacy & Security → Accessibility and Input Monitoring, then restart.")
        self.running = True
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        Q = self.Q
        self.loop = Q.CFRunLoopGetCurrent()
        source = Q.CFMachPortCreateRunLoopSource(None, self.tap, 0)
        Q.CFRunLoopAddSource(self.loop, source, Q.kCFRunLoopCommonModes)
        Q.CGEventTapEnable(self.tap, True)
        Q.CFRunLoopRun()

    def stop(self):
        self.running = False
        if self.tap:
            self.Q.CGEventTapEnable(self.tap, False)
            self.Q.CFMachPortInvalidate(self.tap)
        if self.loop:
            self.Q.CFRunLoopStop(self.loop)
        if hasattr(self, "thread"):
            self.thread.join(1)


def create_backend(capture, report, device=""):
    if sys.platform == "win32":
        return WindowsBackend(capture, report)
    if sys.platform == "darwin":
        return MacBackend(capture, report)
    if sys.platform.startswith("linux"):
        return LinuxBackend(capture, report, device)
    raise RuntimeError("Alt Clip Ctrl supports Windows, Linux and macOS.")
