//! Microphone analysis and ffmpeg-backed music playback.

use std::env;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::{Arc, Mutex};

use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::{FromSample, Sample, SampleFormat, SizedSample, StreamConfig};
use rustfft::num_complex::Complex32;
use rustfft::{Fft, FftPlanner};

pub const SAMPLE_RATE: u32 = 44_100;
pub const BLOCK_SIZE: usize = 1024;
pub const BAND_COUNT: usize = 32;
const MIN_FREQUENCY: f32 = 40.0;
const MAX_FREQUENCY: f32 = 16_000.0;

#[derive(Clone, Debug)]
pub struct AudioLevel {
    pub peak: f32,
    pub rms: f32,
    pub dominant: f32,
    pub bands: [f32; BAND_COUNT],
}

impl Default for AudioLevel {
    fn default() -> Self {
        Self {
            peak: 0.0,
            rms: 0.0,
            dominant: 0.0,
            bands: [0.0; BAND_COUNT],
        }
    }
}

struct SpectrumAnalyzer {
    fft: Arc<dyn Fft<f32>>,
    window: Vec<f32>,
    limits: Vec<(usize, usize)>,
    frequencies: Vec<f32>,
}

impl SpectrumAnalyzer {
    fn new(size: usize, sample_rate: f32) -> Self {
        let mut planner = FftPlanner::new();
        let fft = planner.plan_fft_forward(size);
        let window = (0..size)
            .map(|index| {
                let phase = 2.0 * std::f32::consts::PI * index as f32 / (size as f32 - 1.0);
                0.5 - 0.5 * phase.cos()
            })
            .collect::<Vec<_>>();
        let ratio = (MAX_FREQUENCY / MIN_FREQUENCY).powf(1.0 / BAND_COUNT as f32);
        let edges = (0..=BAND_COUNT)
            .map(|index| MIN_FREQUENCY * ratio.powi(index as i32))
            .collect::<Vec<_>>();
        let frequencies = (0..=size / 2)
            .map(|index| index as f32 * sample_rate / size as f32)
            .collect::<Vec<_>>();
        let limits = edges
            .windows(2)
            .map(|edge| {
                let low = frequencies
                    .iter()
                    .position(|frequency| *frequency >= edge[0])
                    .unwrap_or(frequencies.len() - 1);
                let high = frequencies
                    .iter()
                    .position(|frequency| *frequency >= edge[1])
                    .unwrap_or(frequencies.len());
                (low, high.max(low + 1).min(frequencies.len()))
            })
            .collect();
        Self {
            fft,
            window,
            limits,
            frequencies,
        }
    }

    fn analyze(&self, samples: &[f32]) -> AudioLevel {
        let size = self.window.len();
        if samples.len() < 32 {
            return AudioLevel::default();
        }
        let count = samples.len().min(size);
        let mut buffer = Vec::with_capacity(size);
        for index in 0..size {
            let sample = if index < count { samples[index] } else { 0.0 };
            buffer.push(Complex32::new(sample * self.window[index], 0.0));
        }
        self.fft.process(&mut buffer);
        let mut spectrum = buffer
            .iter()
            .take(size / 2 + 1)
            .map(|value| value.norm())
            .collect::<Vec<_>>();
        if !spectrum.is_empty() {
            spectrum[0] = 0.0;
        }
        let dominant_index = spectrum
            .iter()
            .enumerate()
            .max_by(|left, right| left.1.total_cmp(right.1))
            .map(|(index, _)| index)
            .unwrap_or(0);
        let dominant = *self.frequencies.get(dominant_index).unwrap_or(&0.0);
        let mut bands = [0.0f32; BAND_COUNT];
        let mut peak = 0.0f32;
        for (band, (low, high)) in bands.iter_mut().zip(self.limits.iter()) {
            let value = spectrum
                .get(*low..*high)
                .and_then(|slice| slice.iter().copied().reduce(f32::max))
                .unwrap_or(0.0);
            *band = value;
            peak = peak.max(value);
        }
        if peak > 1e-9 {
            for band in &mut bands {
                *band /= peak;
            }
        }
        let rms = (samples.iter().map(|sample| sample * sample).sum::<f32>()
            / samples.len() as f32)
            .sqrt();
        let peak_sample = samples
            .iter()
            .map(|sample| sample.abs())
            .fold(0.0, f32::max);
        AudioLevel {
            peak: peak_sample,
            rms,
            dominant,
            bands,
        }
    }
}

pub struct MicController {
    stream: Option<cpal::Stream>,
    level: Arc<Mutex<AudioLevel>>,
    device: Option<usize>,
}

impl MicController {
    pub fn new() -> Self {
        Self {
            stream: None,
            level: Arc::new(Mutex::new(AudioLevel::default())),
            device: None,
        }
    }

    pub fn running(&self) -> bool {
        self.stream.is_some()
    }

    pub fn snapshot(&self) -> AudioLevel {
        self.level
            .lock()
            .map(|value| value.clone())
            .unwrap_or_default()
    }

    pub fn input_devices() -> Vec<(usize, String)> {
        let host = cpal::default_host();
        host.input_devices()
            .map(|devices| {
                devices
                    .enumerate()
                    .filter_map(|(index, device)| {
                        let name = device.to_string();
                        device.default_input_config().ok().map(|_| (index, name))
                    })
                    .collect()
            })
            .unwrap_or_default()
    }

    pub fn start(&mut self, device_index: Option<usize>) -> Result<(), String> {
        if self.stream.is_some() {
            return Ok(());
        }
        let host = cpal::default_host();
        let device = match device_index {
            Some(index) => host
                .input_devices()
                .map_err(|error| error.to_string())?
                .filter(|device| device.default_input_config().is_ok())
                .nth(index)
                .ok_or_else(|| format!("input device {index} is not available"))?,
            None => host
                .default_input_device()
                .ok_or_else(|| "no default input device".to_string())?,
        };
        let supported = device
            .default_input_config()
            .map_err(|error| format!("microphone config: {error}"))?;
        let sample_rate = supported.sample_rate() as f32;
        let config = supported.config();
        let level = Arc::clone(&self.level);
        let stream = match supported.sample_format() {
            SampleFormat::F32 => build_input::<f32>(&device, config, level, sample_rate),
            SampleFormat::I16 => build_input::<i16>(&device, config, level, sample_rate),
            SampleFormat::U16 => build_input::<u16>(&device, config, level, sample_rate),
            SampleFormat::I8 => build_input::<i8>(&device, config, level, sample_rate),
            SampleFormat::U8 => build_input::<u8>(&device, config, level, sample_rate),
            SampleFormat::I32 => build_input::<i32>(&device, config, level, sample_rate),
            SampleFormat::U32 => build_input::<u32>(&device, config, level, sample_rate),
            SampleFormat::F64 => build_input::<f64>(&device, config, level, sample_rate),
            other => return Err(format!("unsupported microphone sample format: {other:?}")),
        }
        .map_err(|error| format!("microphone stream: {error}"))?;
        stream
            .play()
            .map_err(|error| format!("start microphone: {error}"))?;
        self.stream = Some(stream);
        self.device = device_index;
        Ok(())
    }

    pub fn stop(&mut self) {
        self.stream = None;
        self.device = None;
        if let Ok(mut level) = self.level.lock() {
            *level = AudioLevel::default();
        }
    }
}

impl Drop for MicController {
    fn drop(&mut self) {
        self.stop();
    }
}

fn build_input<T>(
    device: &cpal::Device,
    config: StreamConfig,
    level: Arc<Mutex<AudioLevel>>,
    sample_rate: f32,
) -> Result<cpal::Stream, cpal::Error>
where
    T: SizedSample + Send + 'static,
    f32: FromSample<T>,
{
    let channels = config.channels as usize;
    let analyzer = SpectrumAnalyzer::new(BLOCK_SIZE, sample_rate);
    let mut pending = Vec::with_capacity(BLOCK_SIZE * 2);
    device.build_input_stream(
        config,
        move |data: &[T], _info: &cpal::InputCallbackInfo| {
            for frame in data.chunks(channels) {
                let sum = frame
                    .iter()
                    .map(|sample| f32::from_sample(*sample))
                    .sum::<f32>();
                pending.push(sum / channels.max(1) as f32);
            }
            while pending.len() >= BLOCK_SIZE {
                let start = pending.len() - BLOCK_SIZE;
                let analysis = analyzer.analyze(&pending[start..]);
                if let Ok(mut current) = level.lock() {
                    *current = analysis;
                }
                pending.clear();
            }
        },
        |error| eprintln!("microphone stream error: {error}"),
        None,
    )
}

#[derive(Debug)]
struct PlayerData {
    samples: Vec<f32>,
    cursor: usize,
    playing: bool,
    volume: f32,
}

impl Default for PlayerData {
    fn default() -> Self {
        Self {
            samples: Vec::new(),
            cursor: 0,
            playing: false,
            volume: 0.8,
        }
    }
}

impl PlayerData {
    fn frames(&self) -> usize {
        self.samples.len() / 2
    }
}

pub struct MusicPlayer {
    data: Arc<Mutex<PlayerData>>,
    stream: Option<cpal::Stream>,
    analyzer: SpectrumAnalyzer,
    path: Option<String>,
}

impl MusicPlayer {
    pub fn new() -> Self {
        Self {
            data: Arc::new(Mutex::new(PlayerData::default())),
            stream: None,
            analyzer: SpectrumAnalyzer::new(2048, SAMPLE_RATE as f32),
            path: None,
        }
    }

    pub fn load(&mut self, path: &str) -> Result<f64, String> {
        self.stop();
        let ffmpeg = ffmpeg_executable()?;
        let mut command = command_for(&ffmpeg);
        command.args([
            "-v",
            "error",
            "-i",
            path,
            "-vn",
            "-f",
            "f32le",
            "-ac",
            "2",
            "-ar",
            &SAMPLE_RATE.to_string(),
            "-",
        ]);
        let output = command
            .output()
            .map_err(|error| format!("could not run ffmpeg: {error}"))?;
        if !output.status.success() {
            let message = String::from_utf8_lossy(&output.stderr).trim().to_string();
            return Err(if message.is_empty() {
                "ffmpeg could not decode this file".into()
            } else {
                message
            });
        }
        let mut samples = Vec::with_capacity(output.stdout.len() / 4);
        for chunk in output.stdout.chunks_exact(4) {
            samples.push(f32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]));
        }
        if samples.len() < 2 {
            return Err("decoded audio is empty".into());
        }
        let frames = samples.len() / 2;
        samples.truncate(frames * 2);
        {
            let mut data = self.data.lock().map_err(|_| "player lock poisoned")?;
            data.samples = samples;
            data.cursor = 0;
            data.playing = false;
        }
        self.path = Some(path.to_string());
        self.ensure_stream()?;
        Ok(frames as f64 / SAMPLE_RATE as f64)
    }

    fn ensure_stream(&mut self) -> Result<(), String> {
        if self.stream.is_some() {
            return Ok(());
        }
        let host = cpal::default_host();
        let device = host
            .default_output_device()
            .ok_or_else(|| "no default output device".to_string())?;
        let supported = device
            .default_output_config()
            .map_err(|error| format!("output config: {error}"))?;
        let config = supported.config();
        let data = Arc::clone(&self.data);
        let stream = match supported.sample_format() {
            SampleFormat::F32 => build_output::<f32>(&device, config, data),
            SampleFormat::I16 => build_output::<i16>(&device, config, data),
            SampleFormat::U16 => build_output::<u16>(&device, config, data),
            SampleFormat::I8 => build_output::<i8>(&device, config, data),
            SampleFormat::U8 => build_output::<u8>(&device, config, data),
            SampleFormat::I32 => build_output::<i32>(&device, config, data),
            SampleFormat::U32 => build_output::<u32>(&device, config, data),
            SampleFormat::F64 => build_output::<f64>(&device, config, data),
            other => return Err(format!("unsupported output sample format: {other:?}")),
        }
        .map_err(|error| format!("output stream: {error}"))?;
        stream
            .play()
            .map_err(|error| format!("start output: {error}"))?;
        self.stream = Some(stream);
        Ok(())
    }

    pub fn duration(&self) -> f64 {
        self.data
            .lock()
            .map(|data| data.frames() as f64 / SAMPLE_RATE as f64)
            .unwrap_or(0.0)
    }

    pub fn position(&self) -> f64 {
        self.data
            .lock()
            .map(|data| data.cursor as f64 / SAMPLE_RATE as f64)
            .unwrap_or(0.0)
    }

    pub fn playing(&self) -> bool {
        self.data.lock().map(|data| data.playing).unwrap_or(false)
    }

    pub fn path(&self) -> Option<&str> {
        self.path.as_deref()
    }

    pub fn set_volume(&self, value: f32) {
        if let Ok(mut data) = self.data.lock() {
            data.volume = value.clamp(0.0, 1.0);
        }
    }

    pub fn play(&mut self) -> Result<(), String> {
        if self.data.lock().map(|data| data.frames()).unwrap_or(0) == 0 {
            return Ok(());
        }
        self.ensure_stream()?;
        if let Ok(mut data) = self.data.lock() {
            if data.cursor >= data.frames() {
                data.cursor = 0;
            }
            data.playing = true;
        }
        Ok(())
    }

    pub fn pause(&self) {
        if let Ok(mut data) = self.data.lock() {
            data.playing = false;
        }
    }

    pub fn toggle(&mut self) -> Result<(), String> {
        if self.playing() {
            self.pause();
            Ok(())
        } else {
            self.play()
        }
    }

    pub fn stop(&mut self) {
        if let Ok(mut data) = self.data.lock() {
            data.playing = false;
            data.cursor = 0;
        }
    }

    pub fn seek(&self, seconds: f64) {
        if let Ok(mut data) = self.data.lock() {
            let cursor = (seconds.max(0.0) * SAMPLE_RATE as f64) as usize;
            data.cursor = cursor.min(data.frames());
        }
    }

    pub fn analysis(&self) -> AudioLevel {
        let block = {
            let Ok(data) = self.data.lock() else {
                return AudioLevel::default();
            };
            let frames = data.frames();
            if frames == 0 {
                return AudioLevel::default();
            }
            let count = frames.min(2048);
            let start = data.cursor.min(frames.saturating_sub(count));
            let mut block = Vec::with_capacity(count);
            for index in 0..count {
                block.push(data.samples[(start + index) * 2]);
            }
            block
        };
        self.analyzer.analyze(&block)
    }

    pub fn close(&mut self) {
        self.pause();
        self.stream = None;
    }
}

impl Drop for MusicPlayer {
    fn drop(&mut self) {
        self.close();
    }
}

fn build_output<T>(
    device: &cpal::Device,
    config: StreamConfig,
    data: Arc<Mutex<PlayerData>>,
) -> Result<cpal::Stream, cpal::Error>
where
    T: SizedSample + FromSample<f32>,
{
    let channels = config.channels as usize;
    device.build_output_stream(
        config,
        move |output: &mut [T], _info: &cpal::OutputCallbackInfo| {
            let Ok(mut data) = data.lock() else {
                for sample in output.iter_mut() {
                    *sample = T::from_sample(0.0);
                }
                return;
            };
            if !data.playing {
                for sample in output.iter_mut() {
                    *sample = T::from_sample(0.0);
                }
                return;
            }
            let frames = data.frames();
            let volume = data.volume;
            for frame in output.chunks_mut(channels) {
                let (left, right) = if data.cursor < frames {
                    let left = data.samples[data.cursor * 2];
                    let right = data.samples[data.cursor * 2 + 1];
                    data.cursor += 1;
                    (left, right)
                } else {
                    data.playing = false;
                    (0.0, 0.0)
                };
                for (channel, sample) in frame.iter_mut().enumerate() {
                    let value = match channel {
                        0 => left,
                        1 => right,
                        _ => (left + right) * 0.5,
                    };
                    *sample = T::from_sample(value * volume);
                }
            }
        },
        |error| eprintln!("output stream error: {error}"),
        None,
    )
}

fn command_for(program: &str) -> Command {
    #[allow(unused_mut)]
    let mut command = Command::new(program);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000);
    }
    command
}

fn ffmpeg_executable() -> Result<String, String> {
    let override_path = env::var("MRSTAR_FFMPEG")
        .ok()
        .or_else(|| env::var("FFMPEG_BINARY").ok());
    if let Some(value) = override_path {
        let path = PathBuf::from(shellexpand(&value));
        if path.is_file() {
            return Ok(path.to_string_lossy().into_owned());
        }
        if let Some(found) = find_on_path(&value) {
            return Ok(found.to_string_lossy().into_owned());
        }
        return Err(format!(
            "MRSTAR_FFMPEG points to a missing executable: {value}"
        ));
    }
    find_on_path("ffmpeg")
        .map(|path| path.to_string_lossy().into_owned())
        .ok_or_else(|| {
            "ffmpeg was not found on PATH. Install it, or set MRSTAR_FFMPEG to the executable path. Linux: sudo apt install ffmpeg; macOS: brew install ffmpeg; Windows: winget install Gyan.FFmpeg".into()
        })
}

fn shellexpand(value: &str) -> String {
    if let Some(stripped) = value.strip_prefix("~/") {
        if let Some(home) = env::var_os("HOME").or_else(|| env::var_os("USERPROFILE")) {
            return Path::new(&home)
                .join(stripped)
                .to_string_lossy()
                .into_owned();
        }
    }
    value.to_string()
}

fn find_on_path(program: &str) -> Option<PathBuf> {
    let candidate = Path::new(program);
    if candidate.is_file() {
        return Some(candidate.to_path_buf());
    }
    let path = env::var_os("PATH")?;
    let extensions = if cfg!(windows) {
        vec!["exe", "cmd", "bat", ""]
    } else {
        vec![""]
    };
    for directory in env::split_paths(&path) {
        for extension in &extensions {
            let name = if extension.is_empty() {
                program.to_string()
            } else {
                format!("{program}.{extension}")
            };
            let candidate = directory.join(name);
            if candidate.is_file() {
                return Some(candidate);
            }
        }
    }
    let fallbacks: &[&str] = if cfg!(windows) {
        &[r"C:\ffmpeg\bin\ffmpeg.exe"]
    } else if cfg!(target_os = "macos") {
        &["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"]
    } else {
        &["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg"]
    };
    fallbacks
        .iter()
        .map(PathBuf::from)
        .find(|candidate| candidate.is_file())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn analyzer_bands_are_normalised() {
        let analyzer = SpectrumAnalyzer::new(BLOCK_SIZE, SAMPLE_RATE as f32);
        let signal = (0..BLOCK_SIZE)
            .map(|index| {
                (2.0 * std::f32::consts::PI * 440.0 * index as f32 / SAMPLE_RATE as f32).sin()
            })
            .collect::<Vec<_>>();
        let result = analyzer.analyze(&signal);
        assert!(result.rms > 0.5);
        assert!(result.bands.iter().any(|value| *value > 0.9));
        assert!(result.dominant > 300.0 && result.dominant < 600.0);
    }
}
