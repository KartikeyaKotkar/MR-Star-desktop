"""Audio helpers for the desktop port.

The Android app has two audio-reactive modes:

* phone microphone -> ``VoiceUtils`` samples MediaRecorder peak amplitude and
  sends 0x09 colour frames;
* music player -> ``MusicFragment`` uses ``Visualizer`` FFT and sends 0x04
  colour frames.

On the desktop those become a sounddevice input analyser and a small
ffmpeg-backed file player that also exposes FFT analysis.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np

try:
    import sounddevice as sd
except Exception as _audio_error:  # PortAudio missing or unusable
    sd = None
    _AUDIO_ERROR: Exception | None = _audio_error
else:
    _AUDIO_ERROR = None

SAMPLE_RATE = 44_100
BLOCK_SIZE = 1024
BAND_COUNT = 32
BAND_EDGES = np.geomspace(40.0, 16_000.0, BAND_COUNT + 1)
MIC_WINDOW = np.hanning(BLOCK_SIZE)
MIC_FREQUENCIES = np.fft.rfftfreq(BLOCK_SIZE, 1.0 / SAMPLE_RATE)
_WINDOWS: dict[int, np.ndarray] = {}
_FREQUENCIES: dict[int, np.ndarray] = {}


def _band_limits(frequencies: np.ndarray) -> tuple[tuple[int, int], ...]:
    limits = []
    for index in range(BAND_COUNT):
        low = int(np.searchsorted(frequencies, BAND_EDGES[index]))
        high = max(int(np.searchsorted(frequencies, BAND_EDGES[index + 1])), low + 1)
        limits.append((low, high))
    return tuple(limits)


MIC_BAND_LIMITS = _band_limits(MIC_FREQUENCIES)


def _require_audio():
    if sd is None:
        raise RuntimeError(
            f"audio backend unavailable ({_AUDIO_ERROR}); install PortAudio"
        )
    return sd


@lru_cache(maxsize=1)
def _ffmpeg_executable() -> str:
    """Return ffmpeg from an override or PATH, with install hints on failure."""
    override = os.environ.get("MRSTAR_FFMPEG") or os.environ.get("FFMPEG_BINARY")
    if override:
        path = Path(override).expanduser()
        if path.is_file():
            return str(path)
        found = shutil.which(override)
        if found:
            return found
        raise RuntimeError(f"MRSTAR_FFMPEG points to a missing executable: {override}")

    found = shutil.which("ffmpeg")
    if found:
        return found
    raise RuntimeError(
        "ffmpeg was not found on PATH. Install it, or set MRSTAR_FFMPEG to the "
        "executable path. Linux: sudo apt install ffmpeg; macOS: brew install "
        "ffmpeg; Windows: winget install Gyan.FFmpeg"
    )


def _window(size: int) -> np.ndarray:
    window = _WINDOWS.get(size)
    if window is None:
        window = np.hanning(size)
        _WINDOWS[size] = window
    return window


def _frequencies(size: int) -> np.ndarray:
    frequencies = _FREQUENCIES.get(size)
    if frequencies is None:
        frequencies = np.fft.rfftfreq(size, 1.0 / SAMPLE_RATE)
        _FREQUENCIES[size] = frequencies
    return frequencies


def _normalise_bands(result: np.ndarray) -> np.ndarray:
    peak = float(result.max())
    if peak > 1e-9:
        result /= peak
    return result


def _bands_from_limits(
    spectrum: np.ndarray, limits: tuple[tuple[int, int], ...]
) -> np.ndarray:
    result = np.zeros(BAND_COUNT, dtype=np.float32)
    for index, (low, high) in enumerate(limits):
        segment = spectrum[low:high]
        if segment.size:
            result[index] = float(segment.max())
    return _normalise_bands(result)


def _bands(spectrum: np.ndarray, frequencies: np.ndarray) -> np.ndarray:
    return _bands_from_limits(spectrum, _band_limits(frequencies))


class MicAnalyzer:
    """Live microphone level/spectrum, Qt-free."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stream: sd.InputStream | None = None
        self._peak = 0.0
        self._rms = 0.0
        self._dominant = 0.0
        self._bands = np.zeros(BAND_COUNT, dtype=np.float32)
        self._device = None

    @property
    def running(self) -> bool:
        return self._stream is not None

    @property
    def device(self):
        return self._device

    @staticmethod
    def input_devices() -> list[tuple[int, str]]:
        audio = _require_audio()
        devices = []
        for index, info in enumerate(audio.query_devices()):
            if info.get("max_input_channels", 0) > 0:
                devices.append((index, info.get("name", f"Input {index}")))
        return devices

    def start(self, device: int | None = None) -> None:
        if self._stream is not None:
            return
        audio = _require_audio()
        stream = audio.InputStream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
            channels=1,
            dtype="float32",
            device=device,
            callback=self._callback,
        )
        try:
            stream.start()
        except Exception:
            stream.close()
            raise
        self._stream = stream
        self._device = device

    def stop(self) -> None:
        stream = self._stream
        self._stream = None
        self._device = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        with self._lock:
            self._peak = 0.0
            self._rms = 0.0
            self._dominant = 0.0
            self._bands = np.zeros(BAND_COUNT, dtype=np.float32)

    def _callback(self, indata, _frames, _time, status) -> None:
        mono = indata[:, 0]
        peak = float(np.max(np.abs(mono)))
        rms = float(np.sqrt(np.mean(np.square(mono))))
        spectrum = np.abs(np.fft.rfft(mono * MIC_WINDOW))
        spectrum[0] = 0.0
        index = int(np.argmax(spectrum))
        dominant = float(MIC_FREQUENCIES[index])
        bands = _bands_from_limits(spectrum, MIC_BAND_LIMITS)
        with self._lock:
            self._peak = peak
            self._rms = rms
            self._dominant = dominant
            self._bands = bands

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "peak": self._peak,
                "rms": self._rms,
                "dominant": self._dominant,
                "bands": self._bands.copy(),
            }


class MusicPlayer:
    """Decode a file with ffmpeg and play it through sounddevice."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: np.ndarray | None = None  # int16, shape (frames, 2)
        self._cursor = 0
        self._playing = False
        self._stream: sd.OutputStream | None = None
        self._volume = 0.8
        self.path: str | None = None

    # ------------------------------------------------------------------ decode
    def load(self, path: str) -> float:
        self.stop()
        command = [
            _ffmpeg_executable(),
            "-v",
            "error",
            "-i",
            path,
            "-vn",
            "-f",
            "s16le",
            "-ac",
            "2",
            "-ar",
            str(SAMPLE_RATE),
            "-",
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        result = subprocess.run(command, capture_output=True, creationflags=creationflags)
        if result.returncode != 0:
            message = result.stderr.decode("utf-8", "replace").strip()
            raise RuntimeError(message or "ffmpeg could not decode this file")
        data = np.frombuffer(result.stdout, dtype="<i2")
        if data.size < 2:
            raise RuntimeError("decoded audio is empty")
        data = data.reshape(-1, 2)
        with self._lock:
            self._data = data
            self._cursor = 0
            self._playing = False
            self.path = path
        self._ensure_stream()
        return len(data) / SAMPLE_RATE

    def _ensure_stream(self) -> None:
        if self._stream is not None:
            return
        audio = _require_audio()
        stream = audio.OutputStream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
            channels=2,
            dtype="float32",
            callback=self._callback,
        )
        try:
            stream.start()
        except Exception:
            stream.close()
            raise
        self._stream = stream

    # ------------------------------------------------------------------ transport
    @property
    def duration(self) -> float:
        with self._lock:
            return len(self._data) / SAMPLE_RATE if self._data is not None else 0.0

    @property
    def position(self) -> float:
        with self._lock:
            return self._cursor / SAMPLE_RATE

    @property
    def playing(self) -> bool:
        with self._lock:
            return self._playing

    @property
    def volume(self) -> float:
        return self._volume

    @volume.setter
    def volume(self, value: float) -> None:
        self._volume = max(0.0, min(1.0, float(value)))

    def play(self) -> None:
        if self._data is None:
            return
        self._ensure_stream()
        with self._lock:
            if self._cursor >= len(self._data):
                self._cursor = 0
            self._playing = True

    def pause(self) -> None:
        with self._lock:
            self._playing = False

    def toggle(self) -> None:
        if self.playing:
            self.pause()
        else:
            self.play()

    def stop(self) -> None:
        with self._lock:
            self._playing = False
            self._cursor = 0

    def seek(self, seconds: float) -> None:
        with self._lock:
            if self._data is None:
                return
            self._cursor = max(0, min(len(self._data), int(seconds * SAMPLE_RATE)))

    def _callback(self, outdata, frames, _time, status) -> None:
        with self._lock:
            if not self._playing or self._data is None:
                outdata.fill(0)
                return
            end = self._cursor + frames
            chunk = self._data[self._cursor:end]
            if chunk.size:
                outdata[: len(chunk)] = chunk.astype(np.float32) * (1.0 / 32768.0) * self._volume
            if len(chunk) < frames:
                outdata[len(chunk):] = 0
                self._cursor = len(self._data)
                self._playing = False
            else:
                self._cursor = end

    # ------------------------------------------------------------------ analysis
    def analysis(self, window: int = 2048) -> dict:
        with self._lock:
            if self._data is None:
                return {"level": 0.0, "dominant": 0.0, "bands": np.zeros(BAND_COUNT, dtype=np.float32)}
            start = max(0, min(len(self._data) - window, self._cursor))
            block = self._data[start:start + window, 0].astype(np.float32) / 32768.0
        if block.size < 32:
            return {"level": 0.0, "dominant": 0.0, "bands": np.zeros(BAND_COUNT, dtype=np.float32)}
        windowed = block * _window(block.size)
        spectrum = np.abs(np.fft.rfft(windowed))
        spectrum[0] = 0.0
        frequencies = _frequencies(block.size)
        index = int(np.argmax(spectrum))
        return {
            "level": float(np.sqrt(np.mean(np.square(block)))),
            "dominant": float(frequencies[index]),
            "bands": _bands(spectrum, frequencies),
        }

    def close(self) -> None:
        self.pause()
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
