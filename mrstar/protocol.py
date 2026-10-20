"""Wire protocol for the MR Star BLE light controller.

Everything in this module is derived from the shipped Android app
``com.frok.mrstar`` v1.0.0 (``MR Star - v1.0.0.apk``).  The relevant
decompiled evidence is:

* ``com/findn/MyApplication.java``       - GATT UUIDs, write/notify, retries
* ``com/findn/ui/fragment/AdjustFragment.java``  - power, brightness, colour
* ``com/findn/ui/fragment/ModeFragment.java``    - mode, speed, direction
* ``com/findn/ui/fragment/MicroPhoneFragment.java`` - mic source/effect/gain
* ``com/findn/ui/fragment/TimerFragment.java``   - schedule read/write
* ``com/findn/utils/TimerUtils.java``            - clock sync frame
* ``com/findn/utils/VoiceUtils.java``            - mic colour frames

Frames are ``BC <command> <length> <payload...> 55`` unless noted.  The
clock-sync frame is the one exception; see :func:`sync_time`.
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Sequence

# GATT profile (MyApplication.java).
SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "0000fff3-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000fff4-0000-1000-8000-00805f9b34fb"

# Manufacturer ID the Android app filters advertisements on.  The APK
# compares the raw advertisement bytes against 0x22, 0x20, which is the
# little-endian company identifier 0x2022.
MANUFACTURER_ID = 0x2022

START_BYTE = 0xBC
END_BYTE = 0x55

CMD_POWER = 0x01
CMD_COLOR_ORDER = 0x02
CMD_PIXEL_COUNT = 0x03
CMD_COLOR = 0x04
CMD_BRIGHTNESS = 0x05
CMD_MODE = 0x06
CMD_DIRECTION = 0x07
CMD_SPEED = 0x08
CMD_MIC_COLOR = 0x09
CMD_SYNC_TIME = 0x0B
CMD_READ_TIMER = 0x0C
CMD_SET_TIMER = 0x0D
CMD_MIC_SOURCE = 0x0F
CMD_MIC_EFFECT = 0x11
CMD_MIC_GAIN = 0x12
CMD_HUE_ONLY = 0x13

MIN_BRIGHTNESS = 3
MAX_BRIGHTNESS = 1000
MIN_PIXELS = 8
MAX_PIXELS = 300

COLOR_ORDERS = ("RGB", "RBG", "GRB", "GBR", "BRG", "BGR")
MIC_EFFECTS = {
    1: "Energy",
    2: "Rhythm",
    3: "Spectrum",
    4: "Scroll",
}
# The Android radio IDs are named classic/soft/dynamic/disco but the UI
# labels come from mic_energy/mic_rhythm/mic_spectrum/mic_scroll.

# Commands the Android app retries when a write fails (MyApplication.java).
RETRY_COMMANDS = frozenset({CMD_SYNC_TIME, CMD_READ_TIMER, 0x50})


def _frame(command: int, payload: Sequence[int]) -> bytes:
    payload = bytes(payload)
    return bytes((START_BYTE, command, len(payload))) + payload + bytes((END_BYTE,))


def _u16(value: int) -> bytes:
    value = max(0, min(0xFFFF, int(value)))
    return bytes((value >> 8, value & 0xFF))


def power(on: bool) -> bytes:
    """Turn the strip on (payload 0) or off (payload 1)."""
    return _frame(CMD_POWER, (0 if on else 1,))


def color_order(index: int) -> bytes:
    """Set the RGB wire order.  ``index`` is 1..6 (RGB..BGR)."""
    index = max(1, min(6, int(index)))
    return _frame(CMD_COLOR_ORDER, (index,))


def pixel_count(count: int) -> bytes:
    """Set the number of addressed LEDs (the app allows 8..300)."""
    count = max(MIN_PIXELS, min(MAX_PIXELS, int(count)))
    return _frame(CMD_PIXEL_COUNT, _u16(count))


def brightness(value: int) -> bytes:
    """Set brightness, 3..1000 in the Android UI."""
    return _frame(CMD_BRIGHTNESS, _u16(value) + b"\x00\x00\x00\x00")


def mode(mode_id: int) -> bytes:
    """Select a built-in animation.

    The app encodes the value as ``value / 255, value % 255`` (not 256).
    For every mode exposed by the app (< 255) this is a plain 16-bit
    big-endian value, but the exact arithmetic is preserved.
    """
    mode_id = max(0, min(0xFFFF, int(mode_id)))
    return _frame(CMD_MODE, ((mode_id // 255) & 0xFF, (mode_id % 255) & 0xFF))


def direction(forward: bool) -> bytes:
    """Animation direction: 0 = forward, 1 = reverse."""
    return _frame(CMD_DIRECTION, (0 if forward else 1,))


def speed(value: int) -> bytes:
    """Animation speed, 0..100."""
    value = max(0, min(100, int(value)))
    return _frame(CMD_SPEED, (value,))


def hue_only(hue_degrees: int) -> bytes:
    """Hue-only command (0x13) used by the hidden wheel picker."""
    return _frame(CMD_HUE_ONLY, _u16(max(0, min(360, int(hue_degrees)))))


def mic_source(device_mic: bool) -> bytes:
    """Select the light's own microphone (1) or phone/PC-driven mode (0)."""
    return _frame(CMD_MIC_SOURCE, (1 if device_mic else 0,))


def mic_effect(effect: int) -> bytes:
    """Set device-mic effect: 1 Energy, 2 Rhythm, 3 Spectrum, 4 Scroll."""
    effect = max(1, min(4, int(effect)))
    return _frame(CMD_MIC_EFFECT, (effect,))


def mic_gain(value: int) -> bytes:
    """Device-mic sensitivity, 0..100."""
    value = max(0, min(100, int(value)))
    return _frame(CMD_MIC_GAIN, (value,))


def rgb_to_hsv_android(red: int, green: int, blue: int) -> tuple[float, float, float]:
    """RGB -> HSV with the Android app's saturation quirk.

    ``RgbUtils.getHsvFromRgb`` forces saturation to 1.0 when the source
    colour is achromatic (``h == 0 and s == 0``).  White therefore goes out
    as hue 0 / saturation 1000, exactly like the APK.
    """
    hue, sat, val = colorsys.rgb_to_hsv(red / 255.0, green / 255.0, blue / 255.0)
    hue *= 360.0
    if sat > 1.0 or (hue == 0.0 and sat == 0.0):
        sat = 1.0
    return hue, sat, val


def _hsv_payload(hue_degrees: float, saturation: float) -> bytes:
    # The app truncates both values with a cast to int.
    hue = max(0, min(360, int(hue_degrees)))
    sat = max(0, min(1000, int(saturation * 1000.0)))
    return _u16(hue) + _u16(sat) + b"\x00\x00"


def color_hsv(hue_degrees: float, saturation: float) -> bytes:
    """Static colour from hue (0..360) and saturation (0..1)."""
    return _frame(CMD_COLOR, _hsv_payload(hue_degrees, saturation))


def color_rgb(red: int, green: int, blue: int) -> bytes:
    """Static colour from RGB using the APK's HSV conversion."""
    hue, sat, _ = rgb_to_hsv_android(red, green, blue)
    return _frame(CMD_COLOR, _hsv_payload(hue, sat))


def mic_color_rgb(red: int, green: int, blue: int) -> bytes:
    """Audio-reactive colour frame (0x09) used for phone-mic input."""
    hue, sat, _ = rgb_to_hsv_android(red, green, blue)
    return _frame(CMD_MIC_COLOR, _hsv_payload(hue, sat))


def mic_color_hsv(hue_degrees: float, saturation: float) -> bytes:
    return _frame(CMD_MIC_COLOR, _hsv_payload(hue_degrees, saturation))


def request_timer() -> bytes:
    """Ask the device to report both schedules over the notify channel."""
    return _frame(CMD_READ_TIMER, (1,))


def set_timer(
    slot: str,
    enabled: bool,
    weekdays: Iterable[bool],
    hour: int,
    minute: int,
) -> bytes:
    """Program the "on" or "off" schedule.

    ``weekdays`` has seven entries, Monday first; bit 0 of the payload is
    Monday.  ``slot`` is ``"on"`` or ``"off"``.
    """
    if slot not in ("on", "off"):
        raise ValueError("slot must be 'on' or 'off'")
    mask = 0
    for index, selected in enumerate(tuple(weekdays)[:8]):
        if selected:
            mask |= 1 << index
    payload = bytes(
        (
            1,
            1 if slot == "on" else 0,
            1 if enabled else 0,
            mask & 0xFF,
            max(0, min(23, int(hour))),
            max(0, min(59, int(minute))),
        )
    )
    return _frame(CMD_SET_TIMER, payload)


def sync_time(when: datetime | None = None) -> bytes:
    """Clock-sync frame (0x0B).

    The shipped frame is anomalous: the length byte says 7, the payload has
    eight data bytes, and the 0x55 terminator sits *before* the weekday, so
    the frame ends with the weekday byte.  It is reproduced byte-for-byte.
    Weekday is 1 = Monday .. 7 = Sunday.
    """
    when = when or datetime.now()
    year = _u16(when.year)
    weekday = when.weekday() + 1
    return bytes(
        (
            START_BYTE,
            CMD_SYNC_TIME,
            7,
            year[0],
            year[1],
            when.month,
            when.day,
            when.hour,
            when.minute,
            when.second,
            END_BYTE,
            weekday,
        )
    )


@dataclass(frozen=True)
class Notification:
    """Decoded notification from characteristic 0xFFF4."""

    command: int
    kind: str
    value: object
    raw: bytes


def parse_notification(data: bytes | bytearray) -> Notification:
    """Decode a notification.

    Only the four reports the Android app handles are interpreted; anything
    else is returned as ``kind="unknown"`` with the raw bytes intact.
    """
    raw = bytes(data)
    if len(raw) < 2:
        return Notification(-1, "unknown", None, raw)
    command = raw[1]
    if command == CMD_BRIGHTNESS and len(raw) >= 5:
        return Notification(command, "brightness", (raw[3] << 8) | raw[4], raw)
    if command == CMD_SPEED and len(raw) >= 4:
        return Notification(command, "speed", raw[3], raw)
    if command == CMD_MIC_GAIN and len(raw) >= 4:
        return Notification(command, "mic_gain", raw[3], raw)
    if command == CMD_SET_TIMER and len(raw) >= 9:
        return Notification(
            command,
            "timer",
            {
                "slot": "on" if raw[4] == 1 else "off",
                "enabled": raw[5] == 1,
                "weekdays": tuple(bool((raw[6] >> bit) & 1) for bit in range(7)),
                "hour": raw[7],
                "minute": raw[8],
            },
            raw,
        )
    return Notification(command, "unknown", None, raw)


def hexdump(data: bytes) -> str:
    return " ".join(f"{byte:02X}" for byte in data)
