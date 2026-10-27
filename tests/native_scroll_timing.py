"""Opt-in timing test: steady input while the GUI thread is deliberately busy.

All source keys are consumed by the test hook; native wheel events are swallowed
by the test's own mouse hook. No test input reaches user applications.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import faulthandler
from pathlib import Path
import statistics
import sys
import threading
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from altclipctrl.live import LiveInput
from altclipctrl.model import action, defaults
from altclipctrl.platforms import WindowsBackend
from altclipctrl.ui import MainWindow
from tests.native_scroll_integration import ReceiverBackend


def main():
    if sys.platform != "win32":
        return 77
    folder = Path(__file__).resolve().parents[1] / "test-results"
    folder.mkdir(exist_ok=True)
    with (folder / "native-scroll-timing.txt").open("w", buffering=1) as report:
        app = QApplication.instance() or QApplication([])
        window = MainWindow(folder / "timing-test-settings.json", diagnostic=True)
        settings = defaults()
        settings["profiles"][0]["bindings"]["top_left"]["tap_hold"] = action("dial_scroll", {"reverse": False})
        window.config = settings
        window.refresh()
        errors = []
        backend = ReceiverBackend(window.capture, errors.append)
        if WindowsBackend.foreground_token(backend) is None:
            report.write("SKIP: no interactive Windows desktop.\n")
            window.close()
            return 77
        faulthandler.dump_traceback_later(8, file=report)
        window.backend = backend
        window.live = LiveInput(settings, backend, errors.append)
        window.engine = window.live.engine
        window.accept_input, window.preview_input = True, False
        backend.create_receiver()
        backend.start()
        window.live.start()
        finished = threading.Event()
        expected = [-120 if (i // 8) % 2 else 120 for i in range(160)]
        busy = []
        def produce():
            try:
                backend.source("F13", True)
                time.sleep(.01)
                backend.source("F13", False)
                time.sleep(.01)
                backend.source("F13", True)
                for amount in expected:
                    key = "F23" if amount > 0 else "F21"
                    backend.source(key, True)
                    backend.source(key, False)
                    time.sleep(.006)
                backend.source("F13", False)
            except Exception as exc:
                errors.append(str(exc))
            finally:
                finished.set()
        def busy_gui():
            busy.append(time.perf_counter())
            time.sleep(.25)
            busy.append(time.perf_counter())
        producer = threading.Thread(target=produce, daemon=True)
        QTimer.singleShot(20, producer.start)
        QTimer.singleShot(100, busy_gui)
        started = time.monotonic()
        timer = QTimer()
        def check():
            complete = finished.is_set() and len(backend.wheels) == len(expected)
            if not complete and time.monotonic() - started < 5:
                return
            latencies = [(received - sent) * 1000 for sent, received in zip(backend.input_times, backend.receive_times)]
            during_busy = sum(busy[0] <= at <= busy[-1] for at in backend.receive_times) if len(busy) == 2 else 0
            good = (complete and backend.wheels == expected and len(latencies) == len(expected)
                    and not errors and during_busy >= 10 and max(latencies) < 75)
            unavailable = not backend.source_count and not errors
            report.write(("SKIP" if unavailable else "PASS" if good else "FAIL") +
                f": {len(backend.wheels)}/160 fixed one-notch steps; {during_busy} delivered during a 250 ms GUI stall.\n")
            if latencies:
                report.write(f"First step: {latencies[0]:.3f} ms; median: {statistics.median(latencies):.3f} ms; "
                    f"max: {max(latencies):.3f} ms; first 16 mean: {statistics.mean(latencies[:16]):.3f} ms; "
                    f"last 16 mean: {statistics.mean(latencies[-16:]):.3f} ms.\n")
            report.write(f"Errors: {errors}\n")
            window.close()
            backend.close_receiver()
            faulthandler.cancel_dump_traceback_later()
            app.exit(77 if unavailable else 0 if good else 1)
        timer.timeout.connect(check)
        timer.start(25)
        result = app.exec()
    print((folder / "native-scroll-timing.txt").read_text().strip())
    return result


if __name__ == "__main__":
    raise SystemExit(main())
