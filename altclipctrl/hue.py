"""Fixed wheel geometry and persistent hue position; no screen inspection."""
import json
import math
import os
from pathlib import Path
import threading


def wheel_defaults():
    # Preset from the supplied 2560 x 1440 Clip Studio Paint layout.
    return dict(center_x=123, center_y=1328, radius=75, step=3.0, angle=240.0, program='clipstudiopaint')


def wheel_point(wheel, angle):
    radians = math.radians(angle)
    return (round(wheel['center_x'] + wheel['radius'] * math.sin(radians)),
            round(wheel['center_y'] - wheel['radius'] * math.cos(radians)))


def wheel_key(wheel):
    return json.dumps([wheel[k] for k in ('center_x', 'center_y', 'radius', 'angle', 'program')])


class HueMemory:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.lock = threading.Lock()
        self.positions = {}
        self.revision = self.saved_revision = 0
        if self.path and self.path.exists():
            try:
                values = json.loads(self.path.read_text(encoding='utf-8'))
                self.positions = {k: float(v) % 360 for k, v in values.items()
                                  if isinstance(k, str) and type(v) in (int, float) and math.isfinite(v)}
            except (OSError, ValueError, AttributeError):
                pass

    def angle(self, wheel):
        with self.lock:
            return self.positions.get(wheel_key(wheel), wheel['angle'])

    def remember(self, wheel, angle):
        with self.lock:
            self.positions[wheel_key(wheel)] = angle % 360
            self.revision += 1

    def flush(self):
        if not self.path:
            return
        with self.lock:
            if self.revision == self.saved_revision:
                return
            snapshot, revision = dict(self.positions), self.revision
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + '.tmp')
        temporary.write_text(json.dumps(snapshot), encoding='utf-8')
        os.replace(temporary, self.path)
        with self.lock:
            self.saved_revision = revision
