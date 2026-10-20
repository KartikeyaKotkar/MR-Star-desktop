# MR Star Rust

A native Rust port of the MR Star desktop controller. It speaks the same BLE
frames as the Python app and the shipped Android APK, but uses egui/OpenGL for
the interface and compiles to a single small executable.

This lives on the `rust` branch next to the unchanged Python implementation.
It is an alternative implementation, not a replacement for `main`.

## Status

- Protocol, mode catalogue, BLE transport, microphone analysis, music playback,
  schedules and settings are implemented.
- The protocol regression tests from the Python code are ported to Rust and
  pass.
- No physical MR Star light was available for live BLE validation. Hardware
  testing is still needed, exactly as for the Python release.
- The port has not yet been through a long-duration hardware soak test.

## Build

```bash
cd rust
cargo test
cargo build --release
./target/release/mrstar
```

Linux build prerequisites:

```bash
sudo apt install \
  build-essential pkg-config \
  libasound2-dev libdbus-1-dev libudev-dev \
  libegl1-mesa-dev libgl1-mesa-dev libwayland-dev \
  libx11-dev libxcb1-dev libxcb-render0-dev libxcb-shape0-dev \
  libxcb-xfixes0-dev libxcursor-dev libxi-dev libxinerama-dev \
  libxkbcommon-dev libxkbcommon-x11-dev libxrandr-dev
```

Runtime prerequisites:

- Linux: BlueZ, D-Bus, ALSA, X11 or Wayland, OpenGL.
- Windows 10/11: Bluetooth enabled. WASAPI is provided by the OS.
- macOS 13+: Bluetooth and microphone permissions.
- Music playback: `ffmpeg` on `PATH`, or `MRSTAR_FFMPEG` pointing at it.

No Python, Qt, PortAudio or bundled runtime is required.

## Features

| Area | Rust port |
| --- | --- |
| Protocol | Byte-identical frames, including inverted power, `/255` mode encoding, malformed clock frame, achromatic HSV quirk, retries for `0x0B`/`0x0C`/`0x50` |
| BLE | Scans for company ID `0x2022`, shows named devices when requested, connects up to seven lights, writes to all, notification parsing, auto-connect, reconnect attempts |
| Modes | All 71 APK modes: 58 reachable plus the hidden 13-mode Flow category |
| Colour | HSV wheel, presets, custom slots, RGB order, pixel count, brightness |
| Mic | Device mic source/effect/gain; PC mic level, 32-band spectrum and 0x09 colour frames at 5 Hz |
| Music | ffmpeg decode, cpal playback, seek/volume/playlist, 32-band FFT and 0x04 colour frames |
| Schedules | Two on/off schedules, weekday masks, device read and clock sync |
| Console | TX/RX log and raw hex frame sender |
| Settings | JSON in the platform config directory |

### Deliberate differences from the Python app

- The file picker is a path field instead of a native dialog. This avoids
  pulling GTK or another desktop toolkit into the binary.
- Music is decoded by an external `ffmpeg`, the same runtime dependency as the
  Python app.
- The UI is egui, so the widget styling is similar but not pixel-identical to
  the Qt version.
- The Rust binary dynamically links the platform's Bluetooth, audio and window
  libraries. The Python bundle ships more of its stack.

## Size comparison

The Rust target is a single stripped executable. Local Linux release build:

```text
rust/target/release/mrstar   6,495,888 bytes  (6.19 MiB)
```

The Linux release archive containing that executable and the README is
2,975,306 bytes (2.84 MiB). The Python `v1.0.0` Linux distribution is a
PyInstaller one-directory bundle: about 243 MiB on disk and 90,442,064 bytes
(86.25 MiB) compressed. Its `MRStar` launcher binary alone is about 5.1 MiB,
but it cannot run without the surrounding bundle.

The Rust CI workflow builds Linux, Windows, macOS Intel and macOS Apple Silicon
artifacts, runs the smoke test, and fails if any executable exceeds
20,971,520 bytes (20 MiB). Artifacts are uploaded by the `Rust build` workflow
and can be attached to a release with a `rust-v*` tag.

## Compared with the Python v1.0.0 app

| | Python v1.0.0 | Rust port |
| --- | --- | --- |
| UI toolkit | PySide6/Qt | egui/OpenGL |
| Linux distribution | 90,442,064-byte tar.gz, ~243 MiB unpacked | 2,975,497-byte tar.gz, 6,495,824-byte executable |
| Runtime | Bundled Python, Qt, numpy, PortAudio | System Bluetooth/audio/window libraries |
| Protocol | Byte-exact APK frames, regression tests | Same tests ported to Rust |
| Modes | 71 (58 reachable + 13 hidden Flow) | Same catalogue |
| BLE | 0x2022 filter, seven connections, broadcast writes, notifications, reconnect | Same behaviour, polling discovery instead of a detection callback |
| Mic | Device mic controls, PC mic spectrum and 0x09 frames | Same |
| Music | ffmpeg decode, playback, FFT and 0x04 frames | Same |
| Schedules | Two slots, weekday masks, read and clock sync | Same |
| Console | TX/RX log and raw frame sender | Same |
| Settings | QSettings | JSON in the platform config directory |
| File picker | Native Qt dialog | Path field, to avoid bundling GTK |

Both implementations remain unvalidated against physical MR Star hardware.

## Tests

```bash
cargo test
cargo build --release
./target/release/mrstar --smoke-test
```

The smoke test validates representative protocol frames, the 71-mode
catalogue, default settings, and that the release binary starts without a GUI.
