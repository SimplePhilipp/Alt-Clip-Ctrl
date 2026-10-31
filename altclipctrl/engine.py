"""Deterministic gestures, adapted from Alt Clip Ctrl's tap/hold arbitration.

All times are monotonic seconds supplied by the caller. Repeats never become
second presses. Own output is excluded by the platform adapter, not timing guesses.
"""
from dataclasses import dataclass
from .model import ACTIONS, DIAL_MODES, GESTURE_NAMES, ROTATIONS, action, chord, cycle_id, cycle_list


@dataclass
class State:
    down: bool = False
    second: bool = False
    started: float = 0
    released: float | None = None
    held: bool = False
    used: bool = False
    output: tuple = ()
    dial_action: dict | None = None
    dial_order: int = 0
    dial_pending: dict | None = None
    override: tuple = ()


class Engine:
    def __init__(self, settings, backend, switched=lambda _: None, activity=lambda _: None):
        self.backend, self.switched = backend, switched
        self.activity = activity
        self.states = {}
        self.positions = {}
        self.held_counts = {}
        self.settings = settings
        self.profile_id = settings["active_profile"]
        self.dial_order = 0
        self.last_scroll = None

    @property
    def profile(self):
        return next(p for p in self.settings["profiles"] if p["id"] == self.profile_id)

    def configure(self, settings):
        self.reset()
        self.settings = settings
        self.profile_id = settings["active_profile"]
        self.positions.clear()

    def switch(self, profile_id):
        if profile_id == self.profile_id:
            return
        if not any(p["id"] == profile_id for p in self.settings["profiles"]):
            raise ValueError("Profile no longer exists.")
        self.reset()
        self.profile_id = self.settings["active_profile"] = profile_id
        self.switched(profile_id)

    def reset(self):
        failure = None
        for key in reversed(list(self.held_counts)):
            try:
                if not self.backend.physical_down(key):
                    self.backend.key_up(key)
            except Exception as error:
                failure = error
        self.held_counts.clear()
        self.states.clear()
        self.dial_order = 0
        self.last_scroll = None
        if failure:
            raise failure

    def event(self, signal, down, now, repeated=False):
        slot = next((s for s, b in self.profile["bindings"].items() if b["input"] == signal), None)
        if slot is None:
            return
        binding = self.profile["bindings"][slot]
        state = self.states.setdefault(slot, State())
        if down and (slot in ROTATIONS or slot == "neutral"):
            if self.prepare_dial(now, turning=slot in ROTATIONS):
                return
        if slot in ROTATIONS:
            if down and (not state.down or repeated):
                state.down = True
                if slot.startswith("pressed_"):
                    neutral = self.states.get("neutral")
                    if neutral:
                        neutral.used = True
                        neutral.released = None
                layer = self.dial_layer
                self.invoke(slot, "tap", output_override=self.turn_output(layer, slot) if layer else None,
                            via=self.layer_name(layer) if layer else "", now=now)
            elif not down:
                state.down = False
            return
        if down:
            if state.down:
                return
            # Flush an expired first tap before starting a new independent press.
            layer = self.dial_layer
            override = (layer, layer.dial_action["value"]["neutral"]) if slot == "neutral" and layer and layer is not state and layer.dial_action["kind"] == "dial_modifier" else ()
            second = not override and not state.override and state.released is not None and now - state.released < self.settings["tap_ms"] / 1000
            if state.released is not None and not second:
                state.released = None
                if self.invoke(slot, "tap", state):
                    return
            state.second, state.down, state.started = second, True, now
            state.released, state.held, state.used = None, False, False
            state.override = override
            if second:
                state.held = True
                self.invoke(slot, "tap_hold", state)
        elif state.down:
            state.down = False
            self.release(state)
            if state.override:
                # Temporary neutral is one press, with no second-press gesture to arbitrate.
                if not state.used:
                    self.invoke(slot, "tap", state)
                state.released = None
                return
            if not state.held and not state.used:
                # A late key-up still has hold semantics even if the timer was delayed.
                if now - state.started >= self.settings["hold_ms"] / 1000:
                    self.invoke(slot, "hold", state)
                    self.release(state)
                else:
                    state.released = now

    def poll(self, now):
        for slot, state in list(self.states.items()):
            binding = self.profile["bindings"][slot]
            if slot in ROTATIONS:
                continue
            if state.down and not state.held and not state.used and not state.override and now - state.started >= self.settings["hold_ms"] / 1000:
                state.held = True
                if self.invoke(slot, "hold", state):
                    return
            if state.released is not None and now - state.released >= self.settings["tap_ms"] / 1000:
                state.released = None
                if self.invoke(slot, "tap", state):
                    return

    def release(self, state):
        if state.dial_action:
            self.last_scroll = None
        state.dial_action = None
        state.dial_pending = None
        for other in self.states.values():
            if other.override and other.override[0] is state:
                other.used = True
                other.released = None
        for key in reversed(state.output):
            count = self.held_counts[key] - 1
            if count:
                self.held_counts[key] = count
            else:
                del self.held_counts[key]
                if not self.backend.physical_down(key):
                    self.backend.key_up(key)
        state.output = ()

    @property
    def dial_layer(self):
        return max((s for s in self.states.values() if s.down and s.dial_action), key=lambda s: s.dial_order, default=None)

    def layer_name(self, layer):
        slot = next((slot for slot, state in self.states.items() if state is layer), None)
        return self.profile["bindings"][slot]["name"] if slot else ""

    def prepare_dial(self, now, *, turning=True):
        # A first dial movement can start a held dial mode before the hold timer fires.
        candidates = []
        for slot, state in self.states.items():
            if slot in ROTATIONS or not state.down or state.override:
                continue
            kind = self.profile["bindings"][slot]["hold"]["kind"]
            if turning and state.dial_pending is not None:
                candidates.append((slot, state))
            elif not state.held and (kind in DIAL_MODES or (turning and kind == "hold_dial")):
                candidates.append((slot, state))
        for slot, state in sorted(candidates, key=lambda pair: pair[1].started):
            state.held = True
            state.released = None
            pending = state.dial_pending
            if pending is None and self.profile["bindings"][slot]["hold"]["kind"] == "hold_dial":
                pending = self.profile["bindings"][slot]["hold"]["value"]["with_dial"]
            if pending is not None:
                # Release pan/modifier output before the very first wheel/key
                # packet. The dial mode stays active until the button is released.
                self.release(state)
                if pending["kind"] == "none":
                    self.dial_order += 1
                    state.dial_action, state.dial_order = pending, self.dial_order
            if self.invoke(slot, "tap_hold" if state.second else "hold", state, output_override=pending):
                return True
        return False

    def turn_output(self, layer, slot):
        mode = layer.dial_action
        if mode["kind"] == "none":
            return action()
        if mode["kind"] == "dial_modifier":
            return mode["value"][slot]
        clockwise = slot in ("cw", "pressed_cw")
        reverse = isinstance(mode["value"], dict) and mode["value"].get("reverse", False)
        forward = clockwise != reverse
        return action(("scroll_up" if forward else "scroll_down") if mode["kind"] == "dial_scroll" else
                      ("cycle_next" if forward else "cycle_previous"),
                      {"cycle_id": cycle_id(self.profile, mode)} if mode["kind"] == "dial_cycle" else "")

    def scroll_notches(self, now, direction):
        """Increase distance from the latest turn interval, with no queued ramp.

        The first turn, a reversal, a new dial layer, or a gap of 120 ms uses
        the base amount. Faster turns approach the selected maximum multiplier.
        Use input timestamps so output-worker scheduling cannot alter the speed.
        """
        base = self.settings["scroll_amount"]
        layer = self.dial_layer
        context = (self.profile_id, layer.dial_order if layer else 0, direction)
        previous = self.last_scroll
        self.last_scroll = (now, context)
        if not self.settings.get("scroll_acceleration", False) or previous is None:
            return base
        interval = now - previous[0]
        if previous[1] != context or not 0 < interval < .120:
            return base
        multiplier = 1 + (self.settings.get("scroll_acceleration_factor", 3.0) - 1) * (1 - interval / .120)
        return max(base, int(base * multiplier + .5))

    def execute(self, output, state=None, scroll_notches=None):
        kind, value = output["kind"], output["value"]
        if kind in DIAL_MODES and state is not None:
            self.dial_order += 1
            state.dial_action, state.dial_order = output, self.dial_order
        elif kind == "hold_dial" and state is not None:
            state.dial_pending = value["with_dial"]
            self.execute(value["without_dial"], state)
        elif kind == "shortcut":
            keys = chord(value)
            self.backend.shortcut(keys, set(self.held_counts))
            self.track("+".join(keys), profile=self.profile)
        elif kind == "hold_key" and state is not None:
            acquired = []
            for key in chord(value, held=True):
                if not self.held_counts.get(key) and not self.backend.physical_down(key):
                    self.backend.key_down(key)
                self.held_counts[key] = self.held_counts.get(key, 0) + 1
                acquired.append(key)
                state.output = tuple(acquired)
        elif kind.startswith("cycle_"):
            cycle = cycle_list(self.profile, output)
            tools = cycle["items"]
            position_key = (self.profile_id, cycle["id"])
            direction = 1 if kind == "cycle_next" else -1
            position = self.positions.get(position_key)
            position = (0 if direction > 0 else len(tools) - 1) if position is None else (position + direction) % len(tools)
            keys = chord(tools[position]["shortcut"])
            self.backend.shortcut(keys, set(self.held_counts))
            self.track("+".join(keys), profile=self.profile)
        elif kind.startswith("scroll_"):
            direction = 1 if kind == "scroll_up" else -1
            amount = self.settings["scroll_amount"] if scroll_notches is None else scroll_notches
            self.backend.scroll(direction * amount * (-1 if self.settings["reverse_scroll"] else 1))
        elif kind == "profile":
            self.switch(value)
            return True
        return False

    def invoke(self, slot, gesture, state=None, output_override=None, via="", now=None):
        profile = self.profile
        binding = profile["bindings"][slot]
        output = output_override if output_override is not None else binding[gesture]
        if state and state.override:
            owner, temporary = state.override
            output = temporary if gesture == "tap" and owner is self.dial_layer else action()
            via = self.layer_name(owner)
        kind, value = output["kind"], output["value"]
        amount = None
        if slot in ROTATIONS:
            if kind.startswith("scroll_") and now is not None:
                direction = (1 if kind == "scroll_up" else -1) * (-1 if self.settings["reverse_scroll"] else 1)
                amount = self.scroll_notches(now, direction)
            else:
                self.last_scroll = None
        detail = ACTIONS[kind]
        if kind in DIAL_MODES:
            reverse = isinstance(value, dict) and value.get("reverse", False)
            detail += (" · reversed" if reverse else "") + " · while held"
            if kind == "dial_cycle":
                detail += " · " + cycle_list(profile, output)["name"]
        elif kind in ("shortcut", "hold_key"):
            detail = ("Hold " if kind == "hold_key" else "Send ") + value
        elif kind == "hold_dial":
            plain = value["without_dial"]
            detail = (("Hold " + plain["value"]) if plain["kind"] == "hold_key" else "No action") + " · turn dial to switch"
        elif kind.startswith("scroll_"):
            direction = (1 if kind == "scroll_up" else -1) * (-1 if self.settings["reverse_scroll"] else 1)
            detail = f"Scroll {'up' if direction > 0 else 'down'} · {amount if amount is not None else self.settings['scroll_amount']} notch(es)"
        elif kind == "profile":
            target = next(p for p in self.settings["profiles"] if p["id"] == value)
            detail = "Switch profile → " + target["name"]
        switched = self.execute(output, state, scroll_notches=amount)
        if kind.startswith("cycle_"):
            cycle = cycle_list(profile, output)
            item = cycle["items"][self.positions[(profile["id"], cycle["id"])]]
            detail = f"Cycle → {item['name']} · {item['shortcut']} · {cycle['name']}"
        if via:
            detail += " · via " + via
        self.activity({"slot": slot, "name": binding["name"], "input": binding["input"],
                       "profile": profile["name"], "gesture": "Turn" if slot in ROTATIONS else GESTURE_NAMES[gesture],
                       "action": detail})
        return switched

    def track(self, signal, *, profile=None):
        # Match exact shortcuts. Nonmatching lists retain their last confirmed
        # position; generated output only updates lists in its active profile.
        for tracked_profile in self.settings["profiles"] if profile is None else (profile,):
            for cycle in tracked_profile["cycle_lists"]:
                for i, tool in enumerate(cycle["items"]):
                    if tool["shortcut"] == signal:
                        self.positions[(tracked_profile["id"], cycle["id"])] = i

    def physical_release(self, key):
        # A real key-up must not end an output the controller is still holding.
        if self.held_counts.get(key):
            self.backend.key_down(key)
