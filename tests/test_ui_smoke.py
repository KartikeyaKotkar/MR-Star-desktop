"""Headless smoke test for the Qt window.

Run with ``QT_QPA_PLATFORM=offscreen`` (set below before importing Qt).
No BLE adapter is touched: the window is created but no scan is started.
"""

from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="mrstar-config-")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mrstar import protocol  # noqa: E402
from mrstar.ui import ICON_PATH, MainWindow  # noqa: E402


class UiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = MainWindow()
        self.window.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.window.close()
        self.app.processEvents()

    def test_pages_exist(self) -> None:
        self.assertTrue(ICON_PATH.is_file())
        self.assertEqual(self.window.stack.count(), 6)
        self.assertEqual(len(self.window._nav_buttons), 6)
        self.assertEqual(self.window.category_list.count(), 7)
        self.assertGreater(self.window.mode_list.count(), 0)
        self.assertEqual(self.window.pixel_spin.minimum(), protocol.MIN_PIXELS)
        self.assertEqual(self.window.pixel_spin.maximum(), protocol.MAX_PIXELS)

    def test_timer_notification_updates_without_echo(self) -> None:
        sent: list[bytes] = []
        self.window.ble.send = lambda frame, coalesce=None: sent.append(bytes(frame))
        self.window._on_notification(
            protocol.parse_notification(bytes.fromhex("bc0d0601010101070555"))
        )
        self.assertTrue(sent == [])
        widgets = self.window._schedule_widgets["on"]
        self.assertTrue(widgets["enabled"].isChecked())
        self.assertEqual(widgets["time"].time().hour(), 7)
        self.assertEqual(widgets["time"].time().minute(), 5)
        self.assertEqual(widgets["weekdays"].weekdays()[0], True)

    def test_schedule_edit_sends(self) -> None:
        sent: list[bytes] = []
        self.window.ble.send = lambda frame, coalesce=None: sent.append(bytes(frame))
        self.window._applying_notification = False
        self.window._initializing = False
        self.window._send_schedule_slot("on")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0:2], b"\xbc\x0d")


if __name__ == "__main__":
    unittest.main()
