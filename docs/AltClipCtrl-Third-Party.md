# Alt Clip Ctrl third-party components

The Windows build bundles unmodified Python and Qt for Python libraries. The application is a directory build so its shared libraries remain separate and replaceable. No Windows system fonts are redistributed; preview tests load fonts from the test machine.

| Component | Version | Upstream source / license information |
| --- | --- | --- |
| CPython | 3.12.14 (build runtime) | [Python source and license](https://www.python.org/downloads/source/) |
| PySide6 Essentials / Shiboken6 | 6.8.3 | [Qt for Python source](https://code.qt.io/cgit/pyside/pyside-setup.git/) · [Qt licensing](https://doc.qt.io/qt-6/licensing.html) |
| Qt shared libraries | 6.8.3 | [Qt source](https://code.qt.io/cgit/qt/) · [Qt third-party notices](https://doc.qt.io/qt-6/licenses-used-in-qt.html) |
| PyInstaller bootloader | 6.16.0 | [License and bootloader exception](https://pyinstaller.org/en/stable/license.html) |

The installed distribution metadata and Python license accompany the packaged build in `third-party/`. The project uses Qt's open-source distribution. The app's source and build instructions are included in the source archive so it can be rebuilt with modified dependencies.

Linux source installations additionally use [python-evdev](https://github.com/gvalkov/python-evdev) (BSD-3-Clause). macOS source installations use [PyObjC](https://github.com/ronaldoussoren/pyobjc) (MIT). These platform-only dependencies are not present in the Windows build.
