"""python -m altclipctrl [--preview] [--settings PATH]"""
import argparse
import os
from pathlib import Path
import sys

from PySide6.QtCore import QLockFile, QStandardPaths, QTimer, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QMessageBox

from .ui import MainWindow, STYLE
from . import DISPLAY_NAME, __version__
from .storage import migrate_settings


def main():
    parser = argparse.ArgumentParser(description="Alt Clip Ctrl · cross-platform dial driver")
    parser.add_argument("--preview", action="store_true", help="Open the UI without hooks or output")
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--smoke-test", type=Path, help="Write a preview and startup report, then exit; sends no output")
    args = parser.parse_args()
    if sys.platform == "darwin":
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_MacDontSwapCtrlAndMeta)
    app = QApplication(sys.argv[:1])
    # Resolve the previous Qt app identity before applying the new branding.
    app.setApplicationName("Inbetween")
    app.setOrganizationName("Inbetween")
    legacy_directory = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation))
    app.setApplicationName("AltClipCtrl")
    app.setApplicationDisplayName(DISPLAY_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("AltClipCtrl")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    directory = args.settings.resolve().parent if args.settings else Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation))
    directory.mkdir(parents=True, exist_ok=True)
    lock_name = "preview.lock" if args.preview else "driver.lock"
    lock_directories = [directory]
    if not args.settings and legacy_directory != directory and legacy_directory.exists():
        lock_directories.append(legacy_directory)
    locks = []
    for lock_directory in lock_directories:
        lock = QLockFile(str(lock_directory / lock_name))
        if not lock.tryLock(0):
            QMessageBox.information(None, "Alt Clip Ctrl is already running",
                                    "Close the other copy first, including any older Inbetween window.")
            for acquired in reversed(locks):
                acquired.unlock()
            return 0
        locks.append(lock)
    if sys.platform == "win32" and not args.preview and not args.smoke_test:
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        legacy_mutex = kernel.CreateMutexW(None, False, "Local\\CSPToolCyclerStandalone")
        if ctypes.get_last_error() == 183:
            QMessageBox.information(None, "Alt Clip Ctrl is already running",
                                    "Close the other copy first, including the legacy Windows helper or an older Inbetween build.")
            kernel.CloseHandle(legacy_mutex)
            for acquired in reversed(locks):
                acquired.unlock()
            return 0
    else:
        legacy_mutex = None
    settings_path = args.settings or directory / "altclipctrl.settings.json"
    try:
        if not args.settings:
            migrate_settings(settings_path, legacy_directory / "inbetween.settings.json")
        window = MainWindow(settings_path, diagnostic=args.preview or bool(args.smoke_test))
    except Exception:
        if legacy_mutex:
            kernel.CloseHandle(legacy_mutex)
        for acquired in reversed(locks):
            acquired.unlock()
        raise
    window.show()
    if args.smoke_test:
        def verify():
            try:
                if sys.platform == "win32" and os.environ.get("QT_QPA_PLATFORM") == "offscreen":
                    for font in ("segoeui.ttf", "segoeuib.ttf", "seguisym.ttf"):
                        QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / font))
                app.processEvents()
                window.grab().save(str(args.smoke_test.with_suffix(".png")))
                from .platforms import create_backend
                backend = create_backend(lambda *_: False, lambda message: None, window.config["linux_device"])
                try:
                    backend.start()
                    assert backend.running
                finally:
                    backend.stop()
                assert not backend.running
                args.smoke_test.write_text("PASS: packaged UI render, native listener startup/shutdown; no input captured and no output sent.\n", encoding="utf-8")
            except Exception as exc:
                args.smoke_test.write_text("FAIL: " + str(exc), encoding="utf-8")
                app.exit(1)
                return
            window.close()
        QTimer.singleShot(400, verify)
    try:
        return app.exec()
    finally:
        if legacy_mutex:
            kernel.CloseHandle(legacy_mutex)
        for acquired in reversed(locks):
            acquired.unlock()


if __name__ == "__main__":
    raise SystemExit(main())
