"""Package an existing Windows build and the portable source. No publish step."""
from pathlib import Path
import importlib.metadata as metadata
import shutil
import sys
import zipfile
import argparse

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--build-dir", type=Path, default=root / "outputs" / "AltClipCtrl")
args = parser.parse_args()
output = args.build_dir.resolve()
if not output.is_relative_to(root) or not (output / "AltClipCtrl.exe").is_file():
    raise RuntimeError("Build the Windows app in this project before packaging it.")
notices = output / "third-party"
notices.mkdir(exist_ok=True)
for name in ("PySide6-Essentials", "shiboken6", "pyinstaller"):
    distribution = metadata.distribution(name)
    target = notices / name
    target.mkdir(exist_ok=True)
    for entry in distribution.files or []:
        if str(entry).endswith("/METADATA") or "license" in entry.name.lower() or "copying" in entry.name.lower():
            source = distribution.locate_file(entry)
            if source.is_file():
                shutil.copyfile(source, target / entry.name)
python_license = Path(sys.base_prefix) / "LICENSE.txt"
if python_license.exists():
    shutil.copyfile(python_license, notices / "Python-LICENSE.txt")
shutil.copyfile(root / "docs" / "AltClipCtrl.md", output / "Read-me.md")
shutil.copyfile(root / "docs" / "AltClipCtrl-Third-Party.md", output / "Third-party.md")
for image in (root / "docs").glob("altclipctrl-*.png"):
    shutil.copyfile(image, output / image.name)
for license_file in (root / "assets" / "licenses").glob("*.txt"):
    shutil.copyfile(license_file, notices / license_file.name)
archive = root / "outputs" / "AltClipCtrl-Windows.zip"
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
    for path in sorted(output.rglob("*")):
        if path.is_file():
            zipped.write(path, path.relative_to(output.parent))
source_archive = root / "outputs" / "AltClipCtrl-Source.zip"
files = [root / name for name in ("README.md", "requirements-altclipctrl.txt", "build-altclipctrl.py",
    "package-altclipctrl.py", "run-altclipctrl.py", "AltClipCtrl.settings.example.xml", "build.ps1", "test.ps1",
    ".gitignore", ".gitattributes")]
for directory in ("altclipctrl", "inbetween", "tests", "docs", "assets", "src"):
    files.extend(path for path in (root / directory).rglob("*") if path.is_file() and "__pycache__" not in path.parts)
with zipfile.ZipFile(source_archive, "w", zipfile.ZIP_DEFLATED) as zipped:
    for path in sorted(set(files)):
        zipped.write(path, path.relative_to(root))
for path in (archive, source_archive):
    print(path, f"{path.stat().st_size / 1024**2:.1f} MB")
