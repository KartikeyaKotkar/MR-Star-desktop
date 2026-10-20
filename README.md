# MR Star Desktop

Native cross-platform controller for **MR Star** BLE light strips, reconstructed
from the shipped Android app (`MR Star - v1.0.0.apk`, package `com.frok.mrstar`,
versionCode 104). Runs on Linux, Windows and macOS.

The Android app has no public protocol documentation. The protocol here was
recovered from the APK and is byte-for-byte compatible with the frames the phone
sends. The current `main` branch is the Rust implementation; the earlier Python
implementation is preserved at tag `v1.0.0`.

![MR Star icon](assets/icon.png)

## Download

Prebuilt bundles are attached to the
[latest GitHub release](https://github.com/KartikeyaKotkar/MR-Star-desktop/releases/latest):

| Platform | Asset | Notes |
| --- | --- | --- |
| Linux x86_64 | `MRStar-1.1.1-linux-x86_64.tar.gz` | BlueZ, D-Bus, ALSA, X11 or Wayland, OpenGL |
| Windows x86_64 | `MRStar-1.1.1-windows-x86_64.zip` | Windows 10/11, Bluetooth enabled |
| macOS Apple Silicon | `MRStar-1.1.1-macos-arm64.zip` | macOS 13+, ad-hoc signed `.app` |
| macOS Intel | `MRStar-1.1.1-macos-x86_64.zip` | macOS 13+, ad-hoc signed `.app` |

The macOS app is not notarized. On first launch, right-click the app and choose
**Open**, or remove the quarantine flag:

```bash
xattr -dr com.apple.quarantine "/Applications/MR Star.app"
```

Windows SmartScreen may also warn because the executable is unsigned.

## Build

```bash
cargo test --release
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
- macOS 13+: the bundled app includes the Bluetooth and microphone usage
  descriptions required by macOS.
- Music playback: `ffmpeg` on `PATH`, or `MRSTAR_FFMPEG` pointing at it. On
  macOS the app also checks `/opt/homebrew/bin` and `/usr/local/bin`, because
  Finder-launched apps do not inherit the shell `PATH`.

No Python, Qt, PortAudio or bundled runtime is required.

## Features

| Area | Implementation |
| --- | --- |
| Protocol | Byte-identical frames, including inverted power, `/255` mode encoding, the malformed clock frame, the achromatic HSV quirk, and retries for `0x0B`/`0x0C`/`0x50` |
| BLE | Scans for company ID `0x2022` or service `FFF0`, shows named devices when requested, connects up to seven lights, broadcasts writes, parses notifications, auto-connects and retries dropped connections |
| Modes | All 71 APK modes: 58 reachable plus the hidden 13-mode Flow category |
| Colour | HSV wheel, presets, custom slots, RGB order, pixel count, brightness |
| Mic | Device mic source/effect/gain; PC mic level, 32-band spectrum and `0x09` colour frames at 5 Hz |
| Music | `ffmpeg` decode, `cpal` playback, seek/volume/playlist, 32-band FFT and `0x04` colour frames |
| Schedules | Two on/off schedules, weekday masks, device read and clock sync |
| Console | TX/RX log and raw hex frame sender |
| Settings | JSON in the platform config directory |

## BLE troubleshooting

- A row says `MR Star` only when the advertisement contains company ID `0x2022`
  or service `FFF0`. Rows marked `other` are shown for diagnostics and are not
  auto-connected.
- `no longer visible to Bluetooth` means the cached peripheral has gone away.
  Power the light on, keep it near the PC, and scan again.
- `write characteristic 0xFFF3 not found` means the device does not implement
  the MR Star GATT service. The console lists the characteristics it does
  expose.
- A BLE light can normally accept one central connection at a time. Disconnect
  it from the phone or another desktop app before connecting here.

## Architecture

- `src/protocol.rs` — APK command frames, notifications and conversions.
- `src/modes.rs` — generated 71-mode catalogue.
- `src/ble.rs` — `btleplug` worker, scan/connect/notify/write loop.
- `src/audio.rs` — `cpal` microphone analysis, `ffmpeg` decode, playback and FFT.
- `src/app.rs` — egui interface and page state.
- `src/settings.rs` — persisted JSON settings.
- `macos/Info.plist` — macOS app metadata, Bluetooth and microphone permissions.

## Differences from the archived Python app

- The file picker is a path field instead of a native dialog. This avoids
  pulling GTK or another desktop toolkit into the binary.
- The UI is egui, so widget styling is similar but not pixel-identical to the
  Qt version.
- The Rust binary dynamically links the platform Bluetooth, audio and window
  libraries. The Python bundle shipped more of its stack.
- Settings are JSON instead of `QSettings`.
- Music is decoded by an external `ffmpeg`, the same runtime dependency as the
  Python app.

## Size

The Rust targets are single stripped executables (macOS uses a small `.app`
bundle). CI size checks enforce a 20 MiB (20,971,520-byte) ceiling on every
executable and archive.

| Platform | Executable | Archive | Python v1.0.0 archive |
| --- | ---: | ---: | ---: |
| Linux x86_64 | ~6.2 MiB | ~2.8 MiB | 86.25 MiB |
| Windows x86_64 | ~4.2 MiB | ~2.1 MiB | 54.29 MiB |
| macOS x86_64 | ~4.4 MiB | ~2.7 MiB | 35.58 MiB |
| macOS arm64 | ~3.6 MiB | ~2.5 MiB | 31.96 MiB |

The Python `v1.0.0` Linux distribution was a PyInstaller one-directory bundle:
about 243 MiB on disk and 90,442,064 bytes compressed. Its `MRStar` launcher was
about 5.1 MiB, but could not run without the surrounding bundle.

## Tests

```bash
cargo fmt --all -- --check
cargo test --release
cargo build --release
./target/release/mrstar --smoke-test
```

The smoke test validates representative protocol frames, the 71-mode
catalogue, default settings, and that the release binary starts without a GUI.
The CI workflow builds Linux, Windows, macOS Intel and macOS Apple Silicon and
runs the size gate. macOS arm64 is cross-compiled on the Intel runner; its
Mach-O architecture is checked before packaging.

## Hardware status

The protocol is verified against the decompiled APK, but not yet against
physical MR Star hardware. Live BLE and microphone behavior still needs a
hardware soak test.

## License

MIT. See [LICENSE](LICENSE).
