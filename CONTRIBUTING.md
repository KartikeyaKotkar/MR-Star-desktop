# Contributing

Thanks for helping improve MR Star Desktop. The project controls real BLE
hardware, so protocol changes need evidence and tests.

## Development setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./run.sh
```

On Debian/Ubuntu the runtime also needs BlueZ, `ffmpeg`, and PortAudio:

```bash
sudo apt install bluez ffmpeg libportaudio2
```

## Running tests

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Tests must pass without a BLE adapter. The Qt test runs with
`QT_QPA_PLATFORM=offscreen`.

## Protocol changes

- Keep the frame quirks documented in the README; they are deliberate copies
  of the Android app's behaviour.
- Every new or changed frame needs either decompiled APK evidence or a capture
  from real hardware, plus a regression test in `tests/test_protocol.py`.
- Do not "fix" the clock-sync frame, the `/255` mode encoding, or the inverted
  power payload without hardware evidence.
- Use the protocol console in the app to capture TX/RX traffic when testing a
  new light.

## Reporting hardware results

A useful bug report includes:

- Light model / advertised name and firmware version, if shown.
- Operating system, Bluetooth adapter, and whether BlueZ is used.
- The commands that worked and the exact TX/RX frames from the console.
- Whether the Android app behaves differently on the same light.

## Pull requests

- Keep changes focused and explain the hardware or APK evidence behind them.
- Add or update tests.
- Update the README protocol table when a command changes.
- Do not commit the proprietary `MR Star - v1.0.0.apk`; it is intentionally
  ignored by Git.
