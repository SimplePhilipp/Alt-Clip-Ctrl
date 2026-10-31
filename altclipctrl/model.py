"""Portable settings and shortcut validation. No OS hooks or UI imports."""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import tempfile
import uuid
import xml.etree.ElementTree as ET

SLOTS = (
    ("top_left", "Top left"), ("top_middle", "Top middle"), ("top_right", "Top right"),
    ("left_upper", "Left upper"), ("left_lower", "Left lower"),
    ("right_upper", "Right upper"), ("right_lower", "Right lower"),
    ("pressed_ccw", "Pressed counterclockwise"), ("ccw", "Counterclockwise"),
    ("neutral", "Pressed neutral"), ("cw", "Clockwise"), ("pressed_cw", "Pressed clockwise"),
)
ROTATIONS = {"pressed_ccw", "ccw", "cw", "pressed_cw"}
DIAL_SLOTS = tuple(slot for slot, _ in SLOTS if slot in ROTATIONS or slot == "neutral")
DIAL_MODES = {"dial_scroll", "dial_cycle", "dial_modifier"}
DIRECTIONAL_ACTIONS = {"scroll_up", "scroll_down", "cycle_next", "cycle_previous"}
GESTURES = ("tap", "hold", "tap_hold")
GESTURE_NAMES = {"tap": "Tap  −", "hold": "Hold  _", "tap_hold": "Tap then hold  −_"}
ACTIONS = {
    "none": "No action", "shortcut": "Key / shortcut", "hold_key": "Hold a key",
    "cycle_next": "Cycle list · next", "cycle_previous": "Cycle list · previous",
    "scroll_up": "Scroll up", "scroll_down": "Scroll down", "profile": "Switch profile",
    "dial_scroll": "Dial scrolling", "dial_cycle": "Dial cycling", "dial_modifier": "Dial modifier",
    "hold_dial": "Hold + dial",
}
MODIFIERS = ("Ctrl", "Alt", "Shift", "Meta")
KEYS = [f"F{i}" for i in range(1, 25)] + list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") + [
    "Space", "Tab", "Enter", "Escape", "Backspace", "Delete", "Insert", "Home", "End",
    "PageUp", "PageDown", "Left", "Right", "Up", "Down", "[", "]", "Minus", "Plus",
    "Comma", "Period", "Slash", "Backslash", "Semicolon", "Quote", "Grave", "CapsLock",
]
ALIASES = {k.casefold(): k for k in KEYS + list(MODIFIERS)}
ALIASES.update({"control": "Ctrl", "command": "Meta", "cmd": "Meta", "win": "Meta",
                "windows": "Meta", "super": "Meta", "option": "Alt", "esc": "Escape",
                "return": "Enter", "oemopenbrackets": "[", "oemclosebrackets": "]",
                "oemplus": "Plus", "oemminus": "Minus", "-": "Minus"})


def chord(text: str, *, held: bool = False) -> tuple[str, ...]:
    tokens = []
    for part in text.strip().split("+"):
        token = ALIASES.get(part.strip().casefold())
        if token is None:
            raise ValueError(f"Unknown key ‘{part}’. Use a key name such as F24, Space or Plus.")
        if token in tokens:
            raise ValueError("A shortcut cannot repeat the same key.")
        tokens.append(token)
    base = [t for t in tokens if t not in MODIFIERS]
    if len(base) > 1 or (not base and not held):
        raise ValueError("Choose one key, optionally with Ctrl, Alt, Shift or Meta.")
    return tuple(m for m in MODIFIERS if m in tokens) + tuple(base)


def normalize(text: str, *, held: bool = False) -> str:
    return "+".join(chord(text, held=held))


def action(kind="none", value=""):
    return {"kind": kind, "value": value}


def allowed_actions(held):
    excluded = {"shortcut"} | DIRECTIONAL_ACTIONS if held else {"hold_key", "hold_dial"} | DIAL_MODES
    return {key: text for key, text in ACTIONS.items() if key not in excluded}


def dial_map(profile=None):
    return {slot: copy.deepcopy(profile["bindings"][slot]["tap"]) if profile else action() for slot in DIAL_SLOTS}


def references_profile(output, profile_id):
    return (output["kind"] == "profile" and output["value"] == profile_id) or (
        output["kind"] in ("dial_modifier", "hold_dial") and any(references_profile(item, profile_id) for item in output["value"].values()))


def cycle_id(profile, output):
    value = output["value"]
    return value.get("cycle_id", profile["cycle_lists"][0]["id"]) if isinstance(value, dict) else profile["cycle_lists"][0]["id"]


def cycle_list(profile, output):
    selected = cycle_id(profile, output)
    return next(c for c in profile["cycle_lists"] if c["id"] == selected)


def references_cycle(output, selected, default_id):
    if output["kind"] in ("cycle_next", "cycle_previous", "dial_cycle"):
        value = output["value"]
        return (value.get("cycle_id", default_id) if isinstance(value, dict) else default_id) == selected
    return output["kind"] in ("dial_modifier", "hold_dial") and any(references_cycle(item, selected, default_id) for item in output["value"].values())


def new_cycle_list(name="New list", items=None):
    return {"id": uuid.uuid4().hex, "name": name,
            "items": copy.deepcopy(items) if items is not None else [{"name": "Pen", "shortcut": "B"}, {"name": "Eraser", "shortcut": "E"}]}


def validate_output(output, ids, *, held=False, cycles=None):
    kind, value = output["kind"], output["value"]
    if kind not in allowed_actions(held):
        raise ValueError("Choose a dial mode or Hold a key for held gestures; directional actions and Key / shortcut belong to Tap.")
    if kind == "hold_dial":
        if not isinstance(value, dict) or set(value) != {"without_dial", "with_dial"}:
            raise ValueError("Choose both the without-dial and with-dial actions.")
        if any(not isinstance(part, dict) for part in value.values()):
            raise ValueError("Choose valid actions for both without dial and with dial.")
        if value["without_dial"].get("kind") not in ("none", "hold_key") or value["with_dial"].get("kind") not in DIAL_MODES | {"none"}:
            raise ValueError("Without dial: choose No action or Hold a key. With dial: choose No action or a dial mode.")
        for part in value.values():
            validate_output(part, ids, held=True, cycles=cycles)
    if kind in ("shortcut", "hold_key"):
        output["value"] = normalize(value, held=kind == "hold_key")
    if kind == "profile" and value not in ids:
        raise ValueError("Choose an existing destination profile.")
    if kind in ("dial_scroll", "dial_cycle"):
        if value == "":
            output["value"] = {"reverse": False}
        elif not isinstance(value, dict) or type(value.get("reverse")) is not bool:
            raise ValueError("Choose a valid direction for the dial action.")
    if kind in ("cycle_next", "cycle_previous", "dial_cycle"):
        value = output["value"]
        if value == "":
            value = output["value"] = {}
        if not isinstance(value, dict):
            raise ValueError("Choose a valid cycle list.")
        if cycles:
            value.setdefault("cycle_id", cycles[0]["id"])
            if type(value["cycle_id"]) is not str or value["cycle_id"] not in {c["id"] for c in cycles}:
                raise ValueError("Choose an existing cycle list in this profile.")
    if kind == "dial_modifier":
        if not isinstance(value, dict) or set(value) != set(DIAL_SLOTS):
            raise ValueError("Set all five temporary dial controls.")
        for temporary in value.values():
            validate_output(temporary, ids, cycles=cycles)


def new_profile(name="Default"):
    bindings = {}
    for i, (slot, label) in enumerate(SLOTS):
        bindings[slot] = {"name": label, "input": f"F{13 + i}",
                          "tap": action(), "hold": action(), "tap_hold": action()}
    cycle = new_cycle_list("Default")
    cycle["id"] = "default"
    return {"id": uuid.uuid4().hex, "name": name, "programs": [], "bindings": bindings,
            "cycle_lists": [cycle]}


def defaults():
    profile = new_profile()
    return {"version": 2, "active_profile": profile["id"], "enabled": True,
            "auto_switch": True, "tap_ms": 100, "hold_ms": 300, "scroll_amount": 1,
            "reverse_scroll": False, "scroll_acceleration": False,
            "scroll_acceleration_factor": 3.0, "linux_device": "", "profiles": [profile]}


def validate(settings):
    if settings.get("version") == 1:
        for profile in settings["profiles"]:
            if "cycle_lists" not in profile:
                profile["cycle_lists"] = [{"id": "default", "name": "Default", "items": profile.pop("cycle")}]
        settings["version"] = 2
    if settings.get("version") != 2:
        raise ValueError("This settings version is not supported.")
    profiles = settings["profiles"]
    if not 1 <= len(profiles) <= 64:
        raise ValueError("Keep between 1 and 64 profiles.")
    ids = {p["id"] for p in profiles}
    if len(ids) != len(profiles) or settings["active_profile"] not in ids:
        raise ValueError("Choose an existing profile. Profile IDs must be unique.")
    names, programs = set(), set()
    for profile in profiles:
        name = profile["name"].strip()
        if not name or name.casefold() in names:
            raise ValueError("Give each profile a unique, nonempty name.")
        profile["name"] = name
        names.add(name.casefold())
        cycles = profile["cycle_lists"]
        if not 1 <= len(cycles) <= 64:
            raise ValueError("Each profile needs between 1 and 64 cycle lists.")
        cycle_ids, cycle_names = set(), set()
        for cycle in cycles:
            cycle_name = cycle["name"].strip()
            if type(cycle["id"]) is not str or not cycle["id"] or cycle["id"] in cycle_ids or not cycle_name or cycle_name.casefold() in cycle_names:
                raise ValueError("Give cycle lists unique IDs and nonempty, different names within each profile.")
            cycle["name"] = cycle_name
            cycle_ids.add(cycle["id"])
            cycle_names.add(cycle_name.casefold())
            if not 1 <= len(cycle["items"]) <= 64:
                raise ValueError("A cycle list needs between 1 and 64 entries.")
            shortcuts = set()
            for item in cycle["items"]:
                item["shortcut"] = normalize(item["shortcut"])
                if not item["name"].strip() or item["shortcut"] in shortcuts:
                    raise ValueError("Cycle entries need names and different shortcuts within each list.")
                shortcuts.add(item["shortcut"])
        for program in profile["programs"]:
            if not program.strip() or program.strip().casefold() in programs:
                raise ValueError("Each program can be linked to only one profile.")
            programs.add(program.strip().casefold())
        if set(profile["bindings"]) != {s for s, _ in SLOTS}:
            raise ValueError("Each profile needs all twelve device signals.")
        inputs = set()
        for slot, binding in profile["bindings"].items():
            if not binding["name"].strip():
                raise ValueError("Each button needs a name for its tooltip.")
            signal = normalize(binding["input"])
            if len(chord(signal)) != 1 or signal in MODIFIERS:
                raise ValueError("Device inputs must be single keys, without modifiers.")
            if signal in inputs:
                raise ValueError(f"‘{signal}’ is assigned to two controls in {name}.")
            inputs.add(signal)
            binding["input"] = signal
            for gesture in GESTURES:
                output = binding[gesture]
                validate_output(output, ids, held=gesture != "tap" and slot not in ROTATIONS, cycles=cycles)
    for field in ("tap_ms", "hold_ms"):
        if type(settings[field]) is not int or not 20 <= settings[field] <= 2000:
            raise ValueError("Gesture timings must be between 20 and 2000 ms.")
    if type(settings["scroll_amount"]) is not int or not 1 <= settings["scroll_amount"] <= 20:
        raise ValueError("Scroll amount must be between 1 and 20 notches.")
    # Existing settings keep their fixed step size until acceleration is enabled.
    settings.setdefault("scroll_acceleration", False)
    settings.setdefault("scroll_acceleration_factor", 3.0)
    if type(settings["scroll_acceleration"]) is not bool:
        raise ValueError("Scroll acceleration must be enabled or disabled.")
    factor = settings["scroll_acceleration_factor"]
    if type(factor) not in (int, float) or not math.isfinite(factor) or not 1 <= factor <= 10:
        raise ValueError("Scroll acceleration factor must be between 1 and 10.")
    return settings


def load(path):
    settings = json.loads(Path(path).read_text(encoding="utf-8"))
    # Preserve existing key assignments as held output in the two held gestures.
    for profile in settings.get("profiles", []):
        for binding in profile.get("bindings", {}).values():
            for gesture in ("hold", "tap_hold"):
                if binding.get(gesture, {}).get("kind") == "shortcut":
                    binding[gesture]["kind"] = "hold_key"
                if binding.get(gesture, {}).get("kind") in DIRECTIONAL_ACTIONS:
                    kind = binding[gesture]["kind"]
                    binding[gesture] = action("dial_scroll" if kind.startswith("scroll_") else "dial_cycle",
                                              {"reverse": kind in ("scroll_down", "cycle_previous")})
    return validate(settings)


def save(path, settings):
    validate(settings)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(settings, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def import_legacy(path, settings):
    """Port old actions/cycles, never the ambiguous Alt/Ctrl/Shift inputs."""
    raw = Path(path).read_bytes()
    if len(raw) > 2_000_000 or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("Unsupported XML file.")
    root = ET.fromstring(raw)
    if root.tag != "AppSettings":
        raise ValueError("Choose an Alt Clip Ctrl settings XML file.")
    result = copy.deepcopy(settings)
    notes = []
    for old in root.findall("./Modifiers/ModifierBinding"):
        modifier = old.findtext("Modifier", "Profile")
        name, suffix = f"Imported · {modifier}", 2
        while any(p["name"].casefold() == name.casefold() for p in result["profiles"]):
            name, suffix = f"Imported · {modifier} {suffix}", suffix + 1
        profile = new_profile(name)
        tools = old.findall("./Tools/ToolBinding") or root.findall("./Tools/ToolBinding")
        if tools:
            profile["cycle_lists"][0]["items"] = [{"name": t.findtext("Name", "Tool"),
                                  "shortcut": t.findtext("Shortcut", "B")} for t in tools]
        def convert(value):
            if value in ("Scroll up", "WheelUp"):
                return action("scroll_up")
            if value in ("Scroll down", "WheelDown"):
                return action("scroll_down")
            return action() if value in (None, "", "No action") else action("shortcut", value)
        b = profile["bindings"]
        b["neutral"]["tap"] = convert(old.findtext("TapOutput"))
        for mode_field, output_field, gesture in (("HoldMode", "HoldOutput", "hold"),
                                                  ("DoubleHoldMode", "DoubleHoldOutput", "tap_hold")):
            mode = old.findtext(mode_field, "Dial modifier" if gesture == "hold" else "Cycle list")
            if mode == "Hold a key":
                b["neutral"][gesture] = action("hold_key", old.findtext(output_field, "Space"))
            for slot, field, direction in (("pressed_cw", "HoldNextOutput", "next"),
                                            ("pressed_ccw", "HoldPreviousOutput", "previous")):
                # There are separate physical pressed-turn signals, not an inferred modifier state.
                if gesture == "tap_hold":
                    if mode != "No action":
                        notes.append(f"{modifier}: second-press dial behavior remains available to assign manually.")
                    break
                b[slot]["tap"] = (action("cycle_" + direction) if mode == "Cycle list" else
                    action("scroll_up" if direction == "next" else "scroll_down") if mode == "Dial scrolling" else
                    convert(old.findtext(field, "No action")) if mode in ("Dial modifier", "Original modifier") else action())
        result["profiles"].append(profile)
    if len(result["profiles"]) == len(settings["profiles"]):
        raise ValueError("No modifier profiles were found in this XML file.")
    validate(result)
    return result, sorted(set(notes))
