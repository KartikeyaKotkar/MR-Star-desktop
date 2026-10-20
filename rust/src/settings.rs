//! Persistent desktop settings.

use std::fs;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};

pub const DEFAULT_COLORS: [[u8; 3]; 7] = [
    [255, 0, 0],
    [255, 255, 0],
    [0, 255, 0],
    [0, 255, 255],
    [0, 0, 255],
    [255, 0, 255],
    [255, 255, 255],
];

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct Schedule {
    pub enabled: bool,
    pub weekdays: [bool; 7],
    pub hour: i32,
    pub minute: i32,
}

impl Default for Schedule {
    fn default() -> Self {
        Self {
            enabled: false,
            weekdays: [false; 7],
            hour: 0,
            minute: 0,
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct Settings {
    pub brightness: i32,
    pub speed: i32,
    pub gain: i32,
    pub reverse: bool,
    pub color_order: usize,
    pub pixels: i32,
    pub music_send: bool,
    pub volume: i32,
    pub auto_connect: bool,
    pub show_all: bool,
    pub power: bool,
    pub custom_colors: [[u8; 3]; 7],
    pub mode_selection: std::collections::BTreeMap<String, i32>,
    pub mode_category: String,
    pub mic_effect: i32,
    pub mic_source: usize,
    pub on: Schedule,
    pub off: Schedule,
    pub playlist: Vec<String>,
}

impl Default for Settings {
    fn default() -> Self {
        let mut mode_selection = std::collections::BTreeMap::new();
        for category in crate::modes::CATEGORIES {
            if let Some((id, _)) = category.modes.first() {
                mode_selection.insert(category.name.to_string(), *id);
            }
        }
        Self {
            brightness: 1000,
            speed: 50,
            gain: 100,
            reverse: false,
            color_order: 0,
            pixels: 60,
            music_send: true,
            volume: 80,
            auto_connect: true,
            show_all: false,
            power: true,
            custom_colors: DEFAULT_COLORS,
            mode_selection,
            mode_category: "Basic".into(),
            mic_effect: 1,
            mic_source: 0,
            on: Schedule::default(),
            off: Schedule::default(),
            playlist: Vec::new(),
        }
    }
}

impl Settings {
    pub fn config_path() -> Option<PathBuf> {
        directories::ProjectDirs::from("io", "github", "MRStar")
            .map(|dirs| dirs.config_dir().join("settings.json"))
    }

    pub fn load() -> Self {
        let Some(path) = Self::config_path() else {
            return Self::default();
        };
        let Ok(text) = fs::read_to_string(path) else {
            return Self::default();
        };
        serde_json::from_str(&text).unwrap_or_default()
    }

    pub fn save(&self) {
        let Some(path) = Self::config_path() else {
            return;
        };
        if let Some(parent) = path.parent() {
            let _ = fs::create_dir_all(parent);
        }
        if let Ok(text) = serde_json::to_string_pretty(self) {
            let _ = fs::write(path, text);
        }
    }
}
