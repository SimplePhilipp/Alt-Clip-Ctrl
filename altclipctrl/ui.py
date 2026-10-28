from __future__ import annotations

import copy
from collections import deque
from pathlib import Path
import sys
import time

from PySide6.QtCore import Qt, QRectF, Signal, QTimer, QObject, QEvent
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QSpinBox, QDoubleSpinBox, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .engine import Engine
from . import __version__
from .live import LiveInput
from .assignment import QuickAssignment
from .model import ACTIONS, DIAL_MODES, DIAL_SLOTS, GESTURES, GESTURE_NAMES, KEYS, MODIFIERS, ROTATIONS, SLOTS, allowed_actions, defaults, dial_map, import_legacy, load, new_cycle_list, new_profile, normalize, references_cycle, references_profile, save, validate, validate_output
from .platforms import PreviewBackend, WindowsBackend, create_backend

STYLE = """
QWidget { background: #ffffff; color: #161616; font-family: 'Segoe UI', 'Helvetica Neue', sans-serif; font-size: 13px; }
QMainWindow, QDialog { background: #ffffff; }
QLabel#muted { color: #767676; }
QLabel#eyebrow { color: #777777; font-size: 10px; font-weight: 600; letter-spacing: 2px; }
QLabel#title { font-size: 30px; font-weight: 600; letter-spacing: -1px; }
QLabel#section { font-size: 17px; font-weight: 600; }
QPushButton { border: 1px solid #d4d4d4; border-radius: 7px; padding: 8px 13px; min-height: 18px; background: white; }
QPushButton:hover { background: #f1f1f1; border-color: #161616; }
QPushButton:pressed { background: #e5e5e5; }
QPushButton:disabled { color: #999; border-color: #eee; }
QPushButton#primary { background: #181818; border-color: #181818; color: white; font-weight: 600; }
QPushButton#primary:hover { background: #383838; }
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit { border: 1px solid #d4d4d4; border-radius: 6px; padding: 7px; selection-background-color: #242424; selection-color: white; }
QComboBox { min-height: 20px; padding-right: 24px; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox::down-arrow { image: url('CHEVRON'); width: 12px; height: 8px; }
QComboBox QAbstractItemView { selection-background-color: #eee; selection-color: #111; padding: 4px; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #aaa; border-radius: 4px; }
QCheckBox::indicator:checked { background: #242424; border: 1px solid #242424; image: none; }
QTabWidget::pane { border: 1px solid #dedede; border-radius: 7px; top: -1px; }
QTabBar::tab { padding: 12px 18px; color: #777; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #111; border-bottom: 2px solid #111; }
QTableWidget { border: 1px solid #ddd; gridline-color: #eee; selection-background-color: #eee; selection-color: #111; }
QHeaderView::section { background: #f6f6f6; border: none; border-bottom: 1px solid #ddd; padding: 8px; font-weight: 600; }
QToolTip { background: #161616; color: #fff; border: none; padding: 8px; }
QScrollArea { border: none; }
QListWidget { border: none; outline: none; background: white; }
QListWidget::item { border-bottom: 1px solid #e8e8e8; padding: 12px 0; }
QListWidget::item:selected { background: #f5f5f5; color: #111; }
""".replace("CHEVRON", (Path(__file__).parent / "assets" / "chevron.svg").as_posix())


def label(text, name=None, wrap=False):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    if wrap:
        widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    return widget


def button(text, callback, primary=False):
    widget = QPushButton(text)
    if primary:
        widget.setObjectName("primary")
    widget.clicked.connect(callback)
    return widget


def line():
    widget = QFrame()
    widget.setFrameShape(QFrame.Shape.HLine)
    widget.setStyleSheet("color: #e7e7e7; background: #e7e7e7; max-height: 1px; border: 0;")
    return widget


def error(parent, exc):
    QMessageBox.information(parent, "Check settings", str(exc))


def qt_shortcut(event):
    key = event.key()
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
        base = f"F{key - Qt.Key.Key_F1 + 1}"
    else:
        names = {Qt.Key.Key_BracketLeft: "[", Qt.Key.Key_BracketRight: "]", Qt.Key.Key_Equal: "Plus",
                 Qt.Key.Key_Plus: "Plus", Qt.Key.Key_Minus: "Minus", Qt.Key.Key_Apostrophe: "Quote",
                 Qt.Key.Key_QuoteLeft: "Grave", Qt.Key.Key_Semicolon: "Semicolon", Qt.Key.Key_Comma: "Comma",
                 Qt.Key.Key_Period: "Period", Qt.Key.Key_Slash: "Slash", Qt.Key.Key_Backslash: "Backslash",
                 Qt.Key.Key_Control: "Ctrl", Qt.Key.Key_Alt: "Alt", Qt.Key.Key_Shift: "Shift", Qt.Key.Key_Meta: "Meta"}
        base = names.get(key, QKeySequence(key).toString())
    modifiers = event.modifiers()
    parts = [name for flag, name in ((Qt.KeyboardModifier.ControlModifier, "Ctrl"),
             (Qt.KeyboardModifier.AltModifier, "Alt"), (Qt.KeyboardModifier.ShiftModifier, "Shift"),
             (Qt.KeyboardModifier.MetaModifier, "Meta")) if modifiers & flag and name != base]
    return normalize("+".join(parts + [base]), held=True)


class Recorder(QDialog):
    def __init__(self, parent, single=False):
        super().__init__(parent)
        self.single, self.value = single, None
        self.setWindowTitle("Record input" if single else "Record output")
        self.setMinimumWidth(390)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.addWidget(label("Press the controller button" if single else "Press a key or shortcut", "section"))
        layout.addWidget(label("F1–F24 are supported. Modifier-only inputs are excluded." if single else
            "Release the key to finish. Pure modifiers can be used for held actions.", "muted", True))
        self.preview = label("Waiting…", "title")
        layout.addWidget(self.preview)
        layout.addWidget(button("Cancel", self.reject))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        QTimer.singleShot(0, self.setFocus)

    def keyPressEvent(self, event):
        if event.isAutoRepeat():
            return
        try:
            value = qt_shortcut(event)
            if self.single and (value in MODIFIERS or "+" in value):
                self.preview.setText("Choose a single key")
                return
            self.value = value
            self.preview.setText(value)
        except ValueError:
            self.value = None

    def keyReleaseEvent(self, event):
        if self.value and not event.isAutoRepeat():
            self.accept()


class KeyEditor(QWidget):
    def __init__(self, value="B", single=False, held=False):
        super().__init__()
        self.single = single
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.addItems((list(MODIFIERS) if held else []) + KEYS)
        self.combo.setCurrentText(value)
        self.combo.setMinimumWidth(125)
        layout.addWidget(self.combo, 1)
        layout.addWidget(button("Record", self.record))

    def record(self):
        dialog = Recorder(self, self.single)
        if dialog.exec():
            self.combo.setCurrentText(dialog.value)

    def text(self):
        return self.combo.currentText().strip()


class ActionEditor(QWidget):
    def __init__(self, output, profiles, allow_hold, default_dial=None, active_profile=None):
        super().__init__()
        self.profiles = profiles
        self.cycle_profile = active_profile or profiles[0]
        self.dial_mapping = copy.deepcopy(output["value"] if output["kind"] == "dial_modifier" else default_dial or dial_map())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.kind = QComboBox()
        for key, text in allowed_actions(allow_hold).items():
            self.kind.addItem(text, key)
        layout.addWidget(self.kind)
        self.key = KeyEditor(output["value"] if output["kind"] in ("shortcut", "hold_key") else "B", held=allow_hold)
        layout.addWidget(self.key)
        self.profile = QComboBox()
        for profile in profiles:
            self.profile.addItem(profile["name"], profile["id"])
        if output["kind"] == "profile":
            self.profile.setCurrentIndex(self.profile.findData(output["value"]))
        layout.addWidget(self.profile)
        self.cycle_picker = QWidget()
        cycle_form = QFormLayout(self.cycle_picker)
        cycle_form.setContentsMargins(0, 0, 0, 0)
        self.cycle = QComboBox()
        for cycle in self.cycle_profile["cycle_lists"]:
            self.cycle.addItem(cycle["name"], cycle["id"])
        if output["kind"] in ("cycle_next", "cycle_previous", "dial_cycle") and isinstance(output["value"], dict) and "cycle_id" in output["value"]:
            self.cycle.setCurrentIndex(self.cycle.findData(output["value"]["cycle_id"]))
        cycle_form.addRow("Cycle list", self.cycle)
        layout.addWidget(self.cycle_picker)
        self.dial_button = button("Configure temporary dial controls…", self.edit_dial)
        layout.addWidget(self.dial_button)
        self.reverse_direction = QCheckBox("Reverse direction")
        self.reverse_direction.setChecked(bool(output["value"].get("reverse", False)) if output["kind"] in ("dial_scroll", "dial_cycle") and isinstance(output["value"], dict) else False)
        layout.addWidget(self.reverse_direction)
        self.hint = label("", "muted", True)
        layout.addWidget(self.hint)
        self.kind.setCurrentIndex(max(0, self.kind.findData(output["kind"])))
        self.kind.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def refresh(self):
        kind = self.kind.currentData()
        self.key.setVisible(kind in ("shortcut", "hold_key"))
        self.profile.setVisible(kind == "profile")
        self.cycle_picker.setVisible(kind in ("cycle_next", "cycle_previous", "dial_cycle"))
        self.dial_button.setVisible(kind == "dial_modifier")
        self.reverse_direction.setVisible(kind in ("dial_scroll", "dial_cycle"))
        self.hint.setText({"none": "This gesture sends nothing.", "shortcut": "Send a key or chord once. Example: Ctrl+Shift+F24.",
            "hold_key": "Keep the key or chord down until you release this button.",
            "cycle_next": "Move forward through the selected cycle list. Manage lists in Options.",
            "cycle_previous": "Move backward through the selected cycle list. Manage lists in Options.",
            "scroll_up": "Scroll at the mouse pointer. Amount and reversal are in Options.",
            "scroll_down": "Scroll at the mouse pointer. Amount and reversal are in Options.",
            "dial_scroll": "While held: clockwise scrolls up and counterclockwise scrolls down, including pressed turns. Amount and reversal are in Options.",
            "dial_cycle": "While held: clockwise moves forward and counterclockwise moves backward through the selected cycle list.",
            "dial_modifier": "Choose temporary outputs for all five dial controls. Release this button to restore the normal dial actions.",
            "profile": "Activate this profile and release any held output."}.get(kind, ""))

    def read(self):
        kind = self.kind.currentData()
        if kind in ("cycle_next", "cycle_previous", "dial_cycle"):
            value = {"cycle_id": self.cycle.currentData()}
            if kind == "dial_cycle":
                value["reverse"] = self.reverse_direction.isChecked()
            return {"kind": kind, "value": value}
        return {"kind": kind, "value": self.key.text() if kind in ("shortcut", "hold_key") else
                self.profile.currentData() if kind == "profile" else copy.deepcopy(self.dial_mapping) if kind == "dial_modifier" else
                {"reverse": self.reverse_direction.isChecked()} if kind == "dial_scroll" else ""}

    def edit_dial(self):
        dialog = TemporaryDialDialog(self, self.dial_mapping, self.profiles, self.cycle_profile)
        if dialog.exec():
            self.dial_mapping = dialog.result_mapping


class TemporaryDialDialog(QDialog):
    def __init__(self, parent, mapping, profiles, active_profile=None):
        super().__init__(parent)
        self.profiles = profiles
        self.cycle_profile = active_profile or profiles[0]
        self.setWindowTitle("Dial modifier · Temporary controls")
        self.resize(700, 730)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.addWidget(label("Temporary dial controls", "title"))
        layout.addWidget(label("These outputs replace the normal dial actions only while the assigned button is held. Device input keys stay the same.", "muted", True))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        rows = QVBoxLayout(content)
        rows.setSpacing(16)
        self.editors = {}
        for slot in DIAL_SLOTS:
            rows.addWidget(label(dict(SLOTS)[slot], "section"))
            editor = ActionEditor(mapping[slot], profiles, False, active_profile=self.cycle_profile)
            self.editors[slot] = editor
            rows.addWidget(editor)
            rows.addWidget(line())
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        footer = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        footer.accepted.connect(self.commit)
        footer.rejected.connect(self.reject)
        footer.button(QDialogButtonBox.StandardButton.Save).setObjectName("primary")
        layout.addWidget(footer)

    def commit(self):
        mapping = {slot: editor.read() for slot, editor in self.editors.items()}
        try:
            for output in mapping.values():
                validate_output(output, {p["id"] for p in self.profiles}, cycles=self.cycle_profile["cycle_lists"])
            self.result_mapping = mapping
            self.accept()
        except Exception as exc:
            error(self, exc)


class BindingDialog(QDialog):
    def __init__(self, parent, settings, slot):
        super().__init__(parent)
        self.result_settings = copy.deepcopy(settings)
        self.slot = slot
        self.profile = next(p for p in self.result_settings["profiles"] if p["id"] == settings["active_profile"])
        binding = self.profile["bindings"][slot]
        self.setWindowTitle("Configure · " + binding["name"])
        self.resize(620, 620 if slot not in ROTATIONS else 450)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 24)
        layout.setSpacing(15)
        layout.addWidget(label("BUTTON MAPPING" if slot not in ROTATIONS else "DIAL MAPPING", "eyebrow"))
        layout.addWidget(label(dict(SLOTS)[slot], "title"))
        layout.addWidget(label("Profile · " + self.profile["name"], "muted"))
        form = QFormLayout()
        form.setSpacing(12)
        self.name = QLineEdit(binding["name"])
        self.input = KeyEditor(binding["input"], single=True)
        form.addRow("Button name", self.name)
        form.addRow("Device input", self.input)
        layout.addLayout(form)
        layout.addWidget(label("Set your controller to send this single key. The name appears when you hover over its control.", "muted", True))
        layout.addWidget(line())
        self.editors = {}
        if slot in ROTATIONS:
            layout.addWidget(label("On each turn", "section"))
            self.editors["tap"] = ActionEditor(binding["tap"], settings["profiles"], False, active_profile=self.profile)
            layout.addWidget(self.editors["tap"])
        else:
            tabs = QTabWidget()
            for gesture in GESTURES:
                page = QWidget()
                page_layout = QVBoxLayout(page)
                page_layout.setContentsMargins(16, 20, 16, 16)
                help_text = {"tap": "Press and release once.", "hold": "Press and keep holding.",
                             "tap_hold": "Tap, release, then press and keep holding."}[gesture]
                page_layout.addWidget(label(help_text, "muted"))
                self.editors[gesture] = ActionEditor(binding[gesture], settings["profiles"], gesture != "tap", dial_map(self.profile), self.profile)
                page_layout.addWidget(self.editors[gesture])
                page_layout.addStretch()
                tabs.addTab(page, GESTURE_NAMES[gesture])
            layout.addWidget(tabs, 1)
        layout.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primary")
        buttons.accepted.connect(self.commit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def commit(self):
        binding = self.profile["bindings"][self.slot]
        binding["name"], binding["input"] = self.name.text().strip(), self.input.text()
        for gesture, editor in self.editors.items():
            binding[gesture] = editor.read()
        try:
            validate(self.result_settings)
            self.accept()
        except (ValueError, KeyError) as exc:
            error(self, exc)


class DeviceButton(QPushButton):
    def __init__(self, slot, compact=False):
        super().__init__()
        self.slot, self.compact = slot, compact
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.flash = False
        self.input_held = False
        self.assigning = False
        self.name, self.signal, self.number = "", "", ""

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        active = self.underMouse() or self.isDown() or self.flash or self.input_held or self.assigning
        painter.setBrush(QColor("#181818" if active else "#ffffff"))
        painter.setPen(QPen(QColor("#181818"), 2))
        painter.drawRoundedRect(rect, 10 if not self.compact else 5, 10 if not self.compact else 5)
        painter.setPen(QColor("#ffffff" if active else "#181818"))
        if self.slot in ROTATIONS or self.slot == "neutral":
            painter.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.number)
        if self.hasFocus():
            painter.setPen(QPen(QColor("#777"), 1, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(5, 5, -5, -5), 6, 6)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)


class DeviceMap(QWidget):
    selected = Signal(str)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(460, 430)
        self.buttons = {}
        for slot, _ in SLOTS:
            widget = DeviceButton(slot, slot.startswith(("left_", "right_")))
            widget.clicked.connect(lambda checked=False, s=slot: self.selected.emit(s))
            self.buttons[slot] = widget
            widget.setParent(self)

    def resizeEvent(self, event):
        cx = self.width() / 2
        x, y, w = cx - 128, 14, 256
        positions = {"top_left": (x+8, y+6, 78, 66), "top_middle": (x+89, y+6, 78, 66),
            "top_right": (x+170, y+6, 78, 66), "left_upper": (x-11, y+84, 24, 62),
            "left_lower": (x-11, y+151, 24, 62), "right_upper": (x+w-13, y+84, 24, 62),
            "right_lower": (x+w-13, y+151, 24, 62)}
        for i, slot in enumerate(("pressed_ccw", "ccw", "neutral", "cw", "pressed_cw")):
            positions[slot] = (cx-220+i*90, 356, 80, 66)
        for slot, rect in positions.items():
            self.buttons[slot].setGeometry(*(int(v) for v in rect))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.width() / 2
        painter.setPen(QPen(QColor("#181818"), 2.5))
        painter.setBrush(QColor("white"))
        painter.drawRoundedRect(QRectF(cx-128, 14, 256, 285), 35, 35)
        painter.drawEllipse(QRectF(cx-76, 119, 152, 152))
        painter.setPen(QPen(QColor("#dedede"), 1))
        painter.drawEllipse(QRectF(cx-65, 130, 130, 130))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#181818"))
        painter.drawEllipse(QRectF(cx-6, 140, 12, 12))
        painter.setPen(QPen(QColor("#d0d0d0"), 1, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath()
        path.moveTo(cx, 301)
        path.lineTo(cx, 326)
        path.moveTo(cx-180, 349)
        path.lineTo(cx-180, 326)
        path.lineTo(cx+180, 326)
        path.lineTo(cx+180, 349)
        for pos in (cx-90, cx, cx+90):
            path.moveTo(pos, 326)
            path.lineTo(pos, 349)
        painter.drawPath(path)

    def refresh(self, profile):
        symbols = {"pressed_ccw": "↓ ↶", "ccw": "↶", "neutral": "↓", "cw": "↷", "pressed_cw": "↓ ↷"}
        for i, (slot, _) in enumerate(SLOTS):
            binding = profile["bindings"][slot]
            widget = self.buttons[slot]
            widget.name, widget.signal = binding["name"], binding["input"]
            widget.number = symbols.get(slot, "")
            widget.setToolTip(binding["name"] + "\nInput · " + binding["input"])
            widget.setAccessibleName(binding["name"])
            widget.setAccessibleDescription("Configure input " + binding["input"])
            widget.update()

    def pulse(self, signal):
        for widget in self.buttons.values():
            if widget.signal == signal:
                widget.flash = True
                widget.update()
                QTimer.singleShot(100, lambda w=widget: self.unpulse(w))

    def set_held(self, signal, down):
        for widget in self.buttons.values():
            if widget.signal == signal:
                widget.input_held = down
                widget.update()
        if down:
            self.pulse(signal)

    def clear_held(self):
        for widget in self.buttons.values():
            widget.input_held = widget.flash = False
            widget.update()

    def highlight(self, slot):
        for key, widget in self.buttons.items():
            widget.assigning = key == slot
            widget.update()

    @staticmethod
    def unpulse(widget):
        widget.flash = False
        widget.update()


class OptionsDialog(QDialog):
    def __init__(self, parent, settings, foreground=""):
        super().__init__(parent)
        self.result_settings = copy.deepcopy(settings)
        self.current = settings["active_profile"]
        self.foreground = foreground
        self.loading = False
        self.current_cycle = None
        self.setWindowTitle("Alt Clip Ctrl · Options")
        self.resize(800, 680)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(14)
        layout.addWidget(label("Options", "title"))
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)
        profiles = QWidget()
        p = QVBoxLayout(profiles)
        p.setContentsMargins(20, 20, 20, 20)
        p.setSpacing(14)
        self.selector = QComboBox()
        self.fill_profiles()
        p.addWidget(self.selector)
        row = QHBoxLayout()
        for text, callback in (("New", self.add_profile), ("Duplicate", self.duplicate_profile),
                               ("Delete", self.delete_profile)):
            row.addWidget(button(text, callback))
        row.addStretch()
        p.addLayout(row)
        form = QFormLayout()
        self.profile_name = QLineEdit()
        form.addRow("Profile name", self.profile_name)
        p.addLayout(form)
        self.auto = QCheckBox("Switch profiles automatically when a linked program is active")
        self.auto.setChecked(settings["auto_switch"])
        p.addWidget(self.auto)
        p.addWidget(label("Linked programs", "section"))
        p.addWidget(label("One exact program name per line: CLIPStudioPaint.exe on Windows, a bundle ID such as com.apple.Preview on macOS, or a WM_CLASS on Linux/X11.", "muted", True))
        self.programs = QPlainTextEdit()
        self.programs.setPlaceholderText("CLIPStudioPaint.exe\nPhotoshop.exe")
        self.programs.setMaximumHeight(120)
        p.addWidget(self.programs)
        detected = button("Link last active program" + (" · " + foreground if foreground else ""), self.link_program)
        detected.setEnabled(bool(foreground and foreground != "@self"))
        p.addWidget(detected)
        p.addWidget(label("Programs without a link keep the current profile. Button actions can switch profiles too; assign Switch profile in any button's menu.", "muted", True))
        p.addStretch()
        tabs.addTab(profiles, "Profiles & programs")

        cycles = QWidget()
        c = QVBoxLayout(cycles)
        c.setContentsMargins(20, 20, 20, 20)
        c.addWidget(label("Cycle lists", "section"))
        c.addWidget(label("Create named lists for the profile selected in Profiles & programs. Choose a list in each button's cycling action.", "muted", True))
        self.cycle_selector = QComboBox()
        c.addWidget(self.cycle_selector)
        list_buttons = QHBoxLayout()
        for text, callback in (("New list", self.add_cycle_list), ("Duplicate list", self.duplicate_cycle_list), ("Delete list", self.delete_cycle_list)):
            list_buttons.addWidget(button(text, callback))
        c.addLayout(list_buttons)
        cycle_form = QFormLayout()
        self.cycle_name = QLineEdit()
        cycle_form.addRow("List name", self.cycle_name)
        c.addLayout(cycle_form)
        self.cycle = QTableWidget(0, 2)
        self.cycle.setHorizontalHeaderLabels(["Tool / action name", "Shortcut"])
        self.cycle.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.cycle.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.cycle.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.cycle.verticalHeader().hide()
        c.addWidget(self.cycle, 1)
        row = QHBoxLayout()
        for text, callback in (("Add", self.add_cycle), ("Remove", self.remove_cycle),
                               ("Move up", lambda: self.move_cycle(-1)), ("Move down", lambda: self.move_cycle(1))):
            row.addWidget(button(text, callback))
        c.addLayout(row)
        c.addWidget(label("Lists wrap independently. Direct matching keyboard shortcuts resync their positions. Mouse tool changes cannot be detected.", "muted", True))
        tabs.addTab(cycles, "Actions & cycles")

        advanced = QWidget()
        a = QVBoxLayout(advanced)
        a.setContentsMargins(20, 20, 20, 20)
        a.setSpacing(18)
        a.addWidget(label("Gesture timing", "section"))
        form = QFormLayout()
        self.tap = QSpinBox()
        self.tap.setRange(20, 2000)
        self.tap.setValue(settings["tap_ms"])
        self.tap.setSuffix(" ms")
        self.hold = QSpinBox()
        self.hold.setRange(20, 2000)
        self.hold.setValue(settings["hold_ms"])
        self.hold.setSuffix(" ms")
        form.addRow("Tap / second-press window", self.tap)
        form.addRow("Hold starts after", self.hold)
        self.amount = QSpinBox()
        self.amount.setRange(1, 20)
        self.amount.setValue(settings["scroll_amount"])
        form.addRow("Scroll notches per step", self.amount)
        a.addLayout(form)
        self.reverse = QCheckBox("Reverse scrolling direction")
        self.reverse.setChecked(settings["reverse_scroll"])
        a.addWidget(self.reverse)
        self.acceleration = QCheckBox("Scroll acceleration")
        self.acceleration.setChecked(settings.get("scroll_acceleration", False))
        a.addWidget(self.acceleration)
        self.acceleration_factor = QDoubleSpinBox()
        self.acceleration_factor.setRange(1, 10)
        self.acceleration_factor.setDecimals(2)
        self.acceleration_factor.setSingleStep(.25)
        self.acceleration_factor.setSuffix(" ×")
        self.acceleration_factor.setValue(settings.get("scroll_acceleration_factor", 3.0))
        self.acceleration_factor.setEnabled(self.acceleration.isChecked())
        self.acceleration.toggled.connect(self.acceleration_factor.setEnabled)
        acceleration_form = QFormLayout()
        acceleration_form.addRow("Acceleration factor", self.acceleration_factor)
        a.addLayout(acceleration_form)
        a.addWidget(label("Slow dial turns keep the normal step size. Quick turns increase up to this factor. Pausing or reversing starts at normal speed.", "muted", True))
        a.addWidget(label("Taps wait for the second-press window. Dial turns are immediate. Held keys are released on focus change, profile change, pause, settings changes and exit.", "muted", True))
        a.addWidget(line())
        a.addWidget(label("Reuse legacy Windows settings", "section"))
        a.addWidget(label("Import old cycle lists and compatible output actions as new profiles. Device inputs stay separate from Alt, Ctrl and Shift.", "muted", True))
        a.addWidget(button("Import settings XML…", self.import_xml))
        a.addStretch()
        advanced_scroll = QScrollArea()
        advanced_scroll.setWidgetResizable(True)
        advanced_scroll.setFrameShape(QFrame.Shape.NoFrame)
        advanced_scroll.setWidget(advanced)
        tabs.addTab(advanced_scroll, "Advanced")

        device = QWidget()
        d = QVBoxLayout(device)
        d.setContentsMargins(20, 20, 20, 20)
        d.setSpacing(14)
        d.addWidget(label("Dedicated input signals", "section"))
        d.addWidget(label("Use the controller's configuration software to assign one unique key to each of its twelve signals. F13–F24 are the defaults. F1–F24 and ordinary keyboard keys are selectable as inputs and outputs.", "muted", True))
        d.addWidget(label("Windows", "section"))
        d.addWidget(label("Only assigned signals are intercepted. Output is tagged so it cannot trigger its own mapping. Close the legacy Windows helper before starting this app.", "muted", True))
        d.addWidget(label("Linux · X11 / Wayland", "section"))
        self.linux_device = QComboBox()
        self.linux_device.setEditable(True)
        self.linux_device.addItem("", "")
        if sys.platform.startswith("linux"):
            try:
                from .platforms import LinuxBackend
                for path, name in LinuxBackend.devices():
                    self.linux_device.addItem(path + " · " + name, path)
            except Exception:
                pass
        self.linux_device.setCurrentText(settings["linux_device"])
        d.addWidget(self.linux_device)
        d.addWidget(label("Select the controller's /dev/input/event device. Access to that device and /dev/uinput is required. The controller is grabbed; other keyboards are untouched. Automatic program links use X11; choose profiles manually on Wayland.", "muted", True))
        d.addWidget(label("macOS", "section"))
        d.addWidget(label("Allow Accessibility and Input Monitoring. F1–F20 use native keycodes. F21–F24 use AppKit function characters and depend on the controller and receiving app; verify those four keys before relying on them.", "muted", True))
        d.addStretch()
        tabs.addTab(device, "Device")
        footer = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        footer.button(QDialogButtonBox.StandardButton.Save).setObjectName("primary")
        footer.accepted.connect(self.commit)
        footer.rejected.connect(self.reject)
        layout.addWidget(footer)
        self.load_profile()
        self.selector.currentIndexChanged.connect(self.change_profile)
        self.cycle_selector.currentIndexChanged.connect(self.change_cycle_list)

    def profile(self):
        return next(p for p in self.result_settings["profiles"] if p["id"] == self.current)

    def fill_profiles(self):
        self.selector.blockSignals(True)
        self.selector.clear()
        for profile in self.result_settings["profiles"]:
            self.selector.addItem(profile["name"], profile["id"])
        self.selector.setCurrentIndex(self.selector.findData(self.current))
        self.selector.blockSignals(False)

    def store_profile(self):
        profile = self.profile()
        profile["name"] = self.profile_name.text().strip()
        profile["programs"] = [s.strip() for s in self.programs.toPlainText().splitlines() if s.strip()]
        self.store_cycle_list()

    def cell(self, row, column):
        item = self.cycle.item(row, column)
        return item.text().strip() if item else ""

    def load_profile(self):
        profile = self.profile()
        self.profile_name.setText(profile["name"])
        self.programs.setPlainText("\n".join(profile["programs"]))
        self.current_cycle = profile["cycle_lists"][0]["id"]
        self.fill_cycle_lists()
        self.load_cycle_list()

    def selected_cycle_list(self):
        return next(c for c in self.profile()["cycle_lists"] if c["id"] == self.current_cycle)

    def store_cycle_list(self):
        if self.current_cycle is None:
            return
        cycle = self.selected_cycle_list()
        cycle["name"] = self.cycle_name.text().strip()
        cycle["items"] = [{"name": self.cell(i, 0), "shortcut": self.cell(i, 1)} for i in range(self.cycle.rowCount())]
        self.cycle_selector.setItemText(self.cycle_selector.findData(self.current_cycle), cycle["name"])

    def fill_cycle_lists(self):
        self.cycle_selector.blockSignals(True)
        self.cycle_selector.clear()
        for cycle in self.profile()["cycle_lists"]:
            self.cycle_selector.addItem(cycle["name"], cycle["id"])
        self.cycle_selector.setCurrentIndex(self.cycle_selector.findData(self.current_cycle))
        self.cycle_selector.blockSignals(False)

    def load_cycle_list(self):
        cycle = self.selected_cycle_list()
        self.cycle_name.setText(cycle["name"])
        self.cycle.setRowCount(0)
        for item in cycle["items"]:
            self.add_cycle(item=item)

    def change_cycle_list(self):
        selected = self.cycle_selector.currentData()
        if selected is None or selected == self.current_cycle:
            return
        self.store_cycle_list()
        self.current_cycle = selected
        self.load_cycle_list()

    def append_cycle_list(self, cycle):
        if len(self.profile()["cycle_lists"]) >= 64:
            return error(self, "Keep at most 64 cycle lists per profile.")
        existing = {c["name"].casefold() for c in self.profile()["cycle_lists"]}
        name, suffix = cycle["name"], 2
        while cycle["name"].casefold() in existing:
            cycle["name"], suffix = f"{name} {suffix}", suffix + 1
        self.profile()["cycle_lists"].append(cycle)
        self.current_cycle = cycle["id"]
        self.fill_cycle_lists()
        self.load_cycle_list()

    def add_cycle_list(self):
        self.store_profile()
        self.append_cycle_list(new_cycle_list("New list", [{"name": "New action", "shortcut": "F1"}]))

    def duplicate_cycle_list(self):
        self.store_profile()
        original = self.selected_cycle_list()
        self.append_cycle_list(new_cycle_list(original["name"] + " copy", original["items"]))

    def delete_cycle_list(self):
        self.store_profile()
        cycles = self.profile()["cycle_lists"]
        if len(cycles) == 1:
            return error(self, "Keep at least one cycle list in each profile.")
        for binding in self.profile()["bindings"].values():
            if any(references_cycle(binding[g], self.current_cycle, cycles[0]["id"]) for g in GESTURES):
                return error(self, "‘" + binding["name"] + "’ uses this cycle list. Choose another list in that button's action first.")
        cycles.remove(self.selected_cycle_list())
        self.current_cycle = cycles[0]["id"]
        self.fill_cycle_lists()
        self.load_cycle_list()

    def change_profile(self):
        if self.selector.currentData() is None:
            return
        self.store_profile()
        self.current = self.selector.currentData()
        self.fill_profiles()
        self.load_profile()

    def add_profile(self):
        name, ok = QInputDialog.getText(self, "New profile", "Profile name")
        if ok and name.strip():
            self.store_profile()
            profile = new_profile(name.strip())
            self.result_settings["profiles"].append(profile)
            self.current = profile["id"]
            self.fill_profiles()
            self.load_profile()

    def duplicate_profile(self):
        self.store_profile()
        profile = copy.deepcopy(self.profile())
        profile["id"] = new_profile()["id"]
        profile["name"] += " copy"
        suffix = 2
        original = profile["name"]
        while any(p["name"] == profile["name"] for p in self.result_settings["profiles"]):
            profile["name"] = original + " " + str(suffix)
            suffix += 1
        profile["programs"] = []
        self.result_settings["profiles"].append(profile)
        self.current = profile["id"]
        self.fill_profiles()
        self.load_profile()

    def delete_profile(self):
        profiles = self.result_settings["profiles"]
        if len(profiles) == 1:
            return error(self, "Keep at least one profile.")
        for profile in profiles:
            if profile["id"] == self.current:
                continue
            for binding in profile["bindings"].values():
                if any(references_profile(binding[g], self.current) for g in GESTURES):
                    return error(self, "A button in ‘" + profile["name"] + "’ switches to this profile. Change that action first.")
        profiles.remove(self.profile())
        self.current = profiles[0]["id"]
        if self.result_settings["active_profile"] not in {p["id"] for p in profiles}:
            self.result_settings["active_profile"] = self.current
        self.fill_profiles()
        self.load_profile()

    def link_program(self):
        entries = [s.strip() for s in self.programs.toPlainText().splitlines() if s.strip()]
        if self.foreground not in entries:
            entries.append(self.foreground)
        self.programs.setPlainText("\n".join(entries))

    def add_cycle(self, checked=False, item=None):
        row = self.cycle.rowCount()
        self.cycle.insertRow(row)
        item = item or {"name": "New action", "shortcut": "F1"}
        self.cycle.setItem(row, 0, QTableWidgetItem(item["name"]))
        self.cycle.setItem(row, 1, QTableWidgetItem(item["shortcut"]))
        self.cycle.selectRow(row)

    def remove_cycle(self):
        row = self.cycle.currentRow()
        if row >= 0:
            self.cycle.removeRow(row)

    def move_cycle(self, direction):
        row = self.cycle.currentRow()
        target = row + direction
        if row < 0 or not 0 <= target < self.cycle.rowCount():
            return
        for col in range(2):
            source_item, target_item = self.cycle.takeItem(row, col), self.cycle.takeItem(target, col)
            self.cycle.setItem(row, col, target_item)
            self.cycle.setItem(target, col, source_item)
        self.cycle.selectRow(target)

    def import_xml(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import legacy Alt Clip Ctrl settings", "", "XML settings (*.xml)")
        if not path:
            return
        try:
            self.store_profile()
            result, notes = import_legacy(path, self.result_settings)
            self.result_settings = result
            self.fill_profiles()
            QMessageBox.information(self, "Settings imported", "Imported as new profiles. Save to keep them." + ("\n\n" + "\n".join(notes) if notes else ""))
        except Exception as exc:
            error(self, exc)

    def commit(self):
        self.store_profile()
        self.result_settings.update(auto_switch=self.auto.isChecked(), tap_ms=self.tap.value(), hold_ms=self.hold.value(),
            scroll_amount=self.amount.value(), reverse_scroll=self.reverse.isChecked(),
            scroll_acceleration=self.acceleration.isChecked(), scroll_acceleration_factor=self.acceleration_factor.value(),
            linux_device=self.linux_device.currentData() if self.linux_device.currentIndex() > 0 else self.linux_device.currentText().strip())
        try:
            validate(self.result_settings)
            self.accept()
        except (ValueError, KeyError) as exc:
            error(self, exc)


class Bridge(QObject):
    input = Signal(str, bool, float, int, bool, object, bool)
    failed = Signal(str)
    observed = Signal(str, bool)
    assignment = Signal(str, bool, float, int)


class MainWindow(QMainWindow):
    def __init__(self, settings_path, *, diagnostic=False):
        super().__init__()
        self.path = Path(settings_path)
        self.config = defaults()
        self.load_error = ""
        if self.path.exists():
            try:
                self.config = load(self.path)
            except Exception as exc:
                self.load_error = str(exc)
        self.diagnostic = diagnostic
        self.generation = 0
        self.active_inputs = frozenset()
        self.accept_input = False
        self.preview_input = False
        self.assignment = None
        self.assignment_id = 0
        self.recording_focus = False
        self.history_entries = deque(maxlen=3)
        self.last_foreground = ""
        self.modal = False
        self.runtime_error = ""
        self.bridge = Bridge()
        self.bridge.input.connect(self.input_event)
        self.bridge.failed.connect(self.failed)
        self.bridge.observed.connect(self.observe)
        self.bridge.assignment.connect(self.assignment_event)
        self.backend = None
        self.live = None
        self.last_live_view = 0
        self.engine = None
        self.preview_engine = Engine(self.config, PreviewBackend(), self.preview_switched,
                                     lambda event: self.record_activity(event, preview=True))
        self.physical = set()
        self.setWindowTitle(f"Alt Clip Ctrl {__version__} · Dial driver")
        self.resize(1000, 830)
        self.setMinimumSize(900, 800)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(36, 25, 36, 22)
        layout.setSpacing(20)
        header = QHBoxLayout()
        profile_box = QVBoxLayout()
        profile_box.setSpacing(5)
        profile_box.addWidget(label("PROFILE", "eyebrow"))
        self.profiles = QComboBox()
        self.profiles.setMinimumWidth(220)
        profile_box.addWidget(self.profiles)
        header.addLayout(profile_box)
        header.addStretch()
        brand = QVBoxLayout()
        brand.setSpacing(2)
        brand.addWidget(label("Alt Clip Ctrl", "section"))
        brand.addWidget(label("DIAL DRIVER", "eyebrow"))
        header.addLayout(brand)
        header.addSpacing(24)
        self.enabled = QCheckBox("Enabled")
        self.enabled.setChecked(self.config["enabled"])
        self.enabled.toggled.connect(self.toggle_enabled)
        header.addWidget(self.enabled)
        header.addSpacing(12)
        header.addWidget(button("Options", self.open_options))
        layout.addLayout(header)
        layout.addWidget(line())
        self.intro_title = label("Make every movement yours.", "title")
        self.intro_hint = label("Click a control to choose its input and actions. Hover to see its name.", "muted")
        layout.addWidget(self.intro_title)
        layout.addWidget(self.intro_hint)
        self.assignment_panel = QFrame()
        self.assignment_panel.setStyleSheet("QFrame { background: #f5f5f5; border-radius: 8px; } QLabel { background: transparent; }")
        assignment_layout = QVBoxLayout(self.assignment_panel)
        assignment_layout.setContentsMargins(16, 12, 16, 12)
        self.assignment_title = label("", "section")
        self.assignment_hint = label("", "muted", True)
        self.assignment_progress = label("", "muted", True)
        assignment_layout.addWidget(self.assignment_title)
        assignment_layout.addWidget(self.assignment_hint)
        assignment_layout.addWidget(self.assignment_progress)
        assignment_buttons = QHBoxLayout()
        self.assignment_back = button("Back", self.assignment_go_back)
        self.assignment_skip = button("Skip", self.assignment_go_skip)
        self.assignment_save = button("Save inputs", self.save_assignment, primary=True)
        assignment_buttons.addWidget(self.assignment_back)
        assignment_buttons.addWidget(self.assignment_skip)
        assignment_buttons.addStretch()
        assignment_buttons.addWidget(button("Cancel", self.cancel_assignment))
        assignment_buttons.addWidget(self.assignment_save)
        assignment_layout.addLayout(assignment_buttons)
        self.assignment_panel.hide()
        layout.addWidget(self.assignment_panel)
        body = QHBoxLayout()
        body.setSpacing(28)
        history_area = QWidget()
        history_area.setFixedWidth(270)
        history_layout = QVBoxLayout(history_area)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.setSpacing(12)
        history_header = QHBoxLayout()
        history_header.addWidget(label("ACTION HISTORY", "eyebrow"), 1)
        history_header.addWidget(button("Clear", self.clear_history))
        history_layout.addLayout(history_header)
        self.history_empty = label("Press a controller button to see its gesture and called action here.", "muted", True)
        history_layout.addWidget(self.history_empty)
        self.history = QListWidget()
        self.history.setWordWrap(True)
        self.history.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        history_layout.addWidget(self.history, 1)
        history_layout.addWidget(label("Three most recent actions. History stays in this session.", "muted", True))
        body.addWidget(history_area)
        map_area = QVBoxLayout()
        map_area.setSpacing(4)
        map_header = QHBoxLayout()
        map_header.addWidget(label("YOUR CONTROLLER", "eyebrow"), 1)
        self.quick_assign = button("Quick assign", self.start_assignment)
        map_header.addWidget(self.quick_assign)
        map_area.addLayout(map_header)
        self.map = DeviceMap()
        self.map.selected.connect(self.edit_binding)
        map_area.addWidget(self.map, 1)
        body.addLayout(map_area, 3)
        self.profile_title = label("", "section")
        self.mapping_count = label("", "muted")
        self.program_links = label("", "muted", True)
        map_area.addWidget(self.mapping_count)
        map_area.addWidget(label("− Tap     _ Hold     −_ Tap then hold", "muted"))
        layout.addLayout(body, 1)
        layout.addWidget(line())
        self.status = label("Starting input listener…", "muted", True)
        layout.addWidget(self.status)
        self.profiles.currentIndexChanged.connect(self.choose_profile)
        self.refresh()
        self.clock = QTimer(self)
        self.clock.setInterval(8)
        self.clock.timeout.connect(self.tick)
        self.focus_clock = QTimer(self)
        self.focus_clock.setInterval(250)
        self.focus_clock.timeout.connect(self.refresh_scope)
        QApplication.instance().applicationStateChanged.connect(self.application_state)
        QApplication.instance().installEventFilter(self)
        if not diagnostic:
            self.start_backend()
            self.focus_clock.start()
            if self.load_error:
                QTimer.singleShot(0, lambda: QMessageBox.information(self, "Settings could not be loaded",
                    "The saved file was left untouched. Defaults are shown.\n\n" + self.load_error))
        else:
            self.status.setText("Preview · Controller gestures are shown without sending output")
        self.clock.start()
        self.refresh_scope()

    def capture(self, signal, down, now, injected=False):
        # Live Windows input never waits for Qt or a history/layout update.
        if self.assignment is not None:
            if self.recording_focus:
                self.bridge.assignment.emit(signal, down, now, self.assignment_id)
                return signal not in MODIFIERS
            return False
        if self.live and self.config["enabled"] and not self.modal:
            routed = self.live.capture(signal, down, now, self.backend.foreground_token(), injected=injected)
            if routed is not None:
                return routed
        if self.config["enabled"] and not self.modal and signal in self.active_inputs:
            token = self.backend.foreground_token() if self.backend else None
            repeats = injected and any(self.active_profile()["bindings"][slot]["input"] == signal for slot in ROTATIONS)
            self.bridge.input.emit(signal, down, now, self.generation, self.preview_input, token, repeats)
            return True
        if self.accept_input:
            self.bridge.observed.emit(signal, down)
        return False

    def start_backend(self):
        try:
            if self.live:
                self.live.stop()
                self.live = None
            if self.backend:
                self.backend.stop()
            self.backend = create_backend(self.capture, self.bridge.failed.emit, self.config["linux_device"])
            if isinstance(self.backend, WindowsBackend):
                self.live = LiveInput(self.config, self.backend, self.bridge.failed.emit)
                self.engine = self.live.engine
            else:
                self.engine = Engine(self.config, self.backend, self.engine_switched, self.record_activity)
            self.backend.start()
            if self.live:
                self.live.start()
            self.refresh_scope()
        except Exception as exc:
            if self.backend:
                self.backend.stop()
            self.failed(str(exc))

    def tick(self):
        if self.live and time.monotonic() - self.last_live_view >= .033:
            self.drain_live_view()
        engine = self.preview_engine if self.preview_input else self.engine if self.accept_input and not self.live else None
        if engine:
            try:
                engine.poll(time.monotonic())
            except Exception as exc:
                self.failed(str(exc))

    def drain_live_view(self):
        now = time.monotonic()
        events, lights, profile_id = self.live.snapshot()
        self.last_live_view = now
        if profile_id != self.config["active_profile"]:
            self.config["active_profile"] = profile_id
            self.preview_engine.configure(self.config)
            self.refresh()
            try:
                save(self.path, self.config)
            except Exception as exc:
                self.status.setText("Could not save profile: " + str(exc))
        for event in events:
            self.record_activity(event)
        # Own-window presses are displayed by the preview input path. Native
        # snapshots describe background input and must not clear those holds
        # or restore an old press after the preview has released it.
        if self.preview_input:
            return
        for widget in self.map.buttons.values():
            down, last_press = lights.get(widget.signal, (False, 0))
            flash = now - last_press < .08
            if widget.input_held != down or widget.flash != flash:
                widget.input_held, widget.flash = down, flash
                widget.update()

    def input_event(self, signal, down, now, generation, preview=False, target=None, repeated=False):
        if target is not None and self.backend:
            if target != self.backend.foreground_token():
                return
            if generation != self.generation and not (
                generation == getattr(self, "scope_previous_generation", None) and
                self.generation == getattr(self, "scope_input_generation", None)
            ):
                return
            # Route the first input after a window switch to the correct engine,
            # rather than waiting for the 250 ms foreground-name poll.
            self.refresh_scope()
            generation, preview = self.generation, self.preview_input
        engine = self.preview_engine if preview and self.preview_input else self.engine if not preview and self.accept_input else None
        if engine is None or generation != self.generation:
            return
        try:
            self.map.set_held(signal, down)
            engine.event(signal, down, now, repeated=repeated)
        except Exception as exc:
            self.failed(str(exc))

    def eventFilter(self, watched, event):
        if event.type() not in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            return super().eventFilter(watched, event)
        if self.modal or not self.isActiveWindow():
            return super().eventFilter(watched, event)
        try:
            text = qt_shortcut(event)
        except ValueError:
            return super().eventFilter(watched, event)
        tokens = text.split("+")
        signal = tokens[-1]
        down = event.type() == QEvent.Type.KeyPress
        if self.assignment is not None:
            if not event.isAutoRepeat():
                if down and any(token in MODIFIERS for token in tokens[:-1]):
                    self.assignment.message = "Release Ctrl, Alt, Shift and Meta, then send a single key."
                    self.update_assignment()
                else:
                    self.assignment_event(signal, down, time.monotonic(), self.assignment_id)
            return True
        if self.preview_input and signal in self.active_inputs:
            if not event.isAutoRepeat():
                self.input_event(signal, down, time.monotonic(), self.generation, True)
            return True
        return super().eventFilter(watched, event)

    def start_assignment(self):
        self.reset()
        self.assignment_original_size = self.size()
        self.assignment_original_minimum = self.minimumHeight()
        self.setMinimumHeight(960)
        self.resize(self.width(), max(960, self.height()))
        self.assignment_id += 1
        self.assignment = QuickAssignment(copy.deepcopy(self.active_profile()))
        if self.backend:
            self.assignment.modifiers.update(key for key in MODIFIERS if self.backend.physical_down(key))
        self.intro_title.hide()
        self.intro_hint.hide()
        self.assignment_panel.show()
        self.quick_assign.setEnabled(False)
        self.profiles.setEnabled(False)
        self.enabled.setEnabled(False)
        self.update_assignment()
        self.refresh_scope()

    def assignment_event(self, signal, down, now, session_id):
        if self.assignment is None or session_id != self.assignment_id:
            return
        self.assignment.event(signal, down, now)
        self.update_assignment()

    def update_assignment(self):
        assignment = self.assignment
        slot = assignment.slot
        self.map.highlight(slot)
        self.assignment_back.setEnabled(assignment.index > 0)
        self.assignment_skip.setEnabled(slot is not None and assignment.pending is None)
        self.assignment_save.setVisible(slot is None)
        if slot is None:
            self.assignment_title.setText("Inputs recorded")
            self.assignment_hint.setText("Save inputs to apply this recording, or go back to change a control.")
            self.assignment_progress.setText(f"{len(assignment.recorded)} recorded · Other inputs stay as they were")
            return
        self.assignment_title.setText(f"{assignment.index + 1} / 12 · {dict(SLOTS)[slot]}")
        direction = "counterclockwise" if "ccw" in slot else "clockwise"
        if slot in ROTATIONS:
            instruction = (f"Hold the dial down and turn {direction}." if slot.startswith("pressed_") else
                           f"Turn the dial {direction} without pressing it.")
            instruction += " Waiting for three matching turn signals."
        else:
            instruction = "Press and release the highlighted button once." if slot != "neutral" else "Press and release the dial once, without turning it."
        self.assignment_hint.setText(instruction)
        self.assignment_progress.setText(assignment.message or "Waiting for input…")

    def assignment_go_back(self):
        if self.assignment:
            self.assignment.back()
            self.update_assignment()

    def assignment_go_skip(self):
        if self.assignment:
            self.assignment.skip()
            self.update_assignment()

    def cancel_assignment(self):
        self.assignment_id += 1
        self.assignment = None
        self.map.highlight(None)
        self.assignment_panel.hide()
        self.intro_title.show()
        self.intro_hint.show()
        self.quick_assign.setEnabled(True)
        self.profiles.setEnabled(True)
        self.enabled.setEnabled(True)
        self.setMinimumHeight(self.assignment_original_minimum)
        self.resize(self.assignment_original_size)
        self.reset()
        self.refresh_scope()

    def save_assignment(self):
        if self.assignment is None or self.assignment.slot is not None:
            return
        try:
            self.persist(self.assignment.apply(self.config))
            self.cancel_assignment()
        except Exception as exc:
            self.assignment_progress.setText(str(exc) + " Use Back to change the conflicting input.")

    def clear_history(self):
        if self.live:
            self.live.snapshot()
        self.history_entries.clear()
        self.history.clear()
        self.history_empty.show()

    def record_activity(self, event, preview=False):
        entry = dict(event, preview=preview, time=time.strftime("%H:%M:%S"))
        self.history_entries.appendleft(entry)
        self.history_empty.hide()
        prefix = "Preview · " if preview else ""
        text = f"{entry['time']}  {entry['name']} · {entry['input']}\n{entry['gesture']} → {prefix}{entry['action']}\n{entry['profile']}"
        item = QListWidgetItem(text)
        item.setToolTip(text)
        self.history.insertItem(0, item)
        while self.history.count() > self.history_entries.maxlen:
            self.history.takeItem(self.history.count() - 1)
        self.history.scrollToTop()

    def preview_switched(self, profile_id):
        self.reset()
        self.config["active_profile"] = profile_id
        if self.live:
            self.live.configure(self.config)
        elif self.engine:
            self.engine.configure(self.config)
        self.refresh()
        try:
            save(self.path, self.config)
        except Exception as exc:
            self.status.setText("Could not save profile: " + str(exc))
        self.refresh_scope()

    def observe(self, signal, down):
        if down:
            self.physical.add(signal)
            if signal not in MODIFIERS and self.engine:
                self.engine.track("+".join([m for m in MODIFIERS if m in self.physical] + [signal]))
        else:
            self.physical.discard(signal)
            if self.engine and self.accept_input:
                try:
                    self.engine.physical_release(signal)
                except Exception as exc:
                    self.failed(str(exc))

    def reset(self, reset_live=True):
        self.accept_input = False
        self.preview_input = False
        self.generation += 1
        self.physical.clear()
        self.map.clear_held()
        self.preview_engine.reset()
        if self.live:
            if reset_live:
                self.live.reset()
        elif self.engine:
            try:
                self.engine.reset()
            except Exception as exc:
                self.status.setText("Could not release an output: " + str(exc))

    def failed(self, message):
        self.reset()
        self.config["enabled"] = False
        self.enabled.blockSignals(True)
        self.enabled.setChecked(False)
        self.enabled.blockSignals(False)
        self.runtime_error = message
        self.status.setText("Input paused · " + message + " · Enable to retry.")

    def application_state(self, state):
        self.recording_focus = state == Qt.ApplicationState.ApplicationActive
        if self.assignment is not None:
            if state != Qt.ApplicationState.ApplicationActive:
                self.assignment.suspend()
                self.update_assignment()
        self.refresh_scope()

    def refresh_scope(self):
        try:
            self._refresh_scope()
        except Exception as exc:
            self.failed("Could not update the active window: " + str(exc))

    def _refresh_scope(self):
        own = QApplication.applicationState() == Qt.ApplicationState.ApplicationActive
        self.recording_focus = own
        if self.assignment is not None:
            self.accept_input = self.preview_input = False
            if self.live:
                self.live.set_paused(True)
            self.status.setText("Quick assign · Actions paused · " + ("Follow the highlighted control" if own else "Return to Alt Clip Ctrl to continue recording"))
            return
        if self.diagnostic:
            self.preview_input = own and self.config["enabled"] and not self.modal
            return
        if not self.backend or not self.backend.running:
            return
        if self.live:
            self.live.set_paused(self.modal or not self.config["enabled"])
            self.live.sync_scope()
        foreground = self.backend.foreground()
        if foreground:
            own = foreground == "@self"
        token = self.backend.foreground_token()
        changed = (token != getattr(self, "scope_token", None)) if token is not None else foreground != getattr(self, "foreground", "")
        program_changed = foreground != getattr(self, "foreground", "")
        if changed:
            self.scope_previous_generation = self.generation
            self.reset(reset_live=False if self.live else True)
        self.foreground, self.scope_token = foreground, token
        if foreground and foreground != "@self":
            self.last_foreground = foreground
            if (changed or program_changed) and self.config["auto_switch"] and self.engine and not self.live:
                match = next((p for p in self.config["profiles"] if foreground.casefold() in
                    {program.casefold() for program in p["programs"]}), None)
                if match and match["id"] != self.engine.profile_id:
                    self.engine.switch(match["id"])
        allowed = self.config["enabled"] and not own and not self.modal
        if self.accept_input and not allowed:
            self.reset()
        self.accept_input = allowed
        self.preview_input = self.config["enabled"] and own and not self.modal
        self.active_inputs = frozenset(b["input"] for b in self.active_profile()["bindings"].values())
        if not self.config["enabled"]:
            self.status.setText("Input paused · " + self.runtime_error + " · Enable to retry." if self.runtime_error else
                                "Paused · Enable the driver to translate device signals")
        elif own:
            self.status.setText("Preview · Buttons light up and actions appear in history · Switch to your app to send output")
        else:
            self.status.setText("Listening · " + (foreground or "Manual profile") + " · " + self.active_profile()["name"])
        if changed:
            self.scope_input_generation = self.generation

    def active_profile(self):
        return next(p for p in self.config["profiles"] if p["id"] == self.config["active_profile"])

    def refresh(self):
        self.profiles.blockSignals(True)
        self.profiles.clear()
        for profile in self.config["profiles"]:
            self.profiles.addItem(profile["name"], profile["id"])
        self.profiles.setCurrentIndex(self.profiles.findData(self.config["active_profile"]))
        self.profiles.blockSignals(False)
        profile = self.active_profile()
        self.map.refresh(profile)
        self.profile_title.setText(profile["name"])
        count = sum(any(b[g]["kind"] != "none" for g in GESTURES) for b in profile["bindings"].values())
        self.mapping_count.setText(f"{count} of 12 controls configured")
        links = profile["programs"]
        self.program_links.setText("Linked to " + ", ".join(links) if links else "No program linked. Use this profile in any app.")
        self.active_inputs = frozenset(b["input"] for b in profile["bindings"].values())

    def persist(self, result):
        # Commit disk first. A failed write never installs an unsaved configuration.
        save(self.path, result)
        self.config = result
        self.generation += 1
        if self.live:
            self.live.configure(result)
        elif self.engine:
            self.engine.configure(result)
        self.preview_engine.configure(result)
        self.refresh()

    def choose_profile(self):
        profile_id = self.profiles.currentData()
        if not profile_id or profile_id == self.config["active_profile"]:
            return
        try:
            result = copy.deepcopy(self.config)
            result["active_profile"] = profile_id
            self.persist(result)
            self.refresh_scope()
        except Exception as exc:
            self.refresh()
            error(self, exc)

    def engine_switched(self, profile_id):
        self.reset()
        self.config["active_profile"] = profile_id
        self.preview_engine.configure(self.config)
        self.refresh()
        try:
            save(self.path, self.config)
        except Exception as exc:
            self.status.setText("Profile changed for this session; could not save: " + str(exc))
        self.refresh_scope()

    def edit_binding(self, slot):
        if self.assignment is not None:
            return
        self.reset()
        self.modal = True
        try:
            dialog = BindingDialog(self, self.config, slot)
            if dialog.exec():
                self.persist(dialog.result_settings)
        except Exception as exc:
            error(self, exc)
        finally:
            self.modal = False
            self.refresh_scope()

    def open_options(self):
        if self.assignment is not None:
            return
        self.reset()
        self.modal = True
        try:
            dialog = OptionsDialog(self, self.config, self.last_foreground)
            if dialog.exec():
                device_changed = dialog.result_settings["linux_device"] != self.config["linux_device"]
                self.persist(dialog.result_settings)
                if device_changed and not self.diagnostic:
                    if self.backend:
                        self.backend.stop()
                    self.start_backend()
        except Exception as exc:
            error(self, exc)
        finally:
            self.modal = False
            self.refresh_scope()

    def toggle_enabled(self, enabled):
        self.reset()
        self.runtime_error = ""
        try:
            result = copy.deepcopy(self.config)
            result["enabled"] = enabled
            self.persist(result)
            if enabled and not self.diagnostic and (not self.backend or not self.backend.running or getattr(self.backend, "output_failed", False)):
                self.start_backend()
            self.refresh_scope()
        except Exception as exc:
            self.failed(str(exc))

    def closeEvent(self, event):
        self.modal = True
        self.clock.stop()
        self.focus_clock.stop()
        self.reset()
        QApplication.instance().removeEventFilter(self)
        if self.live:
            self.live.stop()
        if self.backend:
            self.backend.stop()
        super().closeEvent(event)
