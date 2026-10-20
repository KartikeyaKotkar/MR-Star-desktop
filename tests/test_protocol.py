"""Protocol regression tests.

Expected frames are hard-coded from the decompiled Android app; they are
not derived from the implementation under test.
"""

from __future__ import annotations

import unittest
from datetime import datetime

from mrstar import protocol


class FrameTests(unittest.TestCase):
    def assertFrame(self, frame: bytes, expected: str) -> None:
        self.assertEqual(frame.hex(), expected)

    def test_power(self) -> None:
        self.assertFrame(protocol.power(True), "bc01010055")
        self.assertFrame(protocol.power(False), "bc01010155")

    def test_color_order(self) -> None:
        self.assertFrame(protocol.color_order(1), "bc02010155")
        self.assertFrame(protocol.color_order(6), "bc02010655")
        # The APK picker only offers 1..6; the builder clamps out-of-range input.
        self.assertFrame(protocol.color_order(0), "bc02010155")
        self.assertFrame(protocol.color_order(99), "bc02010655")

    def test_pixel_count(self) -> None:
        self.assertFrame(protocol.pixel_count(300), "bc0302012c55")
        self.assertFrame(protocol.pixel_count(8), "bc0302000855")
        self.assertFrame(protocol.pixel_count(1), "bc0302000855")
        self.assertFrame(protocol.pixel_count(999), "bc0302012c55")

    def test_brightness(self) -> None:
        self.assertFrame(protocol.brightness(1000), "bc050603e80000000055")
        self.assertFrame(protocol.brightness(3), "bc050600030000000055")
        self.assertFrame(protocol.brightness(0), "bc050600000000000055")

    def test_mode(self) -> None:
        self.assertFrame(protocol.mode(1), "bc0602000155")
        self.assertFrame(protocol.mode(93), "bc0602005d55")
        # Quirk preserved: the APK divides by 255, not 256.
        self.assertFrame(protocol.mode(300), "bc0602012d55")
        # Byte casts in the APK wrap the quotient.
        self.assertFrame(protocol.mode(0xFFFF), "bc0602010055")

    def test_direction(self) -> None:
        self.assertFrame(protocol.direction(True), "bc07010055")
        self.assertFrame(protocol.direction(False), "bc07010155")

    def test_speed(self) -> None:
        self.assertFrame(protocol.speed(50), "bc08013255")
        self.assertFrame(protocol.speed(0), "bc08010055")
        self.assertFrame(protocol.speed(100), "bc08016455")
        self.assertFrame(protocol.speed(101), "bc08016455")

    def test_static_colors(self) -> None:
        # White goes out as hue 0 / saturation 1000 because the APK forces
        # saturation to 1.0 for achromatic colours.
        self.assertFrame(protocol.color_rgb(255, 255, 255), "bc0406000003e8000055")
        self.assertFrame(protocol.color_rgb(255, 0, 0), "bc0406000003e8000055")
        self.assertFrame(protocol.color_rgb(0, 0, 0), "bc0406000003e8000055")
        # Pure green is hue 120, saturation 1000.
        self.assertFrame(protocol.color_rgb(0, 255, 0), "bc0406007803e8000055")
        self.assertFrame(protocol.color_hsv(200, 0.5), "bc040600c801f4000055")

    def test_mic_colors(self) -> None:
        self.assertFrame(protocol.mic_color_rgb(255, 255, 255), "bc0906000003e8000055")
        self.assertFrame(protocol.mic_color_hsv(120, 1.0), "bc0906007803e8000055")

    def test_hue_only(self) -> None:
        self.assertFrame(protocol.hue_only(0), "bc1302000055")
        self.assertFrame(protocol.hue_only(360), "bc1302016855")
        self.assertFrame(protocol.hue_only(999), "bc1302016855")

    def test_microphone_controls(self) -> None:
        self.assertFrame(protocol.mic_source(True), "bc0f010155")
        self.assertFrame(protocol.mic_source(False), "bc0f010055")
        self.assertFrame(protocol.mic_effect(1), "bc11010155")
        self.assertFrame(protocol.mic_effect(4), "bc11010455")
        self.assertFrame(protocol.mic_gain(100), "bc12016455")
        self.assertFrame(protocol.mic_gain(0), "bc12010055")

    def test_request_timer(self) -> None:
        self.assertFrame(protocol.request_timer(), "bc0c010155")

    def test_set_timer(self) -> None:
        monday = (True, False, False, False, False, False, False)
        self.assertFrame(
            protocol.set_timer("on", True, monday, 7, 5),
            "bc0d0601010101070555",
        )
        sunday = (False, False, False, False, False, False, True)
        self.assertFrame(
            protocol.set_timer("off", False, sunday, 23, 59),
            "bc0d0601000040173b55",
        )
        with self.assertRaises(ValueError):
            protocol.set_timer("invalid", True, monday, 0, 0)

    def test_clock_sync(self) -> None:
        frame = protocol.sync_time(datetime(2026, 10, 20, 15, 30, 0))
        # Length byte says 7, 0x55 sits before the weekday, no terminator after.
        self.assertFrame(frame, "bc0b0707ea0a140f1e005502")
        self.assertEqual(len(frame), 12)
        self.assertEqual(frame[2], 7)
        self.assertEqual(frame[-2], 0x55)
        self.assertEqual(frame[-1], 2)

    def test_clock_sync_weekday(self) -> None:
        self.assertEqual(protocol.sync_time(datetime(2026, 10, 19, 0, 0))[-1], 1)
        self.assertEqual(protocol.sync_time(datetime(2026, 10, 25, 0, 0))[-1], 7)


class NotificationTests(unittest.TestCase):
    def test_brightness(self) -> None:
        note = protocol.parse_notification(bytes.fromhex("bc050603e80000000055"))
        self.assertEqual(note.command, protocol.CMD_BRIGHTNESS)
        self.assertEqual(note.kind, "brightness")
        self.assertEqual(note.value, 1000)

    def test_speed(self) -> None:
        note = protocol.parse_notification(bytes.fromhex("bc08013255"))
        self.assertEqual(note.kind, "speed")
        self.assertEqual(note.value, 50)

    def test_mic_gain(self) -> None:
        note = protocol.parse_notification(bytes.fromhex("bc12016455"))
        self.assertEqual(note.kind, "mic_gain")
        self.assertEqual(note.value, 100)

    def test_timer(self) -> None:
        note = protocol.parse_notification(bytes.fromhex("bc0d0601010101070555"))
        self.assertEqual(note.kind, "timer")
        self.assertEqual(
            note.value,
            {
                "slot": "on",
                "enabled": True,
                "weekdays": (True, False, False, False, False, False, False),
                "hour": 7,
                "minute": 5,
            },
        )

    def test_unknown_and_short(self) -> None:
        note = protocol.parse_notification(bytes.fromhex("bc02010655"))
        self.assertEqual(note.kind, "unknown")
        self.assertIsNone(note.value)
        self.assertEqual(note.raw.hex(), "bc02010655")

        note = protocol.parse_notification(b"\xbc")
        self.assertEqual(note.kind, "unknown")
        self.assertEqual(note.command, -1)


class ColorConversionTests(unittest.TestCase):
    def test_achromatic_quirk(self) -> None:
        for color in ((0, 0, 0), (255, 255, 255), (128, 128, 128)):
            hue, saturation, _value = protocol.rgb_to_hsv_android(*color)
            self.assertEqual(hue, 0.0)
            self.assertEqual(saturation, 1.0)

    def test_primary_colors(self) -> None:
        self.assertEqual(protocol.rgb_to_hsv_android(255, 0, 0)[0], 0.0)
        self.assertAlmostEqual(protocol.rgb_to_hsv_android(0, 255, 0)[0], 120.0)
        self.assertAlmostEqual(protocol.rgb_to_hsv_android(0, 0, 255)[0], 240.0)


if __name__ == "__main__":
    unittest.main()
