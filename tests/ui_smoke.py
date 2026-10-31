"""Offscreen UI interactions and preview rendering. No real keyboard output."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import copy
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QTabWidget
from PySide6.QtGui import QFontDatabase

from altclipctrl import __version__
from altclipctrl.model import DIAL_MODES, DIAL_SLOTS, DIRECTIONAL_ACTIONS, SLOTS, action, defaults, new_profile, validate
from altclipctrl.ui import BindingDialog, MainWindow, OptionsDialog, STYLE


def main():
    app = QApplication([])
    if sys.platform == "win32":
        for name in ("segoeui.ttf", "segoeuib.ttf", "seguisym.ttf"):
            QFontDatabase.addApplicationFont("C:/Windows/Fonts/" + name)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    out = Path("docs")
    out.mkdir(exist_ok=True)
    temp_root = Path(__file__).resolve().parents[1] / "test-results"
    temp_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temp_root) as directory:
        window = MainWindow(Path(directory) / "settings.json", diagnostic=True)
        window.show()
        app.processEvents()
        assert window.windowTitle().startswith(f"Alt Clip Ctrl {__version__}")
        assert len(window.map.buttons) == 12
        assert window.map.buttons["pressed_ccw"].x() < window.map.buttons["ccw"].x() < window.map.buttons["neutral"].x() < window.map.buttons["cw"].x() < window.map.buttons["pressed_cw"].x()
        window.grab().save(str(out / "altclipctrl-main.png"))
        for slot, _ in SLOTS:
            dialog = BindingDialog(window, window.config, slot)
            dialog.show()
            app.processEvents()
            assert dialog.input.text().startswith("F")
            expected = 1 if slot in {"ccw", "cw", "pressed_ccw", "pressed_cw"} else 3
            assert len(dialog.editors) == expected
            for gesture, editor in dialog.editors.items():
                assert editor.kind.findData("profile") >= 0
                assert (editor.kind.findData("hold_key") >= 0) == (gesture != "tap")
                assert (editor.kind.findData("hold_dial") >= 0) == (gesture != "tap")
                assert (editor.kind.findData("shortcut") >= 0) == (gesture == "tap")
                for mode in DIAL_MODES:
                    assert (editor.kind.findData(mode) >= 0) == (gesture != "tap")
                for mode in DIRECTIONAL_ACTIONS:
                    assert (editor.kind.findData(mode) >= 0) == (gesture == "tap")
                for i in range(editor.kind.count()):
                    editor.kind.setCurrentIndex(i)
                    app.processEvents()
                    assert (not editor.key.isHidden()) == (editor.kind.currentData() in {"shortcut", "hold_key"})
                    assert (not editor.reverse_direction.isHidden()) == (editor.kind.currentData() in {"dial_scroll", "dial_cycle"})
            dialog.name.setText("My custom button")
            for editor in dialog.editors.values():
                editor.kind.setCurrentIndex(editor.kind.findData("none"))
            dialog.commit()
            assert dialog.result() == QDialog.DialogCode.Accepted
            assert dialog.result_settings["profiles"][0]["bindings"][slot]["name"] == "My custom button"
            assert window.config["profiles"][0]["bindings"][slot]["name"] != "My custom button"
            dialog.close()
        dialog = BindingDialog(window, window.config, "top_left")
        dialog.editors["tap"].kind.setCurrentIndex(dialog.editors["tap"].kind.findData("shortcut"))
        dialog.editors["tap"].key.combo.setCurrentText("Ctrl+Shift+F24")
        dialog.show()
        app.processEvents()
        dialog.grab().save(str(out / "altclipctrl-button.png"))
        dialog.commit()
        window.persist(dialog.result_settings)
        assert window.mapping_count.text() == "1 of 12 controls configured"
        window.map.buttons["top_left"].setFocus()
        assert "Top left" in window.map.buttons["top_left"].toolTip()

        options = OptionsDialog(window, window.config, "CLIPStudioPaint.exe")
        options.show()
        app.processEvents()
        assert options.windowTitle() == "Alt Clip Ctrl · Options"
        assert not options.acceleration.isChecked()
        assert not options.acceleration_factor.isEnabled()
        assert options.acceleration_factor.value() == 3
        options.acceleration.setChecked(True)
        assert options.acceleration_factor.isEnabled()
        options.acceleration_factor.setValue(4.25)
        tabs = options.findChild(QTabWidget)
        tabs.setCurrentIndex(2)
        app.processEvents()
        options.grab().save(str(out / "altclipctrl-acceleration.png"))
        tabs.setCurrentIndex(0)
        options.duplicate_profile()
        assert len(options.result_settings["profiles"]) == 2
        options.profile_name.setText("Clip Studio Paint")
        options.link_program()
        options.cycle.item(0, 0).setText("Custom pen")
        options.selector.setCurrentIndex(0)
        options.selector.setCurrentIndex(1)
        assert options.profile_name.text() == "Clip Studio Paint"
        assert options.cycle.item(0, 0).text() == "Custom pen"
        options.cycle.selectRow(0)
        options.move_cycle(1)
        assert options.cycle.item(1, 0).text() == "Custom pen"
        options.move_cycle(-1)
        options.grab().save(str(out / "altclipctrl-options.png"))
        options.cycle_name.setText("Tools")
        options.add_cycle_list()
        options.cycle_name.setText("Brushes")
        options.cycle.item(0, 0).setText("Pencil")
        options.cycle.item(0, 1).setText("P")
        options.cycle_selector.setCurrentIndex(0)
        assert options.cycle_name.text() == "Tools"
        tabs.setCurrentIndex(1)
        app.processEvents()
        options.grab().save(str(out / "altclipctrl-cycle-lists.png"))
        options.commit()
        assert options.result() == QDialog.DialogCode.Accepted
        assert options.result_settings["profiles"][1]["programs"] == ["CLIPStudioPaint.exe"]
        assert options.result_settings["scroll_acceleration"]
        assert options.result_settings["scroll_acceleration_factor"] == 4.25
        window.persist(options.result_settings)
        window.profiles.setCurrentIndex(1)
        assert window.active_profile()["name"] == "Clip Studio Paint"
        options = OptionsDialog(window, window.config)
        assert options.acceleration.isChecked() and options.acceleration_factor.value() == 4.25
        options.acceleration.setChecked(False)
        assert not options.acceleration_factor.isEnabled()
        options.delete_profile()
        options.commit()
        assert len(options.result_settings["profiles"]) == 1

        # Own-window input is previewed, with a visible hold and bounded action history.
        result = copy.deepcopy(window.config)
        profile = next(p for p in result["profiles"] if p["id"] == result["active_profile"])
        profile["bindings"]["top_left"]["hold"] = action("hold_key", "Shift")
        profile["bindings"]["cw"]["tap"] = action("scroll_up")
        window.persist(result)
        window.preview_input = True
        window.input_event("F23", True, 1, window.generation, True)
        window.input_event("F23", False, 1.01, window.generation, True)
        assert window.history_entries[0]["action"].startswith("Scroll up")
        window.input_event("F13", True, 2, window.generation, True)
        window.preview_engine.poll(2.301)
        assert window.map.buttons["top_left"].input_held
        assert window.history_entries[0]["action"] == "Hold Shift"
        assert window.history_entries[0]["preview"]
        app.processEvents()
        window.grab().save(str(out / "altclipctrl-history.png"))
        window.input_event("F13", False, 2.4, window.generation, True)
        assert not window.map.buttons["top_left"].input_held
        sample = dict(window.history_entries[0])
        for index in range(6):
            window.record_activity(dict(sample, action=f"Action {index}"))
        assert window.history.count() == len(window.history_entries) == 3
        assert [item["action"] for item in window.history_entries] == ["Action 5", "Action 4", "Action 3"]
        window.clear_history()
        assert window.history.count() == 0

        before = copy.deepcopy(window.config)
        window.start_assignment()
        token = window.assignment_id
        assert window.map.buttons["top_left"].assigning
        assert not window.preview_input and not window.accept_input
        # Stale capture messages from another session must not assign a control.
        window.assignment_event("F1", True, 0, token - 1)
        assert not window.assignment.recorded
        now = 1
        while window.assignment.slot is not None:
            slot = window.assignment.slot
            key = profile["bindings"][slot]["input"]
            for i in range(3 if slot in {"ccw", "cw", "pressed_ccw", "pressed_cw"} else 1):
                window.assignment_event(key, True, now, token)
                if slot == "ccw" and i == 0:
                    assert window.assignment.slot == "ccw"
                    assert not window.assignment_save.isVisible()
                    app.processEvents()
                    window.grab().save(str(out / "altclipctrl-quick-assign.png"))
                window.assignment_event(key, False, now + .01, token)
                now += .1
        assert window.assignment_save.isVisible()
        assert window.config == before, "Quick assignment must not modify live settings before Save"
        window.save_assignment()
        assert window.assignment is None
        assert not any(w.assigning for w in window.map.buttons.values())
        window.start_assignment()
        window.assignment_event("F1", True, 10, window.assignment_id)
        window.assignment_event("F1", False, 10.01, window.assignment_id)
        window.cancel_assignment()
        assert window.config == before, "Cancel must discard recordings"
        # Test the ordinary Qt key path used when no native listener is running.
        window.activateWindow()
        app.processEvents()
        window.start_assignment()
        QTest.keyClick(window, Qt.Key.Key_F13)
        assert window.assignment.recorded["top_left"] == "F13"
        window.cancel_assignment()
        held_dialog = BindingDialog(window, window.config, "top_left")
        held_editor = held_dialog.editors["hold"]
        held_editor.kind.setCurrentIndex(held_editor.kind.findData("dial_scroll"))
        held_editor.reverse_direction.setChecked(True)
        assert held_editor.read() == action("dial_scroll", {"reverse": True})
        held_dialog.findChild(QTabWidget).setCurrentIndex(1)
        held_dialog.show()
        app.processEvents()
        held_dialog.grab().save(str(out / "altclipctrl-dial-scrolling.png"))
        held_editor.kind.setCurrentIndex(held_editor.kind.findData("dial_cycle"))
        held_editor.cycle.setCurrentIndex(1)
        selected_cycle = window.active_profile()["cycle_lists"][1]["id"]
        assert held_editor.read() == action("dial_cycle", {"reverse": True, "cycle_id": selected_cycle})
        app.processEvents()
        held_dialog.grab().save(str(out / "altclipctrl-dial-cycling.png"))
        assert not held_dialog.editors["tap_hold"].reverse_direction.isChecked()
        held_editor.kind.setCurrentIndex(held_editor.kind.findData("dial_modifier"))
        temporary = held_editor.dial_controls
        assert set(temporary.editors) == set(DIAL_SLOTS)
        for editor in temporary.editors.values():
            assert all(editor.kind.findData(mode) == -1 for mode in DIAL_MODES)
        temporary.editors["cw"].kind.setCurrentIndex(temporary.editors["cw"].kind.findData("shortcut"))
        temporary.editors["cw"].key.combo.setCurrentText("F24")
        temporary.select("cw")
        assert held_editor.read()["value"]["cw"] == action("shortcut", "F24")
        held_dialog.findChild(QTabWidget).setCurrentIndex(1)
        held_dialog.show()
        app.processEvents()
        held_dialog.grab().save(str(out / "altclipctrl-dial-mode.png"))
        temporary.grab().save(str(out / "altclipctrl-temporary-dial.png"))
        held_dialog.commit()
        assert held_dialog.result() == QDialog.DialogCode.Accepted
        check = held_dialog.result_settings["profiles"][1]["bindings"]["top_left"]["hold"]
        assert check["value"]["cw"] == action("shortcut", "F24")
        combined = BindingDialog(window, window.config, "top_left")
        combined.findChild(QTabWidget).setCurrentIndex(1)
        editor = combined.editors["hold"]
        editor.kind.setCurrentIndex(editor.kind.findData("hold_dial"))
        combined.show()
        app.processEvents()
        combined.grab().save(str(out / "altclipctrl-hold-and-dial.png"))
        combined.close()
        window.close()
        app.processEvents()
    print("PASS: 12 editors, gesture menus, profiles/cycles, action history, held-button lighting, guided assignment, repeated turns, draft/cancel isolation, Qt recording and previews.")


if __name__ == "__main__":
    main()
