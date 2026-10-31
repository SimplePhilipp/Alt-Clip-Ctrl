"""Named lists retain their own positions and profile-scoped action references."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from altclipctrl.engine import Engine
from altclipctrl.model import action, defaults, dial_map, load, new_cycle_list, new_profile, save, validate
from altclipctrl.ui import BindingDialog, OptionsDialog, DialControlsEditor
from tests.test_altclipctrl import FakeBackend, TEMP_ROOT


class MultipleCycleTests(unittest.TestCase):
    def setUp(self):
        self.settings = defaults()
        self.profile = self.settings["profiles"][0]
        self.tools = self.profile["cycle_lists"][0]
        self.tools["name"] = "Tools"
        self.colors = new_cycle_list("Colors", [{"name": "Red", "shortcut": "R"},
                                                {"name": "Green", "shortcut": "G"},
                                                {"name": "Blue", "shortcut": "L"}])
        self.profile["cycle_lists"].append(self.colors)
        self.backend, self.history = FakeBackend(), []
        self.engine = Engine(self.settings, self.backend, activity=self.history.append)

    def output(self, kind, cycle):
        return action(kind, {"cycle_id": cycle["id"]})

    def test_lists_advance_and_wrap_independently(self):
        for cycle in (self.tools, self.colors, self.tools, self.colors, self.tools, self.colors, self.colors):
            self.engine.execute(self.output("cycle_next", cycle))
        self.assertEqual([key for event, key in self.backend.events if event == "down"], ["B", "R", "E", "G", "B", "L", "R"])
        self.assertEqual(self.engine.positions[(self.profile["id"], self.tools["id"])], 0)
        self.assertEqual(self.engine.positions[(self.profile["id"], self.colors["id"])], 0)

    def test_previous_begins_at_end_of_selected_list(self):
        self.engine.execute(self.output("cycle_previous", self.colors))
        self.engine.execute(self.output("cycle_previous", self.tools))
        self.assertEqual(self.backend.events, [("down", "L"), ("up", "L"), ("down", "E"), ("up", "E")])

    def test_held_dial_uses_selected_list_reverse_and_resumes_previous_owner(self):
        b = self.profile["bindings"]
        b["top_left"]["hold"] = action("dial_cycle", {"cycle_id": self.tools["id"], "reverse": False})
        b["top_middle"]["hold"] = action("dial_cycle", {"cycle_id": self.colors["id"], "reverse": True})
        for signal, down, at in (("F13", True, 1), ("F23", True, 1.01), ("F23", False, 1.02),
                                  ("F14", True, 2), ("F23", True, 2.01), ("F23", False, 2.02),
                                  ("F21", True, 2.03), ("F21", False, 2.04), ("F14", False, 2.05),
                                  ("F23", True, 2.06), ("F23", False, 2.07)):
            self.engine.event(signal, down, at)
        self.assertEqual([key for event, key in self.backend.events if event == "down"], ["B", "L", "R", "E"])
        self.assertIn("Tools", self.history[-1]["action"])
        self.assertIn("Colors", self.history[-2]["action"])

    def test_same_list_ids_in_different_profiles_have_independent_positions(self):
        other = copy.deepcopy(self.profile)
        other["id"], other["name"] = "other", "Other"
        self.settings["profiles"].append(other)
        self.engine.execute(self.output("cycle_next", self.colors))
        self.engine.switch(other["id"])
        self.engine.execute(self.output("cycle_next", self.colors))
        self.engine.switch(self.profile["id"])
        self.engine.execute(self.output("cycle_next", self.colors))
        self.assertEqual([key for event, key in self.backend.events if event == "down"], ["R", "R", "G"])

    def test_direct_shortcuts_resync_matching_lists_only(self):
        self.colors["items"].append({"name": "Shared eraser", "shortcut": "E"})
        self.engine.track("E")
        self.assertEqual(self.engine.positions[(self.profile["id"], self.tools["id"])], 1)
        self.assertEqual(self.engine.positions[(self.profile["id"], self.colors["id"])], 3)
        self.engine.track("G")
        self.assertEqual(self.engine.positions[(self.profile["id"], self.tools["id"])], 1)
        self.assertEqual(self.engine.positions[(self.profile["id"], self.colors["id"])], 1)

    def test_temporary_dial_outputs_select_a_list_and_history_names_it(self):
        mapping = dial_map()
        mapping["cw"] = self.output("cycle_next", self.colors)
        self.profile["bindings"]["top_left"]["hold"] = action("dial_modifier", mapping)
        self.engine.event("F13", True, 1)
        self.engine.event("F23", True, 1.01)
        self.assertEqual(self.backend.events, [("down", "R"), ("up", "R")])
        self.assertEqual(self.history[-1]["action"], "Cycle → Red · R · Colors · via Top left")

    def test_rename_keeps_existing_action_references(self):
        b = self.profile["bindings"]["cw"]
        b["tap"] = self.output("cycle_next", self.colors)
        self.colors["name"] = "Palette"
        validate(self.settings)
        self.engine.event("F23", True, 1)
        self.assertIn("Palette", self.history[-1]["action"])
        self.assertEqual(self.backend.events, [("down", "R"), ("up", "R")])

    def test_invalid_names_ids_entries_and_missing_references_are_rejected(self):
        for change in (lambda p: p["cycle_lists"].clear(),
                       lambda p: p["cycle_lists"][1].update(name=" tools "),
                       lambda p: p["cycle_lists"][1].update(id="default"),
                       lambda p: p["cycle_lists"][1].update(items=[]),
                       lambda p: p["cycle_lists"][1]["items"].append({"name": "Duplicate", "shortcut": "R"}),
                       lambda p: p["bindings"]["cw"].update(tap=action("cycle_next", {"cycle_id": "missing"})),
                       lambda p: p["bindings"]["top_left"].update(hold=action("dial_cycle", {"cycle_id": "missing", "reverse": False}))):
            settings = copy.deepcopy(self.settings)
            change(settings["profiles"][0])
            with self.assertRaises(ValueError):
                validate(settings)

    def test_shortcuts_may_be_reused_across_lists(self):
        self.colors["items"][0]["shortcut"] = "B"
        validate(self.settings)

    def test_legacy_single_list_and_all_cycle_actions_migrate_without_losing_entries(self):
        settings = defaults()
        profile = settings["profiles"][0]
        items = profile.pop("cycle_lists")[0]["items"]
        profile["cycle"] = items
        settings["version"] = 1
        b = profile["bindings"]
        b["cw"]["tap"], b["ccw"]["tap"] = action("cycle_next"), action("cycle_previous")
        b["top_left"]["hold"] = action("dial_cycle", {"reverse": True})
        mapping = dial_map()
        mapping["neutral"] = action("cycle_next")
        b["top_middle"]["hold"] = action("dial_modifier", mapping)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            path = Path(directory) / "old.json"
            path.write_text(json.dumps(settings), encoding="utf-8")
            migrated = load(path)
            p = migrated["profiles"][0]
            self.assertEqual(migrated["version"], 2)
            self.assertNotIn("cycle", p)
            self.assertEqual(p["cycle_lists"], [{"id": "default", "name": "Default", "items": items}])
            for output in (p["bindings"]["cw"]["tap"], p["bindings"]["ccw"]["tap"], p["bindings"]["top_left"]["hold"], p["bindings"]["top_middle"]["hold"]["value"]["neutral"]):
                self.assertEqual(output["value"]["cycle_id"], "default")
            save(path, migrated)
            self.assertEqual(load(path), migrated)


class SharedCyclePositionTests(unittest.TestCase):
    def setUp(self):
        self.settings = defaults()
        self.profile = self.settings["profiles"][0]
        self.a = self.profile["cycle_lists"][0]
        self.a["name"] = "A"
        self.a["items"] = [{"name": f"Tool {i}", "shortcut": str(i)} for i in range(1, 10)]
        self.b = new_cycle_list("B", [{"name": "One", "shortcut": "1"},
                                      {"name": "Five", "shortcut": "5"},
                                      {"name": "Other tool", "shortcut": "F"}])
        self.profile["cycle_lists"].append(self.b)
        validate(self.settings)
        self.backend, self.history = FakeBackend(), []
        self.engine = Engine(self.settings, self.backend, activity=self.history.append)

    def step(self, cycle, direction="next"):
        self.engine.execute(action("cycle_" + direction, {"cycle_id": cycle["id"]}))

    def position(self, cycle):
        return self.engine.positions.get((self.profile["id"], cycle["id"]))

    def test_shared_selection_updates_both_lists_in_either_direction(self):
        self.step(self.b)  # 1
        self.step(self.b)  # 5
        self.assertEqual((self.position(self.a), self.position(self.b)), (4, 1))
        self.step(self.a, "previous")  # 4 leaves B at 5
        self.assertEqual((self.position(self.a), self.position(self.b)), (3, 1))
        self.step(self.a)  # 5
        self.step(self.b, "previous")  # 1
        self.assertEqual((self.position(self.a), self.position(self.b)), (0, 0))

    def test_nonmatching_output_keeps_last_confirmed_anchor_in_both_directions(self):
        for direction, expected in (("next", "6"), ("previous", "4")):
            with self.subTest(direction=direction):
                self.engine.positions.clear()
                for _ in range(3):
                    self.step(self.b)  # 1, 5, F
                self.assertEqual((self.position(self.a), self.position(self.b)), (4, 2))
                self.step(self.a, direction)
                self.assertEqual(self.backend.events[-2:], [("down", expected), ("up", expected)])
                self.assertEqual(self.position(self.b), 2)

    def test_unconfirmed_list_keeps_unknown_anchor_then_starts_at_correct_end(self):
        self.step(self.b, "previous")  # F never confirms A
        self.assertIsNone(self.position(self.a))
        self.step(self.a, "previous")
        self.assertEqual(self.backend.events[-2:], [("down", "9"), ("up", "9")])
        self.assertEqual(self.position(self.b), 2)

    def test_shortcut_outputs_and_manual_shortcuts_share_the_same_memory(self):
        self.engine.execute(action("shortcut", "5"))
        self.assertEqual((self.position(self.a), self.position(self.b)), (4, 1))
        self.engine.execute(action("shortcut", "F"))
        self.engine.track("9")
        self.assertEqual((self.position(self.a), self.position(self.b)), (8, 2))
        self.engine.execute(action("none"))
        self.engine.execute(action("scroll_up"))
        self.assertEqual((self.position(self.a), self.position(self.b)), (8, 2))
        self.step(self.a)  # wraps to shared 1
        self.assertEqual((self.position(self.a), self.position(self.b)), (0, 0))

    def test_shortcut_identity_includes_modifiers_and_ignores_tool_names(self):
        self.a["items"][0] = {"name": "Same name", "shortcut": "Ctrl+1"}
        self.b["items"][0]["name"] = "Same name"
        self.engine.execute(action("shortcut", "1"))
        self.assertIsNone(self.position(self.a))
        self.engine.execute(action("shortcut", "control+1"))
        self.assertEqual((self.position(self.a), self.position(self.b)), (0, 0))
        self.engine.execute(action("shortcut", "Shift+1"))
        self.assertEqual((self.position(self.a), self.position(self.b)), (0, 0))

    def test_generated_shortcuts_do_not_overwrite_other_profiles(self):
        other = copy.deepcopy(self.profile)
        other["id"], other["name"] = "other", "Other"
        self.settings["profiles"].append(other)
        self.engine.switch(other["id"])
        self.engine.execute(action("shortcut", "1"))
        self.engine.switch(self.profile["id"])
        self.engine.execute(action("shortcut", "5"))
        for cycle in other["cycle_lists"]:
            self.assertEqual(self.engine.positions[(other["id"], cycle["id"])], 0)
        self.assertEqual((self.position(self.a), self.position(self.b)), (4, 1))

    def test_failed_output_does_not_confirm_positions(self):
        self.engine.track("1")
        with patch.object(self.backend, "shortcut", side_effect=OSError("Output unavailable")):
            for output in (action("cycle_next", {"cycle_id": self.b["id"]}), action("shortcut", "5")):
                with self.assertRaises(OSError):
                    self.engine.execute(output)
                self.assertEqual((self.position(self.a), self.position(self.b)), (0, 0))

    def test_switching_held_dial_lists_resumes_from_shared_selection_and_keeps_history(self):
        bindings = self.profile["bindings"]
        for slot, cycle in (("top_left", self.a), ("top_middle", self.b)):
            bindings[slot]["hold"] = action("dial_cycle", {"cycle_id": cycle["id"], "reverse": False})
        self.engine.event("F14", True, 1)
        for i in range(3):
            self.engine.event("F23", True, 1.01 + i * .02)
            self.engine.event("F23", False, 1.02 + i * .02)
        self.engine.event("F14", False, 1.1)
        self.engine.event("F13", True, 2)
        self.engine.event("F23", True, 2.01)
        self.assertEqual(self.backend.events[-2:], [("down", "6"), ("up", "6")])
        self.assertEqual(self.history[-1]["action"], "Cycle → Tool 6 · 6 · A · via Top left")
        self.assertEqual(self.position(self.b), 2)


class CycleListUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.settings = defaults()
        self.profile = self.settings["profiles"][0]
        self.palette = new_cycle_list("Palette", [{"name": "Red", "shortcut": "R"}])
        self.profile["cycle_lists"].append(self.palette)
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.close()

    def options(self):
        dialog = OptionsDialog(None, self.settings)
        self.dialogs.append(dialog)
        return dialog

    def test_create_rename_duplicate_switch_and_delete_lists_remain_drafts(self):
        before = copy.deepcopy(self.settings)
        d = self.options()
        d.cycle_name.setText("Tools")
        d.cycle.item(0, 0).setText("Custom pen")
        d.cycle_selector.setCurrentIndex(1)
        d.cycle_name.setText("Colors")
        d.cycle_selector.setCurrentIndex(0)
        self.assertEqual(d.cycle.item(0, 0).text(), "Custom pen")
        self.assertEqual(d.cycle_name.text(), "Tools")
        d.duplicate_cycle_list()
        self.assertEqual(d.cycle_name.text(), "Tools copy")
        d.cycle.item(0, 0).setText("Copied pen")
        d.cycle_selector.setCurrentIndex(0)
        self.assertEqual(d.cycle.item(0, 0).text(), "Custom pen")
        d.cycle_selector.setCurrentIndex(2)
        d.delete_cycle_list()
        self.assertEqual(d.cycle_selector.count(), 2)
        d.add_cycle_list()
        d.cycle_name.setText("Brush sizes")
        d.commit()
        self.assertEqual([c["name"] for c in d.profile()["cycle_lists"]], ["Tools", "Colors", "Brush sizes"])
        self.assertEqual(self.settings, before)

    def test_profile_switching_preserves_pending_list_edits_and_duplicate_is_independent(self):
        d = self.options()
        d.cycle_selector.setCurrentIndex(1)
        d.cycle_name.setText("Colors")
        d.duplicate_profile()
        d.cycle_selector.setCurrentIndex(1)
        self.assertEqual(d.cycle_name.text(), "Colors")
        d.cycle.item(0, 0).setText("Copied red")
        d.selector.setCurrentIndex(0)
        d.cycle_selector.setCurrentIndex(1)
        self.assertEqual(d.cycle.item(0, 0).text(), "Red")
        d.commit()

    def test_used_and_nested_lists_cannot_be_deleted(self):
        for nested in (False, True):
            output = action("cycle_next", {"cycle_id": self.palette["id"]})
            if nested:
                mapping = dial_map()
                mapping["cw"] = output
                self.profile["bindings"]["top_left"]["hold"] = action("dial_modifier", mapping)
            else:
                self.profile["bindings"]["cw"]["tap"] = output
            d = self.options()
            d.cycle_selector.setCurrentIndex(1)
            with patch("altclipctrl.ui.error") as report:
                d.delete_cycle_list()
            report.assert_called_once()
            self.assertEqual(len(d.profile()["cycle_lists"]), 2)

    def test_cycle_action_selectors_use_active_profiles_lists_and_keep_direction(self):
        other = new_profile("Other")
        other["cycle_lists"][0]["name"] = "Other tools"
        other["cycle_lists"].append(new_cycle_list("Other colors"))
        self.settings["profiles"].append(other)
        self.settings["active_profile"] = other["id"]
        d = BindingDialog(None, self.settings, "top_left")
        self.dialogs.append(d)
        editor = d.editors["hold"]
        editor.kind.setCurrentIndex(editor.kind.findData("dial_cycle"))
        self.assertEqual([editor.cycle.itemText(i) for i in range(editor.cycle.count())], ["Other tools", "Other colors"])
        editor.cycle.setCurrentIndex(1)
        editor.reverse_direction.setChecked(True)
        d.commit()
        output = d.profile["bindings"]["top_left"]["hold"]
        self.assertEqual(output, action("dial_cycle", {"cycle_id": other["cycle_lists"][1]["id"], "reverse": True}))
        mapping_dialog = DialControlsEditor(dial_map(), self.settings["profiles"], other)
        self.dialogs.append(mapping_dialog)
        e = mapping_dialog.editors["cw"]
        e.kind.setCurrentIndex(e.kind.findData("cycle_next"))
        e.cycle.setCurrentIndex(1)
        self.assertEqual(mapping_dialog.read()["cw"]["value"]["cycle_id"], other["cycle_lists"][1]["id"])


if __name__ == "__main__":
    unittest.main()
