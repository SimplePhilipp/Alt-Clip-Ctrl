"""Guided input capture: single button presses, repeated dial pulses, draft only."""
from collections import deque

from .model import MODIFIERS, ROTATIONS, SLOTS, normalize


class QuickAssignment:
    # Record neutral before the pressed rotations, without changing schematic order.
    ORDER = tuple(s for s, _ in SLOTS if s not in ROTATIONS) + ("ccw", "cw", "pressed_ccw", "pressed_cw")
    REPEATS = 3
    WINDOW = 2.0

    def __init__(self, profile):
        self.profile = profile
        self.index = 0
        self.recorded = {}
        self.down = set()
        self.modifiers = set()
        self.pending = None
        self.samples = {}
        self.message = ""

    @property
    def slot(self):
        return self.ORDER[self.index] if self.index < len(self.ORDER) else None

    def clear_step(self):
        self.pending = None
        self.samples.clear()
        self.message = ""

    def event(self, signal, pressed, now):
        if signal in MODIFIERS:
            (self.modifiers.add if pressed else self.modifiers.discard)(signal)
            return
        if not pressed:
            self.down.discard(signal)
            if self.pending == signal:
                self.index += 1
                self.clear_step()
            return
        if signal in self.down or self.pending or self.slot is None:
            return
        self.down.add(signal)
        if self.modifiers:
            self.message = "Release Ctrl, Alt, Shift and Meta, then send a single key."
            return
        try:
            signal = normalize(signal)
        except ValueError as exc:
            self.message = str(exc)
            return
        owner = next((slot for slot, key in self.recorded.items() if key == signal and slot != self.slot), None)
        if owner:
            # A pressed turn may also emit the already-recorded neutral press once.
            if self.slot in ROTATIONS and owner == "neutral":
                return
            self.message = f"{signal} is already recorded for {dict(SLOTS)[owner]}. Send a different key."
            return
        if self.slot in ROTATIONS:
            samples = self.samples.setdefault(signal, deque())
            samples.append(now)
            while samples and now - samples[0] > self.WINDOW:
                samples.popleft()
            self.message = f"{signal} · {len(samples)} of {self.REPEATS} matching turn signals"
            if len(samples) < self.REPEATS:
                return
        self.recorded[self.slot] = signal
        self.pending = signal
        self.message = f"Recorded {signal}. Release to continue."

    def skip(self):
        if self.slot:
            self.index += 1
            self.clear_step()

    def suspend(self):
        if self.pending:
            self.index += 1
        self.down.clear()
        self.modifiers.clear()
        self.clear_step()

    def back(self):
        if self.index:
            self.index -= 1
            self.recorded.pop(self.slot, None)
            self.clear_step()

    def apply(self, settings):
        import copy
        from .model import validate
        result = copy.deepcopy(settings)
        profile = next(p for p in result["profiles"] if p["id"] == self.profile["id"])
        for slot, signal in self.recorded.items():
            profile["bindings"][slot]["input"] = signal
        return validate(result)
