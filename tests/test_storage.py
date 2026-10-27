import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from altclipctrl.model import defaults, load, save
from altclipctrl.storage import migrate_settings
from tests.test_altclipctrl import TEMP_ROOT


class RenameSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.old = root / "Inbetween" / "inbetween.settings.json"
        self.new = root / "AltClipCtrl" / "altclipctrl.settings.json"

    def test_existing_profiles_migrate_exactly_and_original_stays_intact(self):
        settings = defaults()
        settings["profiles"][0]["name"] = "My drawing profile · 绘画"
        settings.update(scroll_acceleration=True, scroll_acceleration_factor=4.25)
        save(self.old, settings)
        original = self.old.read_bytes()
        self.assertTrue(migrate_settings(self.new, self.old))
        self.assertEqual(self.new.read_bytes(), original)
        self.assertEqual(self.old.read_bytes(), original)
        self.assertEqual(load(self.new), settings)
        self.assertEqual(list(self.new.parent.glob("*.tmp")), [])

    def test_new_settings_are_never_overwritten_by_an_old_file(self):
        old, new = defaults(), defaults()
        old["profiles"][0]["name"] = "Old"
        new["profiles"][0]["name"] = "Current"
        save(self.old, old)
        save(self.new, new)
        original = self.new.read_bytes()
        self.assertFalse(migrate_settings(self.new, self.old))
        self.assertEqual(self.new.read_bytes(), original)

    def test_missing_old_file_leaves_new_installation_alone(self):
        self.assertFalse(migrate_settings(self.new, self.old))
        self.assertFalse(self.new.exists())

    def test_corrupt_source_is_preserved_for_normal_startup_validation(self):
        self.old.parent.mkdir()
        self.old.write_bytes(b"{invalid json")
        self.assertTrue(migrate_settings(self.new, self.old))
        self.assertEqual(self.new.read_bytes(), self.old.read_bytes())
        with self.assertRaises(json.JSONDecodeError):
            load(self.new)

    def test_failed_copy_does_not_publish_partial_settings(self):
        save(self.old, defaults())
        before = self.old.read_bytes()
        def fail(original, output):
            output.write(b"partial")
            raise OSError("Interrupted copy")
        with patch("altclipctrl.storage.shutil.copyfileobj", side_effect=fail):
            with self.assertRaises(OSError):
                migrate_settings(self.new, self.old)
        self.assertFalse(self.new.exists())
        self.assertEqual(self.old.read_bytes(), before)
        self.assertEqual(list(self.new.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
