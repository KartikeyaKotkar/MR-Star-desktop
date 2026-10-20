"""Run the MR Star desktop application."""

from __future__ import annotations

import sys

from .ui import MainWindow, create_application


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app = create_application(argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
