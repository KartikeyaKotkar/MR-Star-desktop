# MR Star Desktop

A Linux desktop controller for **MR Star** BLE light strips, reconstructed from
the shipped Android app (`MR Star - v1.0.0.apk`, package `com.frok.mrstar`,
versionCode 104, versionName 1.0.0).

The Android app has no public protocol documentation. Everything here comes
from decompiling the APK and reading its resource tables; the resulting frames
are byte-for-byte compatible with the commands the phone sends.

> **Status:** early release. The protocol is verified against the decompiled
> APK, but not yet against physical hardware. Hardware reports are welcome.

![MR Star icon](assets/icon.png)

## Features

- Scan for lights advertising company ID `0x2022`, auto-connect up to seven.
- Power, HSV colour wheel, brightness, colour presets, RGB order, pixel count.
- All 71 animations defined by the APK (58 reachable in its UI plus the hidden
  "Flow" set), organised by category, with speed and direction controls.
- Light's built-in microphone effects (Energy, Rhythm, Spectrum, Scroll),
  sensitivity and source selection.
- Computer microphone mode: live level/spectrum and `0x09` audio-reactive
  colour frames at the same ~5 Hz cadence as `VoiceUtils`.
- Music player: decode files with ffmpeg, play through `sounddevice`, and send
  `0x04` colour frames derived from an FFT of the playing audio.
- Two on/off schedules with weekday masks, device time sync, and a live
  protocol console (TX/RX log, raw frame sender).
- Settings persist through `QSettings`.

## Reverse-engineering basis

The APK was decompiled with JADX 1.5.1. The files that define the protocol are:

| APK source | What it establishes |
| --- | --- |
| `com/findn/MyApplication.java` | GATT UUIDs, company-ID scan filter, write-with-response, retries, seven connections |
| `com/findn/ui/fragment/AdjustFragment.java` | Power, brightness, static colour, pixel-count frames |
| `com/findn/ui/fragment/ModeFragment.java` | Mode ids, speed, direction, category lists |
| `com/findn/ui/fragment/MicroPhoneFragment.java` | Mic source, effect ids, gain |
| `com/findn/ui/fragment/TimerFragment.java` | Schedule frames and notification layout |
| `com/findn/utils/TimerUtils.java` | Clock-sync frame |
| `com/findn/utils/VoiceUtils.java` | Phone-mic colour frames |
| `com/findn/utils/RgbUtils.java` | HSV conversion and its achromatic-colour quirk |

The app's `cmode1` … `cmode117` strings were extracted from the resource table.
`ModeFragment` only builds lists for ids 1–93 (with gaps), so ids 94–117 are
not reachable in the shipped UI and are not included here.

## BLE profile

| Item | Value |
| --- | --- |
| Service | `0000FFF0-0000-1000-8000-00805F9B34FB` |
| Write characteristic | `0000FFF3-0000-1000-8000-00805F9B34FB` (write with response) |
| Notify characteristic | `0000FFF4-0000-1000-8000-00805F9B34FB` |
| Advertisement filter | manufacturer/company ID `0x2022` (bytes `22 20` on air) |
| Maximum connections | 7 (as configured by the APK) |

## Frame format

Most commands are:

```text
BC <command> <payload-length> <payload…> 55
```

All multi-byte integers are big-endian.

| Command | Name | Payload | Example |
| --- | --- | --- | --- |
| `0x01` | Power | `00` = on, `01` = off | `BC 01 01 00 55` |
| `0x02` | Colour order | `01`–`06` = RGB, RBG, GRB, GBR, BRG, BGR | `BC 02 01 06 55` |
| `0x03` | Pixel count | 16-bit, clamped by the app to 8–300 | `BC 03 02 01 2C 55` |
| `0x04` | Static colour | hue 16-bit (0–360), saturation 16-bit (0–1000), `00 00` | `BC 04 06 00 78 03 E8 00 00 55` |
| `0x05` | Brightness | 16-bit (3–1000), then four zero bytes | `BC 05 06 03 E8 00 00 00 00 55` |
| `0x06` | Mode | two bytes | `BC 06 02 00 01 55` |
| `0x07` | Direction | `00` = forward, `01` = reverse | `BC 07 01 00 55` |
| `0x08` | Speed | `00`–`64` | `BC 08 01 32 55` |
| `0x09` | Mic colour | same payload as `0x04` | `BC 09 06 00 78 03 E8 00 00 55` |
| `0x0B` | Clock sync | see anomaly below | `BC 0B 07 07 EA 0A 14 0F 1E 00 55 02` |
| `0x0C` | Read schedule | `01` | `BC 0C 01 01 55` |
| `0x0D` | Set schedule | `01, on/off, enabled, weekday-mask, hour, minute` | `BC 0D 06 01 01 01 01 07 05 55` |
| `0x0F` | Mic source | `01` = light's mic, `00` = phone/PC | `BC 0F 01 01 55` |
| `0x11` | Mic effect | `01` Energy, `02` Rhythm, `03` Spectrum, `04` Scroll | `BC 11 01 04 55` |
| `0x12` | Mic gain | `00`–`100` | `BC 12 01 64 55` |
| `0x13` | Hue only | hue 16-bit | `BC 13 02 01 68 55` |

Schedule weekday masks use bit 0 = Monday through bit 6 = Sunday.

### Protocol quirks preserved from the APK

- **Power is inverted:** payload `0` switches the strip on.
- **Mode encoding uses `/255` and `%255`,** not `/256` and `%256`. For all
  shipped mode ids (< 255) the result is an ordinary 16-bit value, but the
  arithmetic is reproduced exactly.
- **Clock sync is malformed:** the length byte is `7`, eight data bytes follow,
  the `0x55` terminator sits *before* the weekday, and there is no terminator
  after it. Weekday is `1` = Monday … `7` = Sunday. The desktop app sends the
  same bytes.
- **Achromatic colours force saturation to 1.0.** White, grey and black are all
  sent as hue 0 / saturation 1000, matching `RgbUtils.getHsvFromRgb`.
- **The app retries only commands `0x0B`, `0x0C` and `0x50`** after a failed
  write. The desktop transport retries those once and does not retry other
  frames.
- **The Android UI builds a fifth "Flow" category (ids 63–75) but never adds
  its tab to the tab strip.** The catalogue keeps it, marked as hidden.

### Notifications

Notifications on `0xFFF4` are parsed the same way as `TimerFragment`:

| Command | Meaning | Layout used |
| --- | --- | --- |
| `0x05` | Brightness | 16-bit at 0-based bytes 3–4 |
| `0x08` | Speed | 0-based byte 3 |
| `0x0D` | Schedule | slot at 4, enabled at 5, mask at 6, hour at 7, minute at 8 (0-based) |
| `0x12` | Mic gain | 0-based byte 3 |

Anything else is logged as raw bytes.

## Requirements

- Python 3.10+ (tested with Python 3.14).
- `PySide6`, `bleak` 3.x, `numpy`, `sounddevice`.
- Linux with BlueZ and a working D-Bus session (bleak's Linux backend).
- `ffmpeg` on `PATH` for music playback.
- A microphone input device for PC-mic mode (optional).
- PortAudio for microphone/music output (the `sounddevice` backend). On
  Debian/Ubuntu: `sudo apt install libportaudio2`.

On Linux, make sure the adapter is powered and not blocked:

```bash
sudo systemctl enable --now bluetooth
bluetoothctl show          # check "Powered: yes"
rfkill list bluetooth      # must not be soft/hard blocked
```

## Run

Clone the repository, then start the app:

```bash
git clone <repository-url> MR-Star-desktop
cd MR-Star-desktop
./run.sh
```

`run.sh` creates `.venv` if needed, installs missing dependencies, and starts
`python -m mrstar`.

Manual setup:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m mrstar
```

The shipped Android APK is **not** distributed in this repository: it is
proprietary and ignored by Git. Keep your own copy in the repository root if
you want to compare behaviour; the app does not need it at runtime.

## Tests and CI

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The suite covers exact frame bytes, notification decoding, the mode catalogue,
audio DSP, and a headless Qt smoke test (`QT_QPA_PLATFORM=offscreen` is set by
the test). It does not need a BLE adapter.

GitHub Actions runs the same suite on Ubuntu with Python 3.12; the workflow is
in `.github/workflows/ci.yml`. Maintainers can follow
[PUBLISHING.md](PUBLISHING.md) to push the repository and cut a release.

## Project layout

```text
mrstar/protocol.py   frame builders, UUIDs, notification parser
mrstar/modes.py      71-mode catalogue and categories
mrstar/ble.py        threaded bleak transport, scan filter, reconnects
mrstar/audio.py      microphone analyser and ffmpeg/sounddevice player
mrstar/ui.py         PySide6 window, pages, theme, settings
mrstar/__main__.py   application entry point
tests/               protocol, catalogue, DSP and UI smoke tests
.github/workflows/   GitHub Actions CI
```

The BLE event loop runs on a private asyncio thread. Qt talks to it through
`DeviceBridge` signals, so the UI never blocks on GATT operations.

## Limitations

- **No physical MR Star hardware was available during development.** The
  protocol is verified against the decompiled APK, not against a live strip.
  If a command behaves differently on your hardware, use the protocol console
  and compare it with the Android app.
- Music and PC-microphone effects are desktop reimplementations of the Android
  `Visualizer`/`MediaRecorder` logic. They use the same command ids and cadence,
  but the exact colour mapping is an approximation.
- The Android app's hidden "Flow" modes are included, but whether a particular
  firmware build implements all of them is unknown.
- Mode ids 94–117 exist as strings in the APK but are not referenced by the
  shipped UI, so they are intentionally omitted.
- This desktop port does not implement firmware update, OTA, or pairing/bonding
  features.
- Commands are broadcast to every connected light, matching
  `MyApplication.sendDataToBle`.

## Legal note

This is an independent interoperability project. It contains no Android app
code; protocol constants and animation names were derived from the shipped
APK for the purpose of controlling the same hardware from a desktop.

The launcher icon in `assets/icon.png` comes from the Android package and is
used only to identify the device; it is not covered by the MIT license.

The Android APK itself is not distributed here and must not be committed.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, protocol-change
rules, and hardware reporting guidance.

## License

[MIT](LICENSE) © 2026 MR Star Desktop contributors.

