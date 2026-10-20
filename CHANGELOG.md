# Changelog

All notable changes to this project are documented here.

## [Unreleased]

## [1.0.0] - 2026-10-20

### Added

- Desktop BLE controller reconstructed from the MR Star Android app v1.0.0.
- Power, colour wheel, brightness, presets, colour order, and pixel count.
- All 71 animation modes defined by the APK, including the hidden Flow set.
- Device microphone effects, sensitivity, and source selection.
- Computer microphone and music-reactive colour streaming.
- Two weekly schedules, device clock sync, and schedule readback.
- Protocol console with TX/RX logging and raw frame sending.
- Exact regression tests for frames, notifications, modes, DSP, and the Qt UI.

### Notes

- Protocol compatibility was verified against the decompiled APK, not against
  physical hardware.
- The proprietary APK is not distributed in this repository.
