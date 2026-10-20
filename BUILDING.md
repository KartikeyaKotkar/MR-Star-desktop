# Building MR Star Desktop

The release workflow builds four native bundles on every `v*` tag:

- Linux x86_64 on Ubuntu 22.04
- Windows x86_64 on the current Windows runner
- macOS x86_64 on `macos-15-intel`
- macOS arm64 on `macos-15`

Each bundle is a PyInstaller one-directory build. `PySide6-Essentials` keeps the
artifact smaller than the full `PySide6` metapackage, and the spec excludes Qt
modules the UI does not import.

## Local build

Use a clean virtual environment so PyInstaller does not discover unrelated
packages from the system:

```bash
python3 -m venv .venv-build
.venv-build/bin/python -m pip install --upgrade pip
.venv-build/bin/python -m pip install -r requirements-build.txt
.venv-build/bin/pyinstaller --clean --noconfirm packaging/mrstar.spec
```

On Windows, use `.venv-build\Scripts\python.exe` and
`.venv-build\Scripts\pyinstaller.exe`.

Output:

- Linux/Windows: `dist/MRStar/`
- macOS: `dist/MR Star.app`

## Smoke test

The frozen entry point accepts `--smoke-test`, which shows the window and
closes it after 1.2 seconds. It does not scan for BLE devices.

Linux:

```bash
QT_QPA_PLATFORM=offscreen dist/MRStar/MRStar --smoke-test
```

Windows PowerShell:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
& "dist/MRStar/MRStar.exe" --smoke-test
```

macOS:

```bash
QT_QPA_PLATFORM=offscreen "dist/MR Star.app/Contents/MacOS/MRStar" --smoke-test
```

## Platform notes

- Linux needs `libportaudio2`, `libxcb-cursor0` and a working X11/Wayland stack
  at runtime. BlueZ and D-Bus are required for BLE. The release is built on
  Ubuntu 22.04 for glibc 2.34 compatibility.
- Windows bundles PortAudio through the `sounddevice` wheel. The app uses
  `CREATE_NO_WINDOW` when calling ffmpeg so a console does not flash.
- macOS bundles PortAudio through the `sounddevice` wheel. The app bundle sets
  `NSBluetoothAlwaysUsageDescription` and `NSMicrophoneUsageDescription`; both
  permissions are required for the respective features.
- `ffmpeg` is not bundled. Set `MRSTAR_FFMPEG` or install it on `PATH` for music
  playback.
- Release artifacts are unsigned. Signing and notarization need repository
  secrets and platform certificates, which are intentionally not configured
  here.

## Release

Do not create a release manually. Push a tag:

```bash
git tag -a v1.0.0 -m "MR Star Desktop 1.0.0"
git push origin v1.0.0
```

The `Release` workflow builds all four bundles, smoke-tests each one, and
attaches them to the GitHub release. See [PUBLISHING.md](PUBLISHING.md).
