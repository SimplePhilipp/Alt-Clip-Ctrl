"""Live gestures independent of Qt painting, history layout, and UI timers.

The native hook processes input directly under a short lock. The deadline thread
only resolves pending tap/hold timers; dial turns never wait for that thread.
UI feedback is a bounded snapshot, not one queued Qt event per dial pulse.
"""
from collections import deque
import copy
import threading
import time

from .engine import Engine
from .model import MODIFIERS, ROTATIONS


class LiveInput:
    def __init__(self, settings, backend, report):
        self.backend, self.report = backend, report
        self.condition = threading.Condition(threading.RLock())
        self.activities = deque(maxlen=3)
        self.lights = {}
        self.window = None
        self.program = ""
        self.running = self.enabled = False
        self.engine = Engine(copy.deepcopy(settings), backend, self.switched, self.activities.append)
        self.paused = False

    def switched(self, profile_id):
        # Engine already changed its private settings. GUI persistence comes later.
        pass

    def _scope(self, token):
        program = self.backend.program_for_window(token)
        changed, renamed = token != self.window, program != self.program
        if changed:
            self.engine.reset()
            self.lights.clear()
        self.window, self.program = token, program
        if (changed or renamed) and program and program != "@self" and self.engine.settings["auto_switch"]:
            linked = next((p for p in self.engine.settings["profiles"]
                           if program.casefold() in {name.casefold() for name in p["programs"]}), None)
            if linked:
                self.engine.switch(linked["id"])

    def sync_scope(self):
        with self.condition:
            self._scope(self.backend.foreground_token())
            self.condition.notify()

    def capture(self, signal, down, now, token, injected=False):
        """None means own window (preview); bool is the native consume decision."""
        with self.condition:
            if not self.running or not self.enabled or self.paused:
                return False
            if token != self.backend.foreground_token():
                return False
            self._scope(token)
            if self.program == "@self":
                return None
            if not token:
                return False
            matched = next(((slot, b) for slot, b in self.engine.profile["bindings"].items() if b["input"] == signal), None)
            if matched is None:
                if down and signal not in MODIFIERS:
                    modifiers = [m for m in MODIFIERS if self.backend.physical_down(m)]
                    self.engine.track("+".join(modifiers + [signal]))
                elif not down:
                    self.engine.physical_release(signal)
                return False
            slot, binding = matched
            previous = self.lights.get(signal, (False, 0))
            self.lights[signal] = (down, now if down else previous[1])
            if hasattr(self.backend, "set_output_focus"):
                self.backend.set_output_focus(token)
            # Dispatch first; nothing below performs widget or filesystem work.
            # Controller software can overlap key-downs while earlier notches
            # are still down. Every injected turn down is a step; button repeats
            # remain ordinary holds and physical keyboard repeats stay ignored.
            self.engine.event(signal, down, now, repeated=injected and slot in ROTATIONS)
            self.condition.notify()
            return True

    def next_deadline(self):
        deadlines = []
        settings = self.engine.settings
        for slot, state in self.engine.states.items():
            if slot in ROTATIONS:
                continue
            if state.released is not None:
                deadlines.append(state.released + settings["tap_ms"] / 1000)
            if state.down and not state.held and not state.used and not state.override:
                deadlines.append(state.started + settings["hold_ms"] / 1000)
        return min(deadlines) if deadlines else None

    def run(self):
        while True:
            try:
                with self.condition:
                    if not self.running:
                        return
                    token = self.backend.foreground_token()
                    if token != self.window:
                        self._scope(token)
                    if self.enabled and not self.paused and self.program != "@self":
                        if hasattr(self.backend, "set_output_focus"):
                            self.backend.set_output_focus(token)
                        self.engine.poll(time.monotonic())
                    deadline = self.next_deadline() if self.enabled and not self.paused else None
                    timeout = min(.05, max(.0005, deadline - time.monotonic())) if deadline is not None else .05
                    self.condition.wait(timeout)
            except Exception as exc:
                with self.condition:
                    self.enabled = False
                    try:
                        self.engine.reset()
                    except Exception:
                        pass
                    self.lights.clear()
                self.report(str(exc))

    def start(self):
        with self.condition:
            self.enabled = self.engine.settings["enabled"]
            self.running = True
        self.thread = threading.Thread(target=self.run, daemon=True, name="Alt Clip Ctrl gesture deadlines")
        self.thread.start()

    def reset(self):
        with self.condition:
            self.engine.reset()
            self.lights.clear()
            self.window = None
            self.condition.notify()

    def configure(self, settings):
        draft = copy.deepcopy(settings)
        with self.condition:
            self.engine.configure(draft)
            self.enabled = draft["enabled"]
            self.window = None
            self.lights.clear()
            self.activities.clear()
            self.condition.notify()

    def set_paused(self, paused):
        with self.condition:
            if paused != self.paused:
                self.paused = paused
                self.engine.reset()
                self.lights.clear()
                self.condition.notify()

    def snapshot(self):
        with self.condition:
            events = list(self.activities)
            self.activities.clear()
            return events, dict(self.lights), self.engine.profile_id

    def stop(self):
        with self.condition:
            self.running = self.enabled = False
            self.engine.reset()
            self.lights.clear()
            self.condition.notify()
        if hasattr(self, "thread"):
            self.thread.join(.5)
