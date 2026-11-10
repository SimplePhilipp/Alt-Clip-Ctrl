from __future__ import annotations

import copy
import math
from collections import deque
from pathlib import Path
import sys
import time

import json

from PySide6.QtCore import Qt, QPointF, QRectF, QSize, Signal, QTimer, QObject, QEvent
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QKeySequence, QPixmap, QShortcut, QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QSpinBox, QDoubleSpinBox, QStackedWidget, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .hue import HueMemory, wheel_defaults
from .pointer import cursor_position
from .engine import Engine
from . import __version__
from .live import LiveInput
from .assignment import QuickAssignment
from .model import ACTIONS, DIAL_MODES, DIAL_SLOTS, GESTURES, GESTURE_NAMES, KEYS, MODIFIERS, ROTATIONS, SLOTS, allowed_actions, defaults, dial_map, import_legacy, load, new_cycle_list, new_profile, normalize, references_cycle, references_profile, save, validate, validate_output
from .platforms import PreviewBackend, WindowsBackend, create_backend

ASSETS = Path(__file__).parent / "assets"

# Two palettes share one stylesheet template. Custom-painted widgets read the
# live palette from THEME, so switching themes only needs a restyle + repaint.
THEMES = {
    "dark": dict(
        bg="#0e1113", panel="#14181b", raised="#1b2024", field="#101316", hover="#232a2f",
        line="#262d32", strong="#3a434a", text="#e7ecee", muted="#98a3a9",
        accent="#33b8bf", accent_hover="#4cc6cc", accent_ink="#06282a", accent_soft="#15292b",
        pressed="#4a545b", pressed_text="#ffffff", ok="#4cc38a", warn="#e0a84a", record="#e5534b",
        tooltip="#e7ecee", tooltip_text="#0e1113", chevron="chevron-light.png"),
    "light": dict(
        bg="#f3f5f6", panel="#ffffff", raised="#f4f6f7", field="#ffffff", hover="#eaeef0",
        line="#e2e7e9", strong="#c5cdd1", text="#14181a", muted="#5b666c",
        accent="#168b91", accent_hover="#11767c", accent_ink="#ffffff", accent_soft="#e4f3f3",
        pressed="#d1d5d8", pressed_text="#252b2e", ok="#1f8a55", warn="#a8661a", record="#d93f36",
        tooltip="#161616", tooltip_text="#ffffff", chevron="chevron.png"),
}
THEME = dict(THEMES["dark"], name="dark")

STYLE_TEMPLATE = """
QWidget { background: transparent; color: @text; font-family: 'Segoe UI Variable Text', 'Segoe UI', 'Helvetica Neue', sans-serif; font-size: 13px; }
QMainWindow, QDialog, QMessageBox, QInputDialog { background: @bg; }
QLabel#muted { color: @muted; }
QLabel#eyebrow { color: @muted; font-size: 10px; font-weight: 600; letter-spacing: 1.5px; }
QLabel#title { font-size: 26px; font-weight: 600; letter-spacing: -0.5px; }
QLabel#section { font-size: 15px; font-weight: 600; }
QLabel#heading { font-size: 19px; font-weight: 600; letter-spacing: -0.3px; }
QLabel#brand { font-size: 15px; font-weight: 700; }
QLabel#field { color: @muted; font-size: 12px; }
QLabel#chip { background: @raised; color: @muted; border-radius: 12px; padding: 4px 11px; font-size: 12px; }
QLabel#unsaved { color: @warn; font-size: 12px; font-weight: 600; }
QLabel#saved { color: @ok; font-size: 12px; }
QPushButton { border: 1px solid @line; border-radius: 8px; padding: 7px 13px; min-height: 18px; background: @raised; color: @text; }
QPushButton:hover { background: @hover; border-color: @strong; }
QPushButton:pressed { background: @line; }
QPushButton:disabled { color: @muted; background: transparent; border-color: @line; }
QPushButton#primary { background: @accent; border-color: @accent; color: @accent_ink; font-weight: 600; }
QPushButton#primary:hover { background: @accent_hover; border-color: @accent_hover; }
QPushButton#primary:disabled { background: @raised; border-color: @line; color: @muted; font-weight: 600; }
QPushButton#ghost { background: transparent; }
QPushButton#ghost:hover { background: @hover; }
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit { background: @field; color: @text; border: 1px solid @line; border-radius: 8px; padding: 6px 8px; selection-background-color: @accent; selection-color: @accent_ink; }
QComboBox:hover, QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QPlainTextEdit:hover { border-color: @strong; }
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus { border-color: @accent; }
QComboBox:disabled, QLineEdit:disabled { color: @muted; }
QComboBox { min-height: 20px; padding-right: 26px; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox::down-arrow { image: url('CHEVRON'); width: 12px; height: 8px; }
QAbstractSpinBox { padding-right: 24px; }
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button { subcontrol-origin: border; width: 22px; border: none; background: transparent; }
QAbstractSpinBox::up-button { subcontrol-position: top right; margin: 3px 3px 0 0; }
QAbstractSpinBox::down-button { subcontrol-position: bottom right; margin: 0 3px 3px 0; }
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover { background: @hover; border-radius: 4px; }
QAbstractSpinBox::up-arrow { image: url('CHEVUP'); width: 9px; height: 6px; }
QAbstractSpinBox::down-arrow { image: url('CHEVRON'); width: 9px; height: 6px; }
QComboBox QAbstractItemView { background: @panel; color: @text; border: 1px solid @line; selection-background-color: @accent_soft; selection-color: @text; padding: 4px; outline: 0; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid @strong; border-radius: 4px; background: @field; }
QCheckBox::indicator:checked { background: @accent; border: 1px solid @accent; image: none; }
QTabWidget::pane { border: 1px solid @line; border-radius: 10px; top: -1px; background: @panel; }
QTabWidget#gestures::pane { border: none; border-top: 1px solid @line; border-radius: 0; background: transparent; }
QTabBar { qproperty-drawBase: 0; }
QTabBar::tab { padding: 9px 12px; color: @muted; background: transparent; border: none; border-bottom: 2px solid transparent; }
QTabBar::tab:hover { color: @text; }
QTabBar::tab:selected { color: @text; font-weight: 600; border-bottom: 2px solid @accent; }
QTableWidget { background: @field; color: @text; border: 1px solid @line; border-radius: 8px; gridline-color: @line; selection-background-color: @accent_soft; selection-color: @text; }
QHeaderView::section { background: @raised; color: @text; border: none; border-bottom: 1px solid @line; padding: 8px; font-weight: 600; }
QTableCornerButton::section { background: @raised; border: none; }
QToolTip { background: @tooltip; color: @tooltip_text; border: none; padding: 7px 9px; border-radius: 6px; }
QScrollArea { border: none; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle { background: @strong; border-radius: 3px; min-height: 28px; min-width: 28px; }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page { background: none; border: none; width: 0; height: 0; }
QListWidget { border: none; outline: none; }
QListWidget::item { background: @raised; color: @text; border: 1px solid @line; border-radius: 10px; margin-bottom: 8px; padding: 10px; }
QListWidget::item:selected { background: @accent_soft; border-color: @accent; color: @text; }
QFrame#topBar { background: @panel; border: none; border-bottom: 1px solid @line; }
QFrame#historyPanel { background: @panel; border: none; border-right: 1px solid @line; }
QFrame#inspectorPanel { background: @panel; border: none; border-left: 1px solid @line; }
QFrame#inspectorHeader { border: none; border-bottom: 1px solid @line; }
QFrame#statusBar { background: @panel; border: none; border-top: 1px solid @line; }
QFrame#assignmentPanel { background: @accent_soft; border: 1px solid @accent; border-radius: 12px; }
QFrame#card { background: @raised; border: 1px solid @line; border-radius: 10px; }
QFrame#separator { background: @line; border: none; min-height: 1px; max-height: 1px; }
QDialog QTabWidget::pane { background: @panel; }
QFrame#inspectorPanel QDialog { background: @panel; }
"""


def build_style(name=None):
    palette = THEMES[name] if name else THEME
    style = STYLE_TEMPLATE.replace("CHEVRON", (ASSETS / palette["chevron"]).as_posix())
    style = style.replace("CHEVUP", (ASSETS / palette["chevron"].replace("chevron", "chevron-up")).as_posix())
    # Longest keys first so @accent_hover is not consumed by @accent.
    for key in sorted(palette, key=len, reverse=True):
        style = style.replace("@" + key, palette[key])
    return style


def set_theme(name):
    THEME.clear()
    THEME.update(THEMES[name], name=name)
    app = QApplication.instance()
    style = build_style()
    if app is not None and app.styleSheet() != style:
        # Restyling re-polishes every widget, so only do it on a real change.
        app.setStyleSheet(style)
        for widget in app.allWidgets():
            QWidget.update(widget)


STYLE = build_style("dark")


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
    widget.setObjectName("separator")
    widget.setFixedHeight(1)
    return widget


def field(caption, widget):
    """A small caption above an input, as one widget."""
    box = QWidget()
    column = QVBoxLayout(box)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(5)
    column.addWidget(label(caption, "field"))
    column.addWidget(widget)
    return box


def rounded_path(rect, tl, tr, br, bl):
    path = QPainterPath()
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    path.moveTo(x + tl, y)
    path.lineTo(x + w - tr, y)
    path.quadTo(x + w, y, x + w, y + tr)
    path.lineTo(x + w, y + h - br)
    path.quadTo(x + w, y + h, x + w - br, y + h)
    path.lineTo(x + bl, y + h)
    path.quadTo(x, y + h, x, y + h - bl)
    path.lineTo(x, y + tl)
    path.quadTo(x, y, x + tl, y)
    path.closeSubpath()
    return path


class Switch(QCheckBox):
    """A checkbox drawn as a sliding toggle; same signals and API as QCheckBox."""
    def __init__(self, text=""):
        super().__init__(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self):
        metrics = self.fontMetrics()
        return QSize(46 + metrics.horizontalAdvance(self.text()), 34)

    def minimumSizeHint(self):
        return self.sizeHint()

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        on, enabled = self.isChecked(), self.isEnabled()
        track = QRectF(2, (self.height() - 20) / 2, 34, 20)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(THEME["accent"] if on and enabled else THEME["strong"]))
        painter.drawRoundedRect(track, 10, 10)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(track.x() + (17 if on else 3), track.y() + 3, 14, 14))
        painter.setPen(QColor(THEME["text"] if enabled else THEME["muted"]))
        painter.setFont(self.font())
        painter.drawText(QRectF(44, 0, self.width() - 44, self.height()), Qt.AlignmentFlag.AlignVCenter, self.text())
        if self.hasFocus():
            painter.setPen(QPen(QColor(THEME["accent"]), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(track.adjusted(-2, -2, 2, 2), 12, 12)


class ThemeButton(QPushButton):
    """Sun in dark mode (switch to light), moon in light mode (switch to dark)."""
    def __init__(self, callback):
        super().__init__()
        self.setFixedSize(36, 34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(callback)
        self.refresh()

    def refresh(self):
        dark = THEME["name"] == "dark"
        self.setToolTip("Switch to light mode" if dark else "Switch to dark mode")
        self.setAccessibleName(self.toolTip())
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QRectF(self.rect()).center()
        pen = QPen(QColor(THEME["text"]), 1.7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if THEME["name"] == "dark":
            painter.drawEllipse(c, 3.8, 3.8)
            for i in range(8):
                angle = math.radians(i * 45)
                painter.drawLine(QPointF(c.x() + 6.3 * math.cos(angle), c.y() + 6.3 * math.sin(angle)),
                                 QPointF(c.x() + 8.3 * math.cos(angle), c.y() + 8.3 * math.sin(angle)))
        else:
            moon = QPainterPath()
            moon.addEllipse(c, 7, 7)
            bite = QPainterPath()
            bite.addEllipse(QPointF(c.x() + 4, c.y() - 3.2), 6, 6)
            painter.drawPath(moon.subtracted(bite))


class StatusLabel(QLabel):
    """Status text with a coloured state dot; the dot follows the text."""
    def __init__(self, text=""):
        super().__init__(text)
        self.setObjectName("muted")
        self.setIndent(16)
        # Long errors elide instead of widening the window.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)

    def state_color(self):
        text = self.text()
        if text.startswith(("Input paused", "Paused", "Could not", "Quick assign", "Profile changed")):
            return THEME["warn"]
        if text.startswith("Preview"):
            return THEME["accent"]
        return THEME["ok"]

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.state_color()))
        painter.drawEllipse(QRectF(0, self.height() / 2 - 3.5, 7, 7))
        painter.end()
        super().paintEvent(event)


class Legend(QWidget):
    ITEMS = (("accent", "Selected", False), ("pressed", "Pressed now", False), ("muted", "Not set", True))

    def __init__(self):
        super().__init__()
        self.setFixedHeight(20)
        self.setMinimumWidth(320)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(self.font())
        metrics = self.fontMetrics()
        widths = [16 + metrics.horizontalAdvance(text) for _, text, _ in self.ITEMS]
        x = (self.width() - sum(widths) - 18 * (len(widths) - 1)) / 2
        for (key, text, dashed), width in zip(self.ITEMS, widths):
            box = QRectF(x, self.height() / 2 - 5, 10, 10)
            if dashed:
                pen = QPen(QColor(THEME[key]), 1.3, Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
            else:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(THEME[key]))
            painter.drawRoundedRect(box, 3, 3)
            painter.setPen(QColor(THEME["muted"]))
            painter.drawText(QRectF(x + 16, 0, width, self.height()), Qt.AlignmentFlag.AlignVCenter, text)
            x += width + 18


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
        owner = self.window()
        while owner is not None and not isinstance(owner, MainWindow):
            owner = owner.parentWidget()
        previous_modal = owner.modal if owner else False
        if owner:
            owner.reset()
            owner.modal = True
            owner.refresh_scope()
        try:
            dialog = Recorder(self, self.single)
            if dialog.exec():
                self.combo.setCurrentText(dialog.value)
        finally:
            if owner:
                owner.modal = previous_modal
                owner.refresh_scope()

    def text(self):
        return self.combo.currentText().strip()


class ActionEditor(QWidget):
    def __init__(self, output, profiles, allow_hold, default_dial=None, active_profile=None, choices=None, separate_dial=False):
        super().__init__()
        self.separate_dial = separate_dial
        if separate_dial and output["kind"] != "hold_dial":
            output = {"kind": "hold_dial", "value": {
                "without_dial": copy.deepcopy(output) if output["kind"] not in DIAL_MODES else {"kind": "none", "value": ""},
                "with_dial": copy.deepcopy(output) if output["kind"] in DIAL_MODES else {"kind": "none", "value": ""}}}
        self.profiles = profiles
        self.cycle_profile = active_profile or profiles[0]
        self.initial_output = copy.deepcopy(output)
        self.default_dial = default_dial
        self.dial_controls = None
        self.split = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.kind = QComboBox()
        for key, text in allowed_actions(allow_hold).items():
            if choices is None or key in choices:
                self.kind.addItem(text, key)
        layout.addWidget(self.kind)
        self._key = None
        self._profile_picker = None
        self._cycle = None
        self._cycle_picker = None
        self.allow_hold = allow_hold
        self.initial_dial_mapping = copy.deepcopy(output["value"] if output["kind"] == "dial_modifier" else default_dial or dial_map())
        self.split_container = QWidget()
        self.split_layout = QVBoxLayout(self.split_container)
        self.split_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.split_container)
        self.reverse_direction = Switch("Reverse direction")
        self.reverse_direction.setChecked(bool(output["value"].get("reverse", False)) if output["kind"] in ("dial_scroll", "dial_cycle", "dial_hue") and isinstance(output["value"], dict) else False)
        layout.addWidget(self.reverse_direction)
        self.hint = label("", "muted", True)
        layout.addWidget(self.hint)
        self.kind.setCurrentIndex(max(0, self.kind.findData(output["kind"])))
        self.kind.currentIndexChanged.connect(self.refresh)
        self.refresh()
        if separate_dial:
            self.kind.hide()
        if choices is not None:
            self.hint.hide()

    def refresh(self):
        kind = self.kind.currentData()
        if kind in ("shortcut", "hold_key"):
            self.key.show()
        elif self._key is not None:
            self._key.hide()
        if kind == "profile":
            self.profile.show()
        elif self._profile_picker is not None:
            self._profile_picker.hide()
        if kind in ("cycle_next", "cycle_previous", "dial_cycle"):
            self.cycle_picker.show()
        elif self._cycle_picker is not None:
            self._cycle_picker.hide()
        if kind == "dial_modifier":
            self.ensure_dial_controls()
        if self.dial_controls:
            self.dial_controls.setVisible(kind == "dial_modifier")
        if kind == "hold_dial" and self.split is None:
            value = self.initial_output["value"] if self.initial_output["kind"] == "hold_dial" else {
                "without_dial": {"kind": "hold_key", "value": "Space"}, "with_dial": {"kind": "dial_scroll", "value": {"reverse": False}}}
            self.split = {}
            for part, title, choices in (("without_dial", "Without turning", ("none", "hold_key", "profile") if self.separate_dial else ("none", "hold_key")),
                                         ("with_dial", "With dial", ("none", "dial_scroll", "dial_cycle", "dial_modifier", "dial_hue"))):
                self.split_layout.addWidget(label(title, "section"))
                editor = ActionEditor(value[part], self.profiles, True, self.default_dial, self.cycle_profile, choices)
                self.split[part] = editor
                self.split_layout.addWidget(editor)
        self.split_container.setVisible(kind == "hold_dial")
        self.reverse_direction.setVisible(kind in ("dial_scroll", "dial_cycle", "dial_hue"))
        self.hint.setText({"none": "This gesture sends nothing.", "shortcut": "Send a key or chord once. Example: Ctrl+Shift+F24.",
            "hold_key": "Keep the key or chord down until you release this button.",
            "hold_dial": "Hold alone for the first action. The first turn releases that output and switches to the dial action until you release the button.",
            "cycle_next": "Move forward through the selected cycle list. Manage lists in Options.",
            "cycle_previous": "Move backward through the selected cycle list. Manage lists in Options.",
            "scroll_up": "Scroll at the mouse pointer. Amount and reversal are in Options.",
            "scroll_down": "Scroll at the mouse pointer. Amount and reversal are in Options.",
            "dial_scroll": "While held: clockwise scrolls up and counterclockwise scrolls down, including pressed turns. Amount and reversal are in Options.",
            "dial_cycle": "While held: clockwise moves forward and counterclockwise moves backward through the selected cycle list.",
            "dial_modifier": "Choose temporary outputs for all five dial controls. Release this button to restore the normal dial actions.",
            "dial_hue": "While held, turn to click around the fixed hue wheel. Set its position and step in Options → Hue wheel.",
            "hue_next": "Click the next clockwise hue point. Configure the wheel in Options → Hue wheel.",
            "hue_previous": "Click the next counterclockwise hue point. Configure the wheel in Options → Hue wheel.",
            "profile": "Activate this profile and release any held output."}.get(kind, ""))

    def read(self):
        kind = self.kind.currentData()
        if kind == "hold_dial":
            value = {part: editor.read() for part, editor in self.split.items()}
            if self.separate_dial:
                if value["with_dial"]["kind"] == "none":
                    return value["without_dial"]
                if value["without_dial"]["kind"] == "none":
                    return value["with_dial"]
                if value["without_dial"]["kind"] == "profile":
                    raise ValueError("Switch profile ends this hold. Choose No action under With dial, or choose Hold a key above.")
            return {"kind": kind, "value": value}
        if kind in ("cycle_next", "cycle_previous", "dial_cycle"):
            value = {"cycle_id": self.cycle.currentData()}
            if kind == "dial_cycle":
                value["reverse"] = self.reverse_direction.isChecked()
            return {"kind": kind, "value": value}
        return {"kind": kind, "value": self.key.text() if kind in ("shortcut", "hold_key") else
                self.profile.currentData() if kind == "profile" else copy.deepcopy(self.dial_mapping) if kind == "dial_modifier" else
                {"reverse": self.reverse_direction.isChecked()} if kind in ("dial_scroll", "dial_hue") else ""}

    @property
    def key(self):
        if self._key is None:
            output = self.initial_output
            self._key = KeyEditor(output["value"] if output["kind"] in ("shortcut", "hold_key") else "B", held=self.allow_hold)
            self.layout().insertWidget(1, self._key)
            self._key.setVisible(self.kind.currentData() in ("shortcut", "hold_key"))
        return self._key

    @property
    def profile(self):
        if self._profile_picker is None:
            self._profile_picker = QComboBox()
            for profile in self.profiles:
                self._profile_picker.addItem(profile["name"], profile["id"])
            if self.initial_output["kind"] == "profile":
                self._profile_picker.setCurrentIndex(self._profile_picker.findData(self.initial_output["value"]))
            self.layout().insertWidget(1, self._profile_picker)
            self._profile_picker.setVisible(self.kind.currentData() == "profile")
        return self._profile_picker

    def ensure_cycle_picker(self):
        if self._cycle_picker is None:
            self._cycle_picker = QWidget()
            form = QFormLayout(self._cycle_picker)
            form.setContentsMargins(0, 0, 0, 0)
            self._cycle = QComboBox()
            for cycle in self.cycle_profile["cycle_lists"]:
                self._cycle.addItem(cycle["name"], cycle["id"])
            output = self.initial_output
            if output["kind"] in ("cycle_next", "cycle_previous", "dial_cycle") and isinstance(output["value"], dict) and "cycle_id" in output["value"]:
                self._cycle.setCurrentIndex(self._cycle.findData(output["value"]["cycle_id"]))
            form.addRow("Cycle list", self._cycle)
            self.layout().insertWidget(1, self._cycle_picker)
            self._cycle_picker.setVisible(self.kind.currentData() in ("cycle_next", "cycle_previous", "dial_cycle"))

    @property
    def cycle_picker(self):
        self.ensure_cycle_picker()
        return self._cycle_picker

    @property
    def cycle(self):
        self.ensure_cycle_picker()
        return self._cycle

    def ensure_dial_controls(self):
        if self.dial_controls is None:
            self.dial_controls = DialControlsEditor(self.initial_dial_mapping, self.profiles, self.cycle_profile)
            self.layout().insertWidget(self.layout().indexOf(self.split_container), self.dial_controls)
        return self.dial_controls

    @property
    def dial_mapping(self):
        return self.dial_controls.read() if self.dial_controls else copy.deepcopy(self.initial_dial_mapping)

    @dial_mapping.setter
    def dial_mapping(self, mapping):
        self.initial_dial_mapping = copy.deepcopy(mapping)
        if self.dial_controls is not None:
            self.dial_controls.set_mapping(mapping)


class DialControlsEditor(QWidget):
    """The main page's five dial buttons, with one action visible at a time."""
    def __init__(self, mapping, profiles, active_profile):
        super().__init__()
        self.profiles, self.active_profile = profiles, active_profile
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label("Click a dial control to choose its action.", "muted"))
        row = QHBoxLayout()
        row.setSpacing(7)
        self.buttons = {}
        symbols = ("↺", "↺", "●", "↻", "↻")
        captions = ("PRESS", "TURN", "PRESS", "TURN", "PRESS")
        for slot, symbol, caption in zip(DIAL_SLOTS, symbols, captions):
            widget = DeviceButton(slot)
            widget.number, widget.caption = symbol, caption
            widget.setMinimumSize(56, 52)
            widget.setMaximumHeight(52)
            widget.setAccessibleName(dict(SLOTS)[slot])
            widget.clicked.connect(lambda checked=False, s=slot: self.select(s))
            self.buttons[slot] = widget
            row.addWidget(widget, 1)
        layout.addLayout(row)
        self.selection = label("", "section")
        layout.addWidget(self.selection)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)
        self.set_mapping(mapping)

    def set_mapping(self, mapping):
        while self.stack.count():
            widget = self.stack.widget(0)
            self.stack.removeWidget(widget)
            widget.deleteLater()
        self.editors = {}
        for slot in DIAL_SLOTS:
            editor = ActionEditor(copy.deepcopy(mapping[slot]), self.profiles, False, active_profile=self.active_profile)
            editor.kind.currentIndexChanged.connect(self.refresh_tooltips)
            self.editors[slot] = editor
            self.stack.addWidget(editor)
        self.select("cw")
        self.refresh_tooltips()

    def select(self, slot):
        self.stack.setCurrentWidget(self.editors[slot])
        self.selection.setText(dict(SLOTS)[slot])
        for key, widget in self.buttons.items():
            widget.assigning = key == slot
            widget.update()

    def refresh_tooltips(self):
        for slot, widget in self.buttons.items():
            widget.setToolTip(dict(SLOTS)[slot] + "\n" + self.editors[slot].kind.currentText())

    def read(self):
        return {slot: editor.read() for slot, editor in self.editors.items()}


class BindingDialog(QDialog):
    def __init__(self, parent, settings, slot, embedded=False):
        super().__init__(parent)
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
        self.result_settings = copy.deepcopy(settings)
        self.slot = slot
        self.profile = next(p for p in self.result_settings["profiles"] if p["id"] == settings["active_profile"])
        binding = self.profile["bindings"][slot]
        self.setWindowTitle("Configure · " + binding["name"])
        self.resize(520, 720 if slot not in ROTATIONS else 440)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header: what is being edited, and the save controls, always in view.
        header = QFrame()
        header.setObjectName("inspectorHeader")
        head = QVBoxLayout(header)
        head.setContentsMargins(20, 14, 20, 14)
        head.setSpacing(8)
        kind = "BUTTON MAPPING" if slot not in ROTATIONS else "DIAL MAPPING"
        eyebrow = label(kind + "  ·  " + self.profile["name"].upper(), "eyebrow")
        eyebrow.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        head.addWidget(eyebrow)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.heading = label(binding["name"], "heading")
        # The title gives way to the save controls, never the other way round.
        self.heading.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        top.addWidget(self.heading, 1)
        self.unsaved = label("●  Unsaved", "unsaved")
        self.saved = label("✓  Saved", "saved")
        top.addWidget(self.unsaved, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.saved, 0, Qt.AlignmentFlag.AlignVCenter)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Discard)
        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setObjectName("primary")
        self.save_button.setText("Save")
        self.save_button.setToolTip("Save this control (Ctrl+S)")
        self.discard_button = buttons.button(QDialogButtonBox.StandardButton.Discard)
        self.discard_button.setObjectName("ghost")
        self.discard_button.setToolTip("Undo the changes to this control")
        self.save_button.setMinimumWidth(68)
        self.discard_button.setMinimumWidth(80)
        buttons.accepted.connect(self.commit)
        self.discard_button.clicked.connect(self.reject)
        top.addWidget(buttons, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addLayout(top)
        head.addSpacing(4)
        identity = QGridLayout()
        identity.setHorizontalSpacing(12)
        identity.setContentsMargins(0, 0, 0, 0)
        self.name = QLineEdit(binding["name"])
        self.name.textChanged.connect(lambda text: self.heading.setText(text.strip() or dict(SLOTS)[slot]))
        self.input = KeyEditor(binding["input"], single=True)
        self.input.setToolTip("Set your controller to send this single key. The name appears when you hover over its control.")
        identity.addWidget(field("Button name", self.name), 0, 0)
        identity.addWidget(field("Device input", self.input), 0, 1)
        identity.setColumnStretch(0, 1)
        identity.setColumnStretch(1, 1)
        head.addLayout(identity)
        outer.addWidget(header)

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(20, 14, 20, 16)
        layout.setSpacing(10)
        self.editors = {}
        if slot in ROTATIONS:
            layout.addWidget(label("On each turn", "section"))
            layout.addWidget(label("Runs on every notch of the dial in this direction.", "muted"))
            self.editors["tap"] = ActionEditor(binding["tap"], settings["profiles"], False, active_profile=self.profile)
            layout.addWidget(self.editors["tap"])
        else:
            tabs = QTabWidget()
            tabs.setObjectName("gestures")
            for gesture in GESTURES:
                page = QWidget()
                page_layout = QVBoxLayout(page)
                page_layout.setContentsMargins(2, 12, 2, 4)
                page_layout.setSpacing(10)
                help_text = {"tap": "Press and release once.", "hold": "Press and keep holding.",
                             "tap_hold": "Tap, release, then press and keep holding."}[gesture]
                page_layout.addWidget(label(help_text, "muted"))
                self.editors[gesture] = ActionEditor(binding[gesture], settings["profiles"], gesture != "tap", dial_map(self.profile), self.profile,
                                                     separate_dial=gesture != "tap")
                page_layout.addWidget(self.editors[gesture])
                page_layout.addStretch()
                tabs.addTab(page, GESTURE_NAMES[gesture])
            layout.addWidget(tabs, 1)
        layout.addStretch()
        outer.addWidget(body, 1)
        self.set_dirty(False)
        if not embedded:
            # A standalone dialog has no live dirty tracking: plain Save / Cancel.
            self.unsaved.hide()
            self.saved.hide()
            self.save_button.setEnabled(True)
            self.discard_button.setText("Cancel")
            self.discard_button.setEnabled(True)

    def set_dirty(self, dirty):
        self.unsaved.setVisible(dirty)
        self.saved.setVisible(not dirty)
        # Both buttons keep their place, so the header never reflows.
        self.save_button.setEnabled(dirty)
        self.discard_button.setEnabled(dirty)

    def commit(self):
        binding = self.profile["bindings"][self.slot]
        binding["name"], binding["input"] = self.name.text().strip(), self.input.text()
        try:
            for gesture, editor in self.editors.items():
                binding[gesture] = editor.read()
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
        self.selected = False
        self.flash = False
        self.input_held = False
        self.assigning = False
        self.configured = True
        self.name, self.signal, self.number, self.caption = "", "", "", ""

    def colors(self):
        pressed = self.flash or self.input_held
        chosen = self.selected or self.assigning
        if pressed:
            return THEME["pressed"], THEME["pressed"], THEME["pressed_text"], Qt.PenStyle.SolidLine
        if chosen:
            return THEME["accent"], THEME["accent"], THEME["accent_ink"], Qt.PenStyle.SolidLine
        hover = self.underMouse() or self.isDown()
        if not self.configured:
            return (THEME["hover"] if hover else THEME["bg"]), THEME["muted"], THEME["muted"], Qt.PenStyle.DashLine
        return (THEME["hover"] if hover else THEME["raised"]), (THEME["muted"] if hover else THEME["strong"]), THEME["text"], Qt.PenStyle.SolidLine

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        fill, border, text, style = self.colors()
        painter.setBrush(QColor(fill))
        pen = QPen(QColor(border), 1.5, style)
        painter.setPen(pen)
        if self.slot == "top_left":
            painter.drawPath(rounded_path(rect, 30, 9, 9, 9))
        elif self.slot == "top_right":
            painter.drawPath(rounded_path(rect, 9, 30, 9, 9))
        else:
            radius = 8 if self.compact else 11
            painter.drawRoundedRect(rect, radius, radius)
        painter.setPen(QColor(text))
        if self.slot in ROTATIONS or self.slot == "neutral":
            if self.height() >= 58:
                painter.setFont(QFont(self.font().family(), 15))
                painter.drawText(QRectF(rect.x(), rect.y() + 4, rect.width(), rect.height() * .58), Qt.AlignmentFlag.AlignCenter, self.number)
                small = QFont(self.font().family(), 8)
                small.setWeight(QFont.Weight.DemiBold)
                painter.setFont(small)
                painter.drawText(rect.adjusted(0, 0, 0, -6), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, self.caption)
            else:
                # Compact copies (dial modifier editor): glyph only, the name is in the tooltip.
                painter.setFont(QFont(self.font().family(), 13))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.number)
        elif self.slot.startswith("top_"):
            small = QFont("Consolas", 8)
            painter.setFont(small)
            painter.drawText(rect.adjusted(0, 0, 0, -7), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, self.signal)
        if self.hasFocus():
            painter.setPen(QPen(QColor(THEME["muted"]), 1, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            inset = 3 if self.compact else 5
            painter.drawRoundedRect(rect.adjusted(inset, inset, -inset, -inset), 5, 5)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)


class DeviceMap(QWidget):
    selected = Signal(str)

    HEIGHT = 420

    def __init__(self):
        super().__init__()
        self.setMinimumSize(460, self.HEIGHT)
        self.buttons = {}
        for slot, _ in SLOTS:
            widget = DeviceButton(slot, slot.startswith(("left_", "right_")))
            widget.clicked.connect(lambda checked=False, s=slot: self.selected.emit(s))
            self.buttons[slot] = widget
            widget.setParent(self)

    def resizeEvent(self, event):
        cx = self.width() / 2
        x, y, w = cx - 129, max(8, (self.height() - self.HEIGHT) / 2), 258
        self.body_y = y
        positions = {"top_left": (x+10, y+10, 76, 62), "top_middle": (x+91, y+10, 76, 62),
            "top_right": (x+172, y+10, 76, 62), "left_upper": (x-12, y+96, 25, 62),
            "left_lower": (x-12, y+166, 25, 62), "right_upper": (x+w-13, y+96, 25, 62),
            "right_lower": (x+w-13, y+166, 25, 62)}
        for i, slot in enumerate(("pressed_ccw", "ccw", "neutral", "cw", "pressed_cw")):
            positions[slot] = (cx-206+i*84, y+352, 76, 62)
        for slot, rect in positions.items():
            self.buttons[slot].setGeometry(*(int(v) for v in rect))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.width() / 2
        painter.translate(0, getattr(self, "body_y", 8))
        painter.setPen(QPen(QColor(THEME["strong"]), 1.5))
        painter.setBrush(QColor(THEME["panel"]))
        painter.drawRoundedRect(QRectF(cx-129, 0, 258, 300), 40, 40)
        painter.setBrush(QColor(THEME["raised"]))
        painter.drawEllipse(QRectF(cx-77, 110, 154, 154))
        painter.setPen(QPen(QColor(THEME["line"]), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(cx-63, 124, 126, 126))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(THEME["accent"]))
        painter.drawEllipse(QRectF(cx-5, 132, 10, 10))
        painter.setPen(QColor(THEME["muted"]))
        caption = QFont(self.font().family(), 7)
        caption.setWeight(QFont.Weight.DemiBold)
        caption.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.4)
        painter.setFont(caption)
        painter.drawText(QRectF(0, 318, self.width(), 24), Qt.AlignmentFlag.AlignCenter, "DIAL")

    def refresh(self, profile):
        symbols = {"pressed_ccw": "↺", "ccw": "↺", "neutral": "●", "cw": "↻", "pressed_cw": "↻"}
        captions = {"pressed_ccw": "PRESS", "ccw": "TURN", "neutral": "PRESS", "cw": "TURN", "pressed_cw": "PRESS"}
        for i, (slot, _) in enumerate(SLOTS):
            binding = profile["bindings"][slot]
            widget = self.buttons[slot]
            widget.name, widget.signal = binding["name"], binding["input"]
            widget.number = symbols.get(slot, "")
            widget.caption = captions.get(slot, "")
            widget.configured = any(binding.get(g, {"kind": "none"})["kind"] != "none" for g in GESTURES)
            widget.setToolTip(binding["name"] + "\nInput · " + binding["input"] + ("" if widget.configured else "\nNot set · click to choose actions"))
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


class WheelCalibration(QDialog):
    """Two intercepted clicks: wheel centre, then the current marker on its ring."""
    def __init__(self, parent):
        super().__init__(parent)
        self.center = self.result_wheel = None
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(QApplication.primaryScreen().virtualGeometry())
        self.setWindowTitle("Calibrate hue wheel")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 25))
        painter.fillRect(20, 20, self.width()-40, 72, QColor(20, 30, 30, 235))
        painter.setPen(QColor("white"))
        painter.setFont(QFont("Segoe UI", 17))
        message = "Click the centre of your hue wheel" if self.center is None else "Click the CURRENT hue marker on the coloured ring"
        painter.drawText(QRectF(38, 20, self.width()-76, 72), Qt.AlignmentFlag.AlignVCenter, message + "   ·   Esc to cancel")

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        try:
            point = cursor_position()
            if self.center is None:
                self.center = point
                self.update()
            else:
                dx, dy = point[0]-self.center[0], point[1]-self.center[1]
                radius = round(math.hypot(dx, dy))
                if radius < 5:
                    return
                self.result_wheel = dict(center_x=self.center[0], center_y=self.center[1], radius=radius,
                                         angle=math.degrees(math.atan2(dx, -dy)) % 360)
                self.accept()
        except Exception as exc:
            self.reject()
            error(self.parentWidget(), exc)


class OptionsDialog(QDialog):
    def __init__(self, parent, settings, foreground="", hue_angle=None):
        super().__init__(parent)
        self.result_settings = copy.deepcopy(settings)
        self.reset_hue = False
        self.current = settings["active_profile"]
        self.foreground = foreground
        self.loading = False
        self.current_cycle = None
        self.setWindowTitle("Alt Clip Ctrl · Options")
        self.resize(840, 720)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(12)
        title_row = QHBoxLayout()
        title_row.addWidget(label("Options", "title"), 1)
        footer = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        footer.button(QDialogButtonBox.StandardButton.Save).setObjectName("primary")
        footer.button(QDialogButtonBox.StandardButton.Save).setToolTip("Save options (Ctrl+S)")
        footer.button(QDialogButtonBox.StandardButton.Cancel).setObjectName("ghost")
        footer.accepted.connect(self.commit)
        footer.rejected.connect(self.reject)
        QShortcut(QKeySequence(QKeySequence.StandardKey.Save), self).activated.connect(self.commit)
        title_row.addWidget(footer, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(title_row)
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
        tabs.addTab(profiles, "Profiles && programs")

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
        tabs.addTab(cycles, "Actions && cycles")

        advanced = QWidget()
        a = QVBoxLayout(advanced)
        a.setContentsMargins(20, 16, 20, 16)
        a.setSpacing(10)
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
        tabs.addTab(advanced, "Advanced")

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

        hue_page = QWidget()
        hue_layout = QVBoxLayout(hue_page)
        hue_layout.setContentsMargins(20, 16, 20, 16)
        hue_layout.setSpacing(9)
        hue_layout.addWidget(label("Fixed hue wheel", "section"))
        hue_layout.addWidget(label("Each dial step clicks the next point on the visible wheel and returns your pointer. The last angle is remembered, including after restarting. No colour detection is used.", "muted", True))
        hue_layout.addWidget(button("Calibrate on screen…", self.calibrate_hue))
        hue_layout.addWidget(label("The preset matches your 2560 × 1440 layout. Calibrate if display scaling or wheel position differs.", "muted", True))
        hue = settings.get("hue_wheel", wheel_defaults())
        self.hue_fields = {}
        hue_form = QFormLayout()
        for key, title, low, high in (("center_x", "Centre X", -100000, 100000),
                                     ("center_y", "Centre Y", -100000, 100000), ("radius", "Ring radius", 5, 5000),
                                     ("step", "Degrees per notch", .1, 180), ("angle", "Starting angle", 0, 360)):
            field = QSpinBox() if key in ("center_x", "center_y", "radius") else QDoubleSpinBox()
            field.setRange(low, high)
            if isinstance(field, QDoubleSpinBox):
                field.setDecimals(1)
                field.setSuffix("°")
            else:
                field.setSuffix(" px")
            field.setValue(hue[key])
            self.hue_fields[key] = field
            hue_form.addRow(title, field)
        self.hue_program = QLineEdit(hue["program"])
        hue_form.addRow("Target program contains", self.hue_program)
        hue_layout.addLayout(hue_form)
        if hue_angle is not None:
            hue_layout.addWidget(label(f"Remembered angle: {hue_angle:.1f}°", "muted"))
        self.hue_reset = QCheckBox("Reset remembered position to the starting angle when saved")
        hue_layout.addWidget(self.hue_reset)
        hue_layout.addWidget(label("0° is the top; angles increase clockwise. Assign Dial hue wheel under With dial, or assign Hue wheel clockwise/counterclockwise to individual turns. Physical mouse buttons or modifiers pause hue clicks. Linux requires X11 and libXtst.", "muted", True))
        hue_layout.addStretch()
        tabs.addTab(hue_page, "Hue wheel")
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

    def calibrate_hue(self):
        owner = self.parentWidget()
        self.hide()
        if owner:
            owner.hide()
        picker = WheelCalibration(None)
        try:
            if picker.exec():
                for key, value in picker.result_wheel.items():
                    self.hue_fields[key].setValue(value)
                self.hue_reset.setChecked(True)
        finally:
            picker.deleteLater()
            if owner:
                owner.show()
            self.show()
            self.activateWindow()

    def commit(self):
        self.result_settings["hue_wheel"] = {key: field.value() for key, field in self.hue_fields.items()}
        self.result_settings["hue_wheel"]["program"] = self.hue_program.text().strip()
        self.reset_hue = self.hue_reset.isChecked()
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
        self.hue_memory = HueMemory(self.path.with_suffix(".hue.json"))
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
        self.text_focus = False
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
        self.resize(1320, 860)
        self.setMinimumSize(1240, 800)
        self.inspector = None
        self.preferences_path = self.path.with_suffix(".ui.json")
        self.apply_theme(self.load_theme(), remember=False)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header_widget = QFrame()
        header_widget.setObjectName("topBar")
        header_widget.setFixedHeight(60)
        header = QHBoxLayout(header_widget)
        header.setContentsMargins(20, 0, 20, 0)
        header.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(QIcon(str(ASSETS / "AltClipCtrl.ico")).pixmap(26, 26))
        header.addWidget(logo)
        header.addWidget(label("Alt Clip Ctrl", "brand"))
        header.addSpacing(10)
        header.addWidget(label("Profile", "field"))
        self.profiles = QComboBox()
        self.profiles.setMinimumWidth(190)
        self.profiles.setAccessibleName("Profile")
        header.addWidget(self.profiles)
        self.program_links = label("", "chip")
        self.program_links.setMaximumWidth(240)
        self.program_links.setFixedHeight(26)
        header.addWidget(self.program_links, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addStretch()
        self.enabled = Switch("Enabled")
        self.enabled.setChecked(self.config["enabled"])
        self.enabled.toggled.connect(self.toggle_enabled)
        self.enabled.toggled.connect(lambda on: self.enabled.setText("Enabled" if on else "Paused"))
        self.enabled.setText("Enabled" if self.config["enabled"] else "Paused")
        header.addWidget(self.enabled)
        header.addSpacing(4)
        self.quick_assign = button("Quick assign", self.start_assignment)
        header.addWidget(self.quick_assign)
        header.addWidget(button("Cycle lists", lambda: self.open_options(cycle_lists=True)))
        self.theme_button = ThemeButton(self.toggle_theme)
        header.addWidget(self.theme_button)
        header.addWidget(button("Options", self.open_options))
        layout.addWidget(header_widget)
        self.intro_title = label("", "title")
        self.intro_hint = label("", "muted")
        self.intro_title.hide()
        self.intro_hint.hide()
        self.assignment_panel = QFrame()
        self.assignment_panel.setObjectName("assignmentPanel")
        assignment_layout = QVBoxLayout(self.assignment_panel)
        assignment_layout.setContentsMargins(16, 14, 16, 14)
        assignment_layout.setSpacing(8)
        assignment_layout.addWidget(label("QUICK ASSIGN", "eyebrow"))
        self.assignment_title = label("", "section")
        self.assignment_hint = label("", "muted", True)
        self.assignment_progress = label("", "muted", True)
        assignment_layout.addWidget(self.assignment_title)
        assignment_layout.addWidget(self.assignment_hint)
        assignment_layout.addWidget(self.assignment_progress)
        assignment_buttons = QHBoxLayout()
        assignment_buttons.setSpacing(8)
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
        body = QHBoxLayout()
        body.setSpacing(0)
        history_area = QFrame()
        history_area.setObjectName("historyPanel")
        history_area.setFixedWidth(248)
        history_layout = QVBoxLayout(history_area)
        history_layout.setContentsMargins(16, 20, 16, 16)
        history_layout.setSpacing(12)
        history_header = QHBoxLayout()
        history_header.addWidget(label("Recent actions", "section"), 1)
        clear = button("Clear", self.clear_history)
        clear.setObjectName("ghost")
        history_header.addWidget(clear)
        history_layout.addLayout(history_header)
        self.history_empty = label("Press a controller button to see its action here.", "muted", True)
        history_layout.addWidget(self.history_empty)
        self.history = QListWidget()
        self.history.setWordWrap(True)
        self.history.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.history.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        history_layout.addWidget(self.history, 1)
        history_layout.addWidget(label("Your three most recent actions, with the action that was actually called.", "muted", True))
        body.addWidget(history_area)
        map_area = QVBoxLayout()
        map_area.setContentsMargins(24, 22, 24, 16)
        map_area.setSpacing(6)
        self.profile_title = label("", "section")
        map_heading = QVBoxLayout()
        map_heading.setSpacing(2)
        map_heading.addWidget(label("YOUR CONTROLLER", "eyebrow"))
        self.mapping_count = label("", "heading")
        map_heading.addWidget(self.mapping_count)
        map_area.addLayout(map_heading)
        self.map = DeviceMap()
        self.map.selected.connect(self.edit_binding)
        map_area.addWidget(self.map, 1)
        map_area.addWidget(Legend())
        hint = label("Click a control to edit it · hover to see its name", "muted")
        map_area.addWidget(hint, 0, Qt.AlignmentFlag.AlignHCenter)
        body.addLayout(map_area, 1)
        self.inspector_area = QFrame()
        self.inspector_area.setObjectName("inspectorPanel")
        self.inspector_area.setFixedWidth(460)
        self.inspector_layout = QVBoxLayout(self.inspector_area)
        self.inspector_layout.setContentsMargins(0, 0, 0, 0)
        self.inspector_layout.setSpacing(0)
        self.assignment_box = QWidget()
        assignment_box_layout = QVBoxLayout(self.assignment_box)
        assignment_box_layout.setContentsMargins(16, 16, 16, 16)
        assignment_box_layout.addWidget(self.assignment_panel)
        assignment_box_layout.addStretch()
        self.assignment_box.hide()
        self.inspector_layout.addWidget(self.assignment_box, 1)
        self.inspector_empty = QWidget()
        empty = QVBoxLayout(self.inspector_empty)
        empty.setContentsMargins(28, 28, 28, 28)
        empty.addStretch()
        empty.addWidget(label("Nothing selected", "section"), 0, Qt.AlignmentFlag.AlignHCenter)
        empty_hint = label("Select a control on the controller to choose its input and actions.", "muted", True)
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        empty.addWidget(empty_hint)
        empty.addStretch()
        self.inspector_layout.addWidget(self.inspector_empty, 1)
        body.addWidget(self.inspector_area)
        layout.addLayout(body, 1)
        status_bar = QFrame()
        status_bar.setObjectName("statusBar")
        status_bar.setFixedHeight(30)
        status_layout = QHBoxLayout(status_bar)
        status_layout.setContentsMargins(20, 0, 20, 0)
        self.status = StatusLabel("Starting input listener…")
        status_layout.addWidget(self.status, 1)
        status_layout.addWidget(label(f"Alt Clip Ctrl {__version__}", "muted"))
        layout.addWidget(status_bar)
        self.save_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Save), self)
        self.save_shortcut.activated.connect(lambda: self.inspector is not None and self.save_inspector())
        self.dirty_clock = QTimer(self)
        self.dirty_clock.setInterval(250)
        self.dirty_clock.timeout.connect(self.refresh_dirty)
        self.dirty_clock.start()
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
        QApplication.instance().focusChanged.connect(self.editor_focus_changed)
        if not diagnostic:
            self.start_backend()
            self.focus_clock.start()
            if self.load_error:
                QTimer.singleShot(0, lambda: QMessageBox.information(self, "Settings could not be loaded",
                    "The saved file was left untouched. Defaults are shown.\n\n" + self.load_error))
        else:
            self.status.setText("Preview · Controller gestures are shown without sending output")
        self.clock.start()
        self.hue_clock = QTimer(self)
        self.hue_clock.setInterval(1000)
        self.hue_clock.timeout.connect(self.flush_hue_memory)
        self.hue_clock.start()
        self.refresh_scope()

    def capture(self, signal, down, now, injected=False):
        # Live Windows input never waits for Qt or a history/layout update.
        if self.assignment is not None:
            if self.recording_focus:
                self.bridge.assignment.emit(signal, down, now, self.assignment_id)
                return signal not in MODIFIERS
            return False
        if self.text_focus:
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
            self.engine.hue_memory = self.hue_memory
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
        if isinstance(QApplication.focusWidget(), (QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox)):
            return super().eventFilter(watched, event)
        if self.preview_input and signal in self.active_inputs:
            if not event.isAutoRepeat():
                self.input_event(signal, down, time.monotonic(), self.generation, True)
            return True
        return super().eventFilter(watched, event)

    def start_assignment(self):
        if not self.leave_inspector():
            return
        self.close_inspector()
        self.inspector_empty.hide()
        self.reset()
        self.assignment_id += 1
        self.assignment = QuickAssignment(copy.deepcopy(self.active_profile()))
        if self.backend:
            self.assignment.modifiers.update(key for key in MODIFIERS if self.backend.physical_down(key))
        self.intro_title.hide()
        self.intro_hint.hide()
        self.assignment_panel.show()
        self.assignment_box.show()
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
        self.assignment_box.hide()
        self.inspector_empty.show()
        self.intro_title.hide()
        self.intro_hint.hide()
        self.quick_assign.setEnabled(True)
        self.profiles.setEnabled(True)
        self.enabled.setEnabled(True)
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

    def editor_focus_changed(self, *_):
        focus = QApplication.focusWidget()
        editing = (QApplication.applicationState() == Qt.ApplicationState.ApplicationActive and
                   isinstance(focus, (QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox)))
        if editing != self.text_focus:
            self.text_focus = editing
            self.reset()
            self.refresh_scope()

    def application_state(self, state):
        self.editor_focus_changed()
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
            self.preview_input = own and self.config["enabled"] and not self.modal and not self.text_focus
            return
        if not self.backend or not self.backend.running:
            return
        if self.live:
            self.live.set_paused(self.modal or self.text_focus or not self.config["enabled"])
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
        allowed = self.config["enabled"] and not own and not self.modal and not self.text_focus
        if self.accept_input and not allowed:
            self.reset()
        self.accept_input = allowed
        self.preview_input = self.config["enabled"] and own and not self.modal and not self.text_focus
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
        self.program_links.setText(", ".join(links) if links else "Any application")
        self.program_links.setToolTip("Linked programs: " + ", ".join(links) if links else "No program linked. Use this profile in any app.")
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
        if not self.leave_inspector():
            self.refresh()
            return
        self.close_inspector()
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

    def close_inspector(self):
        if self.inspector is not None:
            self.inspector_layout.removeWidget(self.inspector)
            self.inspector.hide()
            self.inspector.deleteLater()
            self.inspector = None
        if self.assignment is None:
            self.inspector_empty.show()
        for widget in self.map.buttons.values():
            widget.selected = False
            widget.update()

    def inspector_is_dirty(self):
        if self.inspector is None:
            return False
        editor = self.inspector
        original = self.inspector_original
        try:
            return (editor.name.text().strip() != original["name"] or editor.input.text() != original["input"] or
                    any(part.read() != original[gesture] for gesture, part in editor.editors.items()))
        except ValueError:
            return True

    def leave_inspector(self):
        if not self.inspector_is_dirty():
            return True
        choice = QMessageBox.question(self, "Unsaved changes", "Save this control before continuing?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save)
        if choice == QMessageBox.StandardButton.Cancel:
            return False
        if choice == QMessageBox.StandardButton.Save:
            return self.save_inspector()
        return True

    def save_inspector(self):
        editor = self.inspector
        if editor is None:
            return True
        try:
            binding = copy.deepcopy(self.inspector_original)
            binding["name"], binding["input"] = editor.name.text().strip(), editor.input.text()
            for gesture, part in editor.editors.items():
                binding[gesture] = part.read()
            result = copy.deepcopy(self.config)
            profile = next((p for p in result["profiles"] if p["id"] == editor.profile["id"]), None)
            if profile is None:
                raise ValueError("This profile was removed. Cancel this edit and select another control.")
            if profile["bindings"][editor.slot] != self.inspector_original:
                raise ValueError("This control changed while you were editing. Cancel and reopen it before saving.")
            profile["bindings"][editor.slot] = binding
            validate(result)
            self.persist(result)
            self.inspector_original = copy.deepcopy(binding)
            self.status.setText("Saved · " + binding["name"])
            return True
        except Exception as exc:
            error(self, exc)
            return False

    def edit_binding(self, slot):
        if (self.inspector is not None and self.inspector.slot == slot and
                self.inspector.profile["id"] == self.config["active_profile"] and
                self.inspector_original == self.active_profile()["bindings"][slot]):
            return
        if self.assignment is not None or not self.leave_inspector():
            return
        self.close_inspector()
        dialog = BindingDialog(self, self.config, slot, embedded=True)
        self.inspector = dialog
        self.inspector_original = copy.deepcopy(dialog.profile["bindings"][slot])
        buttons = dialog.findChild(QDialogButtonBox)
        buttons.accepted.disconnect()
        dialog.discard_button.clicked.disconnect()
        buttons.accepted.connect(self.save_inspector)
        dialog.discard_button.clicked.connect(self.discard_inspector)
        self.inspector_layout.addWidget(dialog, 1)
        self.inspector_empty.hide()
        self.map.buttons[slot].selected = True
        self.map.buttons[slot].update()
        dialog.show()

    def discard_inspector(self):
        """Throw away the draft and show the saved version of the same control."""
        if self.inspector is None:
            return
        slot = self.inspector.slot
        self.close_inspector()
        self.edit_binding(slot)

    def refresh_dirty(self):
        if self.inspector is not None:
            self.inspector.set_dirty(self.inspector_is_dirty())

    def load_theme(self):
        try:
            name = json.loads(self.preferences_path.read_text(encoding="utf-8")).get("theme", "dark")
        except (OSError, ValueError, AttributeError):
            name = "dark"
        return name if name in THEMES else "dark"

    def apply_theme(self, name, remember=True):
        set_theme(name)
        if hasattr(self, "theme_button"):
            self.theme_button.refresh()
        if remember:
            try:
                self.preferences_path.write_text(json.dumps({"theme": name}), encoding="utf-8")
            except OSError as exc:
                self.status.setText("Could not save the theme: " + str(exc))

    def toggle_theme(self):
        self.apply_theme("light" if THEME["name"] == "dark" else "dark")

    def open_options(self, cycle_lists=False):
        if self.assignment is not None or not self.leave_inspector():
            return
        self.close_inspector()
        self.reset()
        self.modal = True
        try:
            dialog = OptionsDialog(self, self.config, self.last_foreground, self.hue_memory.angle(self.config.get("hue_wheel", wheel_defaults())))
            if cycle_lists:
                dialog.findChild(QTabWidget).setCurrentIndex(1)
            if dialog.exec():
                device_changed = dialog.result_settings["linux_device"] != self.config["linux_device"]
                self.persist(dialog.result_settings)
                if dialog.reset_hue:
                    wheel = self.config["hue_wheel"]
                    self.hue_memory.remember(wheel, wheel["angle"])
                    self.flush_hue_memory()
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

    def flush_hue_memory(self):
        try:
            self.hue_memory.flush()
        except OSError as exc:
            self.status.setText("Could not remember hue position: " + str(exc))

    def closeEvent(self, event):
        if not self.leave_inspector():
            event.ignore()
            return
        self.modal = True
        self.clock.stop()
        self.hue_clock.stop()
        self.flush_hue_memory()
        self.focus_clock.stop()
        self.reset()
        QApplication.instance().focusChanged.disconnect(self.editor_focus_changed)
        QApplication.instance().removeEventFilter(self)
        if self.live:
            self.live.stop()
        if self.backend:
            self.backend.stop()
        super().closeEvent(event)
