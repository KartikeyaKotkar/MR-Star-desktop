"""DSP tests that do not open audio devices."""

from __future__ import annotations

import os
import tempfile
import unittest

import numpy as np

from mrstar.audio import BAND_COUNT, SAMPLE_RATE, MusicPlayer, _bands, _ffmpeg_executable


class BandTests(unittest.TestCase):
    def test_shape_and_normalisation(self) -> None:
        frequencies = np.fft.rfftfreq(2048, 1.0 / SAMPLE_RATE)
        spectrum = np.linspace(0.0, 2.0, frequencies.size)
        bands = _bands(spectrum, frequencies)
        self.assertEqual(bands.shape, (BAND_COUNT,))
        self.assertAlmostEqual(float(bands.max()), 1.0)

    def test_silence(self) -> None:
        frequencies = np.fft.rfftfreq(2048, 1.0 / SAMPLE_RATE)
        bands = _bands(np.zeros_like(frequencies), frequencies)
        self.assertTrue(np.all(bands == 0.0))


class FfmpegTests(unittest.TestCase):
    def test_environment_override_wins(self) -> None:
        previous = os.environ.get("MRSTAR_FFMPEG")
        with tempfile.NamedTemporaryFile() as temporary:
            os.environ["MRSTAR_FFMPEG"] = temporary.name
            _ffmpeg_executable.cache_clear()
            try:
                self.assertEqual(_ffmpeg_executable(), temporary.name)
            finally:
                if previous is None:
                    os.environ.pop("MRSTAR_FFMPEG", None)
                else:
                    os.environ["MRSTAR_FFMPEG"] = previous
                _ffmpeg_executable.cache_clear()


class MusicAnalysisTests(unittest.TestCase):
    def test_sine_dominant_frequency(self) -> None:
        time = np.arange(4096) / SAMPLE_RATE
        mono = (0.5 * np.sin(2.0 * np.pi * 440.0 * time) * 32767.0).astype(np.int16)
        data = np.stack((mono, mono), axis=1)

        player = MusicPlayer()
        player._data = data
        player._cursor = 1024
        result = player.analysis(window=2048)

        self.assertAlmostEqual(result["dominant"], 440.0, delta=25.0)
        self.assertGreater(result["level"], 0.1)
        self.assertEqual(result["bands"].shape, (BAND_COUNT,))


if __name__ == "__main__":
    unittest.main()
