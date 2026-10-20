# Changelog

All notable changes to this project are documented here.

## [Unreleased]

## [1.0.0] - 2026-10-20

### Added

- Cross-platform desktop controller for Linux, Windows and macOS.
- Native release bundles for Linux x86_64, Windows x86_64, macOS Intel and
  macOS Apple Silicon.
- Power, colour wheel, brightness, presets, colour order, and pixel count.
- All 71 animation modes defined by the APK, including the hidden Flow set.
- Device microphone effects, sensitivity, and source selection.
- Computer microphone and music-reactive colour streaming.
- Two weekly schedules, device clock sync, and schedule readback.
- Protocol console with TX/RX logging and raw frame sending.
- Exact regression tests for frames, notifications, modes, DSP, and the Qt UI.

### Changed

- Use `PySide6-Essentials` and one-directory PyInstaller bundles instead of the
  full Qt metapackage.
- Precompute microphone FFT windows/frequencies and cache music analysis data.
- Defer audio-device enumeration until the microphone page is opened.
- Use the Fusion Qt style for consistent rendering on all platforms.
- Find `ffmpeg` through `MRSTAR_FFMPEG`, then `PATH`, and hide its console window
  on Windows.
- Add Windows launcher, macOS app metadata, and platform icons.

### Notes

- Protocol compatibility was verified against the decompiled APK, not against
  physical hardware.
- The proprietary APK is not distributed in this repository.
