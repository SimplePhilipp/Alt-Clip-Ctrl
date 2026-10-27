"""Build on the destination OS: python build-altclipctrl.py (requires PyInstaller)."""
from pathlib import Path
import argparse
import subprocess
import sys

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--dist-root", type=Path, default=root / "outputs")
args = parser.parse_args()
dist_root = args.dist_root.resolve()
destination = (dist_root / "AltClipCtrl").resolve()
if not destination.is_relative_to(root) or destination == root:
    raise RuntimeError("The build destination must remain inside this project.")
if sys.platform == "win32" and (destination / "AltClipCtrl.exe").exists():
    try:
        with (destination / "AltClipCtrl.exe").open("r+b"):
            pass
    except OSError as exc:
        raise RuntimeError("Close the app before replacing this build, or choose another --dist-root.") from exc
command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--windowed", "--onedir",
           "--name", "AltClipCtrl", "--distpath", str(dist_root),
           "--workpath", str(root / "work" / "altclipctrl-build"),
           "--specpath", str(root / "work"),
           "--add-data", str(root / "altclipctrl" / "assets") + ":altclipctrl/assets",
           "--exclude-module", "tkinter", "--exclude-module", "PySide6.QtTest"]
if sys.platform == "win32":
    command += ["--icon", str(root / "assets" / "AltClipCtrl.ico")]
subprocess.run(command + [str(root / "run-altclipctrl.py")], cwd=root, check=True)
print("Built", destination)
