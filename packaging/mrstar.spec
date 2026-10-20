# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for a self-contained, one-directory app."""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
ASSETS = ROOT / "mrstar" / "assets"

datas = [(str(ASSETS / "icon.png"), "mrstar/assets")]
binaries = []
hiddenimports = []

# sounddevice ships PortAudio on Windows and macOS.  Collect its data so the
# frozen application can find the library without a system install.
sound_datas, sound_binaries, sound_hidden = collect_all("sounddevice")
datas += sound_datas
binaries += sound_binaries
hiddenimports += sound_hidden

# bleak chooses its platform backend with a runtime import.
if sys.platform.startswith("linux"):
    hiddenimports += collect_submodules("bleak.backends.bluezdbus")
elif sys.platform == "win32":
    hiddenimports += collect_submodules("bleak.backends.winrt")
elif sys.platform == "darwin":
    hiddenimports += collect_submodules("bleak.backends.corebluetooth")

# Keep the bundle small: only QtCore, QtGui and QtWidgets are imported.
excludes = [
    "tkinter",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
]

exe_icon = str(ASSETS / "icon.ico") if sys.platform == "win32" else None
version_file = str(ROOT / "packaging" / "version_info.txt") if sys.platform == "win32" else None

a = Analysis(
    [str(ROOT / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

# The GTK platform theme and Qt's translation catalogues are optional.  The
# Fusion style and Qt's built-in English strings are used instead.
def _keep(entry):
    destination = entry[0].replace("\\", "/")
    return not (
        "PySide6/Qt/translations/" in destination
        or destination.endswith("PySide6/Qt/plugins/platformthemes/libqgtk3.so")
    )


a.binaries = [entry for entry in a.binaries if _keep(entry)]
a.datas = [entry for entry in a.datas if _keep(entry)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MRStar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=exe_icon,
    version=version_file,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MRStar",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="MR Star.app",
        icon=str(ASSETS / "icon.icns"),
        bundle_identifier="io.github.kartikeyakotkar.mrstar",
        info_plist={
            "CFBundleDisplayName": "MR Star",
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1.0.0",
            "LSMinimumSystemVersion": "13.0",
            "LSApplicationCategoryType": "public.app-category.utilities",
            "NSHighResolutionCapable": True,
            "NSHumanReadableCopyright": "MIT licensed code; see LICENSE",
            "NSBluetoothAlwaysUsageDescription": (
                "MR Star uses Bluetooth to find and control your light strip."
            ),
            "NSBluetoothPeripheralUsageDescription": (
                "MR Star uses Bluetooth to find and control your light strip."
            ),
            "NSMicrophoneUsageDescription": (
                "MR Star uses the microphone for audio-reactive lighting."
            ),
        },
    )
