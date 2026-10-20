"""Run the MR Star desktop application."""

from __future__ import annotations

import ctypes
import multiprocessing
import sys

from PySide6.QtCore import QTimer

from .ui import MainWindow, create_application


def _set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MRStar.Desktop")
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    smoke_test = "--smoke-test" in argv
    if smoke_test:
        argv = [arg for arg in argv if arg != "--smoke-test"]
    _set_windows_app_id()
    app = create_application(argv)
    window = MainWindow()
    window.show()
    if smoke_test:
        QTimer.singleShot(1200, window.close)
    return app.exec()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
