//! egui desktop interface.

use std::path::Path;
use std::time::{Duration, Instant};

use chrono::Local;
use eframe::egui::{self, Color32, FontId, RichText, Sense, Stroke, TextureHandle, Vec2};

use crate::audio::{AudioLevel, MicController, MusicPlayer, BAND_COUNT};
use crate::ble::{BleClient, BleEvent, DeviceRecord};
use crate::modes;
use crate::protocol::{self, Notification, NotificationValue};
use crate::settings::{Schedule, Settings};

const ACCENT: Color32 = Color32::from_rgb(47, 129, 247);
const PANEL: Color32 = Color32::from_rgb(17, 21, 28);
const SIDEBAR: Color32 = Color32::from_rgb(22, 27, 36);
const CARD: Color32 = Color32::from_rgb(25, 31, 42);
const BORDER: Color32 = Color32::from_rgb(38, 48, 65);
const MUTED: Color32 = Color32::from_rgb(139, 152, 173);
const TEXT: Color32 = Color32::from_rgb(231, 237, 247);
const OK: Color32 = Color32::from_rgb(110, 231, 165);
const WARN: Color32 = Color32::from_rgb(255, 209, 102);

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Page {
    Color,
    Modes,
    Mic,
    Music,
    Schedule,
    Settings,
}

impl Page {
    const ALL: [Page; 6] = [
        Page::Color,
        Page::Modes,
        Page::Mic,
        Page::Music,
        Page::Schedule,
        Page::Settings,
    ];

    fn title(self) -> &'static str {
        match self {
            Page::Color => "Colour",
            Page::Modes => "Modes",
            Page::Mic => "Mic",
            Page::Music => "Music",
            Page::Schedule => "Schedule",
            Page::Settings => "Settings",
        }
    }
}

struct ColorWheel {
    texture: Option<TextureHandle>,
    size: usize,
}

impl ColorWheel {
    fn new() -> Self {
        Self {
            texture: None,
            size: 0,
        }
    }

    fn show(&mut self, ui: &mut egui::Ui, hue: f32, saturation: f32) -> Option<(f32, f32)> {
        let side = ui.available_width().min(300.0).max(180.0);
        let (rect, response) = ui.allocate_exact_size(Vec2::splat(side), Sense::click_and_drag());
        let size = 256;
        if self.texture.is_none() || self.size != size {
            let mut image = egui::ColorImage::new([size, size], Color32::TRANSPARENT);
            let center = (size as f32 - 1.0) / 2.0;
            let radius = size as f32 / 2.0 - 1.0;
            for y in 0..size {
                for x in 0..size {
                    let dx = x as f32 - center;
                    let dy = y as f32 - center;
                    let distance = (dx * dx + dy * dy).sqrt();
                    if distance > radius {
                        continue;
                    }
                    let h = (dy.atan2(dx).to_degrees() + 360.0) % 360.0;
                    let s = (distance / radius).clamp(0.0, 1.0);
                    let (r, g, b) = protocol::hsv_to_rgb(h, s, 1.0);
                    image.pixels[y * size + x] = Color32::from_rgb(r, g, b);
                }
            }
            self.texture = Some(ui.ctx().load_texture(
                "colour-wheel",
                image,
                egui::TextureOptions::LINEAR,
            ));
            self.size = size;
        }
        if let Some(texture) = &self.texture {
            ui.painter().image(
                texture.id(),
                rect,
                egui::Rect::from_min_max(egui::pos2(0.0, 0.0), egui::pos2(1.0, 1.0)),
                Color32::WHITE,
            );
        }
        let center = rect.center();
        let radius = rect.width() / 2.0 - 1.0;
        let angle = hue.to_radians();
        let marker =
            center + egui::vec2(angle.cos(), angle.sin()) * (saturation.clamp(0.0, 1.0) * radius);
        ui.painter().circle_stroke(
            marker,
            7.0,
            Stroke::new(2.0_f32, Color32::from_rgb(245, 248, 255)),
        );
        ui.painter()
            .circle_stroke(marker, 9.0, Stroke::new(1.0_f32, Color32::BLACK));
        if response.clicked() || response.dragged() {
            if let Some(position) = response.interact_pointer_pos() {
                let dx = position.x - center.x;
                let dy = position.y - center.y;
                let distance = (dx * dx + dy * dy).sqrt();
                let h = (dy.atan2(dx).to_degrees() + 360.0) % 360.0;
                let s = (distance / radius).clamp(0.0, 1.0);
                return Some((h, s));
            }
        }
        None
    }
}

pub struct MrStarApp {
    settings: Settings,
    ble: BleClient,
    devices: Vec<DeviceRecord>,
    selected_device: Option<String>,
    scanning: bool,
    page: Page,
    wheel: ColorWheel,
    hue: f32,
    saturation: f32,
    preview: [u8; 3],
    pending_color: Option<Vec<u8>>,
    last_color_sent: Instant,
    mic: MicController,
    mic_inputs: Vec<(usize, String)>,
    mic_input: Option<usize>,
    mic_level: AudioLevel,
    mic_preview: [u8; 3],
    last_mic_send: Instant,
    music: MusicPlayer,
    music_level: AudioLevel,
    selected_track: Option<usize>,
    music_path_input: String,
    last_music_send: Instant,
    last_music_analysis: Instant,
    sync_status: String,
    raw_hex: String,
    log: Vec<String>,
    status: String,
    dirty: bool,
    last_save: Instant,
}

impl MrStarApp {
    pub fn new(cc: &eframe::CreationContext<'_>) -> Self {
        configure_style(&cc.egui_ctx);
        let settings = Settings::load();
        let (hue, saturation, _) = protocol::rgb_to_hsv_android(
            settings.custom_colors[0][0],
            settings.custom_colors[0][1],
            settings.custom_colors[0][2],
        );
        let ble = BleClient::new();
        ble.configure(settings.auto_connect, settings.show_all);
        let mic_inputs = MicController::input_devices();
        let mut log = Vec::new();
        log.push("MR Star Rust desktop ready. Press Scan to find lights.".into());
        let mut app = Self {
            settings,
            hue,
            saturation,
            preview: [255, 0, 0],
            wheel: ColorWheel::new(),
            ble,
            devices: Vec::new(),
            selected_device: None,
            scanning: false,
            page: Page::Color,
            pending_color: None,
            last_color_sent: Instant::now() - Duration::from_secs(1),
            mic: MicController::new(),
            mic_inputs,
            mic_input: None,
            mic_level: AudioLevel::default(),
            mic_preview: [255, 0, 0],
            last_mic_send: Instant::now() - Duration::from_secs(1),
            music: MusicPlayer::new(),
            music_level: AudioLevel::default(),
            selected_track: None,
            music_path_input: String::new(),
            last_music_send: Instant::now() - Duration::from_secs(1),
            last_music_analysis: Instant::now() - Duration::from_secs(1),
            sync_status: "Not sent yet".into(),
            raw_hex: String::new(),
            log,
            status: "Ready. Press Scan to find lights.".into(),
            dirty: false,
            last_save: Instant::now(),
        };
        app.set_preview_from_hue();
        app
    }

    fn connected_count(&self) -> usize {
        self.devices
            .iter()
            .filter(|device| device.status == "connected")
            .count()
    }

    fn persist(&mut self) {
        self.dirty = true;
    }

    fn append_log(&mut self, message: impl Into<String>) {
        let stamp = Local::now().format("%H:%M:%S");
        self.log.push(format!("{stamp}  {}", message.into()));
        if self.log.len() > 600 {
            self.log.drain(0..self.log.len() - 600);
        }
    }

    fn set_preview_from_hue(&mut self) {
        let (r, g, b) = protocol::hsv_to_rgb(self.hue, self.saturation, 1.0);
        self.preview = [r, g, b];
    }

    fn queue_color(&mut self) {
        self.set_preview_from_hue();
        self.pending_color = Some(protocol::color_hsv(self.hue, self.saturation));
    }

    fn send_color_rgb(&mut self, red: u8, green: u8, blue: u8) {
        self.preview = [red, green, blue];
        let (hue, saturation) = rgb_to_hue_sat(red, green, blue);
        self.hue = hue;
        self.saturation = saturation;
        self.pending_color = Some(protocol::color_rgb(red, green, blue));
    }

    fn send_frame(&self, frame: Vec<u8>) {
        if self.connected_count() > 0 {
            self.ble.send(frame);
        }
    }

    fn send_power(&self) {
        self.send_frame(protocol::power(self.settings.power));
    }

    fn send_brightness(&self) {
        self.send_frame(protocol::brightness(self.settings.brightness));
    }

    fn send_schedule(&self, slot_on: bool) {
        let schedule = if slot_on {
            &self.settings.on
        } else {
            &self.settings.off
        };
        self.send_frame(protocol::set_timer(
            slot_on,
            schedule.enabled,
            schedule.weekdays,
            schedule.hour,
            schedule.minute,
        ));
    }

    fn handle_events(&mut self, ctx: &egui::Context) {
        for event in self.ble.drain() {
            match event {
                BleEvent::Devices(devices) => {
                    self.devices = devices;
                    if let Some(selected) = &self.selected_device {
                        if !self
                            .devices
                            .iter()
                            .any(|device| &device.address == selected)
                        {
                            self.selected_device = None;
                        }
                    }
                    if self.selected_device.is_none() {
                        self.selected_device =
                            self.devices.first().map(|device| device.address.clone());
                    }
                }
                BleEvent::Scanning(scanning) => self.scanning = scanning,
                BleEvent::Log(message) => {
                    self.status = message.clone();
                    self.append_log(message);
                }
                BleEvent::Notification(device, notification) => {
                    self.apply_notification(&notification);
                    self.append_log(format!(
                        "RX {device}: {}",
                        describe_notification(&notification)
                    ));
                }
            }
        }
        if self.connected_count() > 0 {
            ctx.request_repaint_after(Duration::from_millis(100));
        }
    }

    fn apply_notification(&mut self, notification: &Notification) {
        match &notification.value {
            NotificationValue::Brightness(value) => {
                self.settings.brightness = *value as i32;
                self.persist();
            }
            NotificationValue::Speed(value) => {
                self.settings.speed = *value as i32;
                self.persist();
            }
            NotificationValue::MicGain(value) => {
                self.settings.gain = *value as i32;
                self.persist();
            }
            NotificationValue::Timer(timer) => {
                let schedule = if timer.slot == "on" {
                    &mut self.settings.on
                } else {
                    &mut self.settings.off
                };
                schedule.enabled = timer.enabled;
                schedule.weekdays = timer.weekdays;
                schedule.hour = timer.hour as i32;
                schedule.minute = timer.minute as i32;
                self.persist();
                self.status = "Schedule read from device".into();
            }
            NotificationValue::None => {}
        }
    }

    fn tick_audio(&mut self) {
        if self.mic.running() {
            let level = self.mic.snapshot();
            self.mic_level = level.clone();
            if self.settings.mic_source == 1
                && self.last_mic_send.elapsed() >= Duration::from_millis(200)
                && level.peak > 0.004
            {
                let volume = level.peak * 32767.0 * self.settings.gain as f32 / 500.0;
                let hue = (volume as i32 % 140) as f32 * (360.0 / 140.0);
                self.mic_preview = protocol::hsv_to_rgb(hue, 1.0, 1.0).into();
                self.send_frame(protocol::mic_color_hsv(hue, 1.0));
                self.last_mic_send = Instant::now();
            }
        }
        let duration = self.music.duration();
        if duration > 0.0 && self.last_music_analysis.elapsed() >= Duration::from_millis(100) {
            let analysis = self.music.analysis();
            self.music_level = analysis.clone();
            if self.settings.music_send
                && self.music.playing()
                && self.last_music_send.elapsed() >= Duration::from_millis(200)
                && analysis.rms > 0.002
            {
                let hue = (analysis.dominant as i32 % 140) as f32 * (360.0 / 140.0);
                let saturation = (0.35 + analysis.rms * 12.0).min(1.0);
                self.send_frame(protocol::color_hsv(hue, saturation));
                self.last_music_send = Instant::now();
            }
            self.last_music_analysis = Instant::now();
        }
    }

    fn sidebar(&mut self, ctx: &egui::Context) {
        egui::SidePanel::left("sidebar")
            .exact_width(300.0)
            .resizable(false)
            .frame(
                egui::Frame::new()
                    .fill(SIDEBAR)
                    .inner_margin(18.0)
                    .stroke(Stroke::new(1.0_f32, BORDER)),
            )
            .show(ctx, |ui| {
                ui.horizontal(|ui| {
                    let (rect, _) = ui.allocate_exact_size(Vec2::splat(40.0), Sense::hover());
                    ui.painter().circle_filled(rect.center(), 18.0, ACCENT);
                    ui.painter().circle_filled(
                        rect.center(),
                        10.0,
                        Color32::from_rgb(255, 255, 255),
                    );
                    ui.vertical(|ui| {
                        ui.label(RichText::new("MR Star").size(20.0).strong());
                        ui.label(
                            RichText::new("BLE light controller")
                                .color(MUTED)
                                .size(12.0),
                        );
                    });
                });
                ui.add_space(10.0);
                let scan_text = if self.scanning {
                    "Stop scanning"
                } else {
                    "Scan for lights"
                };
                if ui
                    .add(
                        egui::Button::new(RichText::new(scan_text).strong())
                            .fill(ACCENT)
                            .stroke(Stroke::new(1.0_f32, ACCENT))
                            .min_size(Vec2::new(ui.available_width(), 32.0)),
                    )
                    .clicked()
                {
                    if self.scanning {
                        self.ble.stop_scan();
                    } else {
                        self.ble.scan();
                    }
                }
                ui.label(
                    RichText::new(if self.scanning {
                        "Scanning for 0x2022 advertisements"
                    } else {
                        "Not scanning"
                    })
                    .color(MUTED)
                    .size(12.0),
                );
                let auto = ui.checkbox(
                    &mut self.settings.auto_connect,
                    "Auto-connect matching lights",
                );
                if auto.changed() {
                    self.ble
                        .configure(self.settings.auto_connect, self.settings.show_all);
                    self.persist();
                }
                let show_all =
                    ui.checkbox(&mut self.settings.show_all, "Show every named BLE device");
                if show_all.changed() {
                    self.ble
                        .configure(self.settings.auto_connect, self.settings.show_all);
                    self.persist();
                }
                ui.add_space(4.0);
                ui.label(RichText::new("DEVICES").color(MUTED).size(11.0).strong());
                let devices = self.devices.clone();
                egui::ScrollArea::vertical()
                    .max_height(320.0)
                    .auto_shrink([false, false])
                    .show(ui, |ui| {
                        if devices.is_empty() {
                            ui.label(RichText::new("No lights discovered yet.").color(MUTED));
                        }
                        for device in &devices {
                            let selected =
                                self.selected_device.as_deref() == Some(device.address.as_str());
                            let status = if device.status == "connected" {
                                "connected"
                            } else if device.matched {
                                "MR Star"
                            } else {
                                "other"
                            };
                            let text = format!("{}\n{} dBm  ·  {status}", device.name, device.rssi);
                            if ui
                                .add(
                                    egui::Button::new(
                                        RichText::new(text)
                                            .color(if selected { TEXT } else { MUTED })
                                            .size(12.0),
                                    )
                                    .fill(if selected {
                                        Color32::from_rgb(36, 45, 60)
                                    } else {
                                        Color32::TRANSPARENT
                                    })
                                    .stroke(Stroke::NONE)
                                    .min_size(Vec2::new(ui.available_width(), 38.0)),
                                )
                                .clicked()
                            {
                                self.selected_device = Some(device.address.clone());
                            }
                        }
                    });
                ui.add_space(4.0);
                ui.horizontal(|ui| {
                    let connected = self
                        .selected_device
                        .as_ref()
                        .and_then(|address| self.devices.iter().find(|d| &d.address == address))
                        .map(|device| device.status == "connected")
                        .unwrap_or(false);
                    if ui
                        .add_enabled(
                            self.selected_device.is_some() && !connected,
                            egui::Button::new("Connect"),
                        )
                        .clicked()
                    {
                        if let Some(address) = self.selected_device.clone() {
                            self.ble.connect(address);
                        }
                    }
                    if ui
                        .add_enabled(connected, egui::Button::new("Disconnect"))
                        .clicked()
                    {
                        if let Some(address) = self.selected_device.clone() {
                            self.ble.disconnect(address);
                        }
                    }
                });
                if ui.button("Device settings").clicked() {
                    self.page = Page::Settings;
                }
                ui.with_layout(egui::Layout::bottom_up(egui::Align::LEFT), |ui| {
                    ui.label(
                        RichText::new("Desktop 1.0.0  ·  APK v1.0.0")
                            .color(Color32::from_rgb(95, 108, 129))
                            .size(11.0),
                    );
                });
            });
    }

    fn main_panel(&mut self, ctx: &egui::Context) {
        egui::CentralPanel::default()
            .frame(
                egui::Frame::new()
                    .fill(PANEL)
                    .inner_margin(egui::Margin::symmetric(24, 18)),
            )
            .show(ctx, |ui| {
                self.top_bar(ui);
                ui.add_space(10.0);
                egui::ScrollArea::vertical()
                    .auto_shrink([false, false])
                    .show(ui, |ui| match self.page {
                        Page::Color => self.color_page(ui),
                        Page::Modes => self.mode_page(ui),
                        Page::Mic => self.mic_page(ui),
                        Page::Music => self.music_page(ui),
                        Page::Schedule => self.schedule_page(ui),
                        Page::Settings => self.settings_page(ui),
                    });
            });
    }

    fn top_bar(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            ui.label(RichText::new(self.page.title()).size(22.0).strong());
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                let (text, color) = if self.scanning {
                    ("Scanning".to_string(), WARN)
                } else if self.connected_count() > 0 {
                    (format!("{} light(s) connected", self.connected_count()), OK)
                } else {
                    ("Disconnected".to_string(), MUTED)
                };
                egui::Frame::new()
                    .fill(Color32::from_rgb(35, 42, 56))
                    .corner_radius(10.0)
                    .inner_margin(egui::Margin::symmetric(12, 5))
                    .show(ui, |ui| {
                        ui.label(RichText::new(text).color(color).strong().size(12.0));
                    });
            });
        });
        ui.add_space(4.0);
        ui.horizontal(|ui| {
            for page in Page::ALL {
                let selected = page == self.page;
                let text = RichText::new(page.title())
                    .color(if selected { Color32::WHITE } else { MUTED })
                    .size(13.0);
                if ui
                    .add(
                        egui::Button::new(text)
                            .fill(if selected {
                                ACCENT
                            } else {
                                Color32::TRANSPARENT
                            })
                            .stroke(Stroke::NONE)
                            .corner_radius(7.0)
                            .min_size(Vec2::new(72.0, 28.0)),
                    )
                    .clicked()
                {
                    self.page = page;
                }
            }
        });
        ui.separator();
    }

    fn color_page(&mut self, ui: &mut egui::Ui) {
        ui.horizontal_top(|ui| {
            card(ui, "Colour wheel", |ui| {
                if let Some((hue, saturation)) = self.wheel.show(ui, self.hue, self.saturation) {
                    self.hue = hue;
                    self.saturation = saturation;
                    self.queue_color();
                }
                ui.horizontal(|ui| {
                    let (rect, _) = ui.allocate_exact_size(Vec2::splat(44.0), Sense::hover());
                    ui.painter().rect_filled(
                        rect,
                        10.0,
                        Color32::from_rgb(self.preview[0], self.preview[1], self.preview[2]),
                    );
                    ui.label(
                        RichText::new(format!(
                            "#{:02X}{:02X}{:02X}",
                            self.preview[0], self.preview[1], self.preview[2]
                        ))
                        .monospace()
                        .color(TEXT),
                    );
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        ui.label(
                            RichText::new(format!(
                                "{}, {}, {}",
                                self.preview[0], self.preview[1], self.preview[2]
                            ))
                            .color(MUTED),
                        );
                    });
                });
                ui.label(
                    RichText::new(
                        "Hue and saturation are sent to the strip; brightness is separate.",
                    )
                    .color(MUTED)
                    .size(12.0),
                );
            });
            ui.add_space(14.0);
            ui.vertical(|ui| {
                card(ui, "Power & brightness", |ui| {
                    if ui.checkbox(&mut self.settings.power, "Power").changed() {
                        self.send_power();
                        self.persist();
                    }
                    let mut brightness = self.settings.brightness;
                    if ui
                        .add(
                            egui::Slider::new(&mut brightness, protocol::MIN_BRIGHTNESS..=protocol::MAX_BRIGHTNESS)
                                .text("Brightness")
                                .step_by(1.0),
                        )
                        .changed()
                    {
                        self.settings.brightness = brightness;
                        self.send_brightness();
                        self.persist();
                    }
                    ui.label(
                        RichText::new("The APK clamps brightness to 3...1000.")
                            .color(MUTED)
                            .size(12.0),
                    );
                });
                ui.add_space(14.0);
                card(ui, "Colour presets", |ui| {
                    ui.label(
                        RichText::new(
                            "Custom slots  ·  right-click a slot to save the wheel colour",
                        )
                        .color(MUTED)
                        .size(12.0),
                    );
                    ui.horizontal(|ui| {
                        for index in 0..self.settings.custom_colors.len() {
                            let color = self.settings.custom_colors[index];
                            let response = ui.add(
                                egui::Button::new(" ")
                                    .fill(Color32::from_rgb(color[0], color[1], color[2]))
                                    .stroke(Stroke::new(1.0_f32, Color32::from_white_alpha(60)))
                                    .min_size(Vec2::splat(32.0)),
                            );
                            if response.clicked() {
                                self.send_color_rgb(color[0], color[1], color[2]);
                            }
                            if response.secondary_clicked() {
                                self.settings.custom_colors[index] = self.preview;
                                self.persist();
                            }
                        }
                    });
                    ui.add_space(4.0);
                    ui.label(RichText::new("Fixed palette").color(MUTED).size(12.0));
                    ui.horizontal(|ui| {
                        for color in [
                            [255, 0, 0],
                            [255, 255, 0],
                            [0, 255, 0],
                            [0, 255, 255],
                            [0, 0, 255],
                            [255, 0, 255],
                            [255, 254, 255],
                        ] {
                            if ui
                                .add(
                                    egui::Button::new(" ")
                                        .fill(Color32::from_rgb(color[0], color[1], color[2]))
                                        .stroke(Stroke::new(
                                            1.0_f32,
                                            Color32::from_white_alpha(60),
                                        ))
                                        .min_size(Vec2::splat(32.0)),
                                )
                                .clicked()
                            {
                                self.send_color_rgb(color[0], color[1], color[2]);
                            }
                        }
                    });
                    ui.label(
                        RichText::new(
                            "Preset frames use the APK's RGB-to-HSV conversion, including its achromatic saturation quirk.",
                        )
                        .color(MUTED)
                        .size(12.0),
                    );
                });
            });
        });
    }

    fn mode_page(&mut self, ui: &mut egui::Ui) {
        let category =
            modes::category_by_name(&self.settings.mode_category).unwrap_or(&modes::CATEGORIES[0]);
        ui.horizontal_top(|ui| {
            card(ui, "Categories", |ui| {
                for item in modes::CATEGORIES {
                    let label = if item.hidden {
                        format!("{}  (not in APK UI)", item.name)
                    } else {
                        item.name.to_string()
                    };
                    if ui
                        .selectable_label(self.settings.mode_category == item.name, label)
                        .clicked()
                    {
                        self.settings.mode_category = item.name.to_string();
                        self.persist();
                    }
                }
                ui.add_space(6.0);
                ui.label(
                    RichText::new(
                        "Flow (63...75) exists in the APK resources but the shipped tab strip never exposes it.",
                    )
                    .color(MUTED)
                    .size(12.0),
                );
            });
            ui.add_space(14.0);
            card(ui, "Animations", |ui| {
                let selected = self
                    .settings
                    .mode_selection
                    .get(category.name)
                    .copied()
                    .or_else(|| category.modes.first().map(|(id, _)| *id));
                egui::ScrollArea::vertical()
                    .max_height(330.0)
                    .auto_shrink([false, false])
                    .show(ui, |ui| {
                        for (id, name) in category.modes {
                            let label = format!("{name}   [{id}]");
                            if ui
                                .selectable_label(selected == Some(*id), label)
                                .clicked()
                            {
                                self.settings
                                    .mode_selection
                                    .insert(category.name.to_string(), *id);
                                self.send_frame(protocol::mode(*id));
                                self.persist();
                            }
                        }
                    });
                ui.label(
                    RichText::new(format!(
                        "Mode id: {}  ·  {}",
                        selected.map(|id| id.to_string()).unwrap_or_else(|| "—".into()),
                        selected.and_then(modes::mode_name).unwrap_or("")
                    ))
                    .color(MUTED)
                    .size(12.0),
                );
                let mut speed = self.settings.speed;
                if ui
                    .add(egui::Slider::new(&mut speed, 0..=100).text("Speed"))
                    .changed()
                {
                    self.settings.speed = speed;
                    self.send_frame(protocol::speed(speed));
                    self.persist();
                }
                let mut brightness = self.settings.brightness;
                if ui
                    .add(
                        egui::Slider::new(&mut brightness, protocol::MIN_BRIGHTNESS..=protocol::MAX_BRIGHTNESS).text("Brightness"),
                    )
                    .changed()
                {
                    self.settings.brightness = brightness;
                    self.send_brightness();
                    self.persist();
                }
                if ui
                    .checkbox(&mut self.settings.reverse, "Reverse direction")
                    .changed()
                {
                    self.send_frame(protocol::direction(!self.settings.reverse));
                    self.persist();
                }
            });
        });
    }

    fn mic_page(&mut self, ui: &mut egui::Ui) {
        ui.horizontal_top(|ui| {
            card(ui, "Microphone source", |ui| {
                let old_source = self.settings.mic_source;
                egui::ComboBox::from_id_salt("mic-source")
                    .selected_text(if old_source == 0 {
                        "Light's own microphone"
                    } else {
                        "This computer's microphone"
                    })
                    .show_ui(ui, |ui| {
                        ui.selectable_value(
                            &mut self.settings.mic_source,
                            0,
                            "Light's own microphone",
                        );
                        ui.selectable_value(
                            &mut self.settings.mic_source,
                            1,
                            "This computer's microphone",
                        );
                    });
                if old_source != self.settings.mic_source {
                    if self.settings.mic_source == 0 {
                        self.mic.stop();
                        self.mic_level = AudioLevel::default();
                    }
                    self.send_frame(protocol::mic_source(self.settings.mic_source == 0));
                    self.persist();
                }
                let old_effect = self.settings.mic_effect;
                egui::ComboBox::from_id_salt("mic-effect")
                    .selected_text(
                        protocol::MIC_EFFECTS
                            .iter()
                            .find(|(id, _)| *id as i32 == old_effect)
                            .map(|(_, name)| *name)
                            .unwrap_or("Energy"),
                    )
                    .show_ui(ui, |ui| {
                        for (id, name) in protocol::MIC_EFFECTS {
                            ui.selectable_value(&mut self.settings.mic_effect, id as i32, name);
                        }
                    });
                if old_effect != self.settings.mic_effect {
                    self.send_frame(protocol::mic_effect(self.settings.mic_effect));
                    self.persist();
                }
                let mut gain = self.settings.gain;
                if ui
                    .add(egui::Slider::new(&mut gain, 0..=100).text("Sensitivity"))
                    .changed()
                {
                    self.settings.gain = gain;
                    self.send_frame(protocol::mic_gain(gain));
                    self.persist();
                }
                ui.label(
                    RichText::new(
                        "Device mode programs the strip's built-in microphone. The APK labels the four effects Energy, Rhythm, Spectrum and Scroll.",
                    )
                    .color(MUTED)
                    .size(12.0),
                );
                ui.add_space(6.0);
                let (rect, _) = ui.allocate_exact_size(
                    Vec2::new(ui.available_width(), 44.0),
                    Sense::hover(),
                );
                ui.painter().rect_filled(
                    rect,
                    10.0,
                    Color32::from_rgb(
                        self.mic_preview[0],
                        self.mic_preview[1],
                        self.mic_preview[2],
                    ),
                );
            });
            ui.add_space(14.0);
            card(ui, "Computer microphone", |ui| {
                ui.horizontal(|ui| {
                    egui::ComboBox::from_id_salt("mic-input")
                        .selected_text(
                            self.mic_input
                                .and_then(|index| {
                                    self.mic_inputs
                                        .iter()
                                        .find(|(candidate, _)| *candidate == index)
                                        .map(|(_, name)| name.clone())
                                })
                                .unwrap_or_else(|| "Default input".into()),
                        )
                        .show_ui(ui, |ui| {
                            ui.selectable_value(&mut self.mic_input, None, "Default input");
                            for (index, name) in &self.mic_inputs {
                                ui.selectable_value(
                                    &mut self.mic_input,
                                    Some(*index),
                                    name.clone(),
                                );
                            }
                        });
                    if ui.button("Refresh").clicked() {
                        self.mic_inputs = MicController::input_devices();
                    }
                });
                let toggle = if self.mic.running() {
                    "Stop listening"
                } else {
                    "Start listening"
                };
                if ui
                    .add(
                        egui::Button::new(RichText::new(toggle).strong())
                            .fill(ACCENT)
                            .stroke(Stroke::new(1.0_f32, ACCENT))
                            .min_size(Vec2::new(ui.available_width(), 32.0)),
                    )
                    .clicked()
                {
                    if self.mic.running() {
                        self.mic.stop();
                        self.mic_level = AudioLevel::default();
                        if self.settings.mic_source == 1 {
                            self.settings.mic_source = 0;
                            self.send_frame(protocol::mic_source(true));
                        }
                        self.append_log("PC microphone stopped");
                    } else {
                        match self.mic.start(self.mic_input) {
                            Ok(()) => {
                                self.settings.mic_source = 1;
                                self.send_frame(protocol::mic_source(false));
                                self.append_log("PC microphone started");
                            }
                            Err(error) => {
                                self.status = format!("Microphone: {error}");
                                self.append_log(format!("Microphone: {error}"));
                            }
                        }
                    }
                    self.persist();
                }
                level_meter(ui, (self.mic_level.peak * 3.0).min(1.0));
                spectrum_view(ui, &self.mic_level.bands);
                ui.label(
                    RichText::new(
                        "PC mode sends 0x09 colour frames about five times per second, matching VoiceUtils in the APK. The strip's own mic is disabled while listening.",
                    )
                    .color(MUTED)
                    .size(12.0),
                );
            });
        });
    }

    fn music_page(&mut self, ui: &mut egui::Ui) {
        ui.horizontal_top(|ui| {
            card(ui, "Playlist", |ui| {
                egui::ScrollArea::vertical()
                    .max_height(250.0)
                    .auto_shrink([false, false])
                    .show(ui, |ui| {
                        let playlist = self.settings.playlist.clone();
                        for (index, path) in playlist.iter().enumerate() {
                            let name = Path::new(path)
                                .file_name()
                                .map(|name| name.to_string_lossy().into_owned())
                                .unwrap_or_else(|| path.clone());
                            let response = ui.selectable_label(
                                self.selected_track == Some(index),
                                name,
                            );
                            if response.clicked() {
                                self.selected_track = Some(index);
                            }
                            if response.double_clicked() {
                                self.load_track(index);
                            }
                        }
                        if self.settings.playlist.is_empty() {
                            ui.label(RichText::new("No tracks yet.").color(MUTED));
                        }
                    });
                ui.horizontal(|ui| {
                    ui.add(
                        egui::TextEdit::singleline(&mut self.music_path_input)
                            .hint_text("Path to an audio file")
                            .desired_width(180.0),
                    );
                    if ui.button("Add").clicked() {
                        let path = self.music_path_input.trim().to_string();
                        if !path.is_empty() && !self.settings.playlist.contains(&path) {
                            self.settings.playlist.push(path);
                            self.music_path_input.clear();
                            self.persist();
                        }
                    }
                });
                if ui.button("Remove selected").clicked() {
                    if let Some(index) = self.selected_track {
                        if index < self.settings.playlist.len() {
                            self.settings.playlist.remove(index);
                            self.selected_track = None;
                            self.persist();
                        }
                    }
                }
                ui.label(
                    RichText::new(
                        "Double-click a track to play it. Audio is decoded with ffmpeg.",
                    )
                    .color(MUTED)
                    .size(12.0),
                );
            });
            ui.add_space(14.0);
            card(ui, "Player", |ui| {
                let now_playing = self
                    .music
                    .path()
                    .and_then(|path| Path::new(path).file_name())
                    .map(|name| name.to_string_lossy().into_owned())
                    .unwrap_or_else(|| "Nothing playing".into());
                ui.label(RichText::new(now_playing).size(15.0).strong());
                ui.horizontal(|ui| {
                    if ui.button("Prev").clicked() {
                        self.step_track(-1);
                    }
                    let play_label = if self.music.playing() { "Pause" } else { "Play" };
                    if ui
                        .add(
                            egui::Button::new(RichText::new(play_label).strong())
                                .fill(ACCENT)
                                .stroke(Stroke::new(1.0_f32, ACCENT)),
                        )
                        .clicked()
                    {
                        if let Err(error) = self.music.toggle() {
                            self.status = error.clone();
                            self.append_log(error);
                        }
                    }
                    if ui.button("Stop").clicked() {
                        self.music.stop();
                    }
                    if ui.button("Next").clicked() {
                        self.step_track(1);
                    }
                });
                let duration = self.music.duration();
                let mut position = self.music.position();
                if ui
                    .add(
                        egui::Slider::new(&mut position, 0.0..=duration.max(0.01))
                            .show_value(false),
                    )
                    .changed()
                {
                    self.music.seek(position);
                }
                ui.horizontal(|ui| {
                    ui.label(RichText::new(format_time(self.music.position())).monospace());
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        ui.label(RichText::new(format_time(duration)).monospace());
                    });
                });
                let mut volume = self.settings.volume;
                if ui
                    .add(egui::Slider::new(&mut volume, 0..=100).text("Volume"))
                    .changed()
                {
                    self.settings.volume = volume;
                    self.music.set_volume(volume as f32 / 100.0);
                    self.persist();
                }
                if ui
                    .checkbox(
                        &mut self.settings.music_send,
                        "Send audio-reactive colours to the light",
                    )
                    .changed()
                {
                    self.persist();
                }
                spectrum_view(ui, &self.music_level.bands);
                level_meter(ui, (self.music_level.rms * 5.0).min(1.0));
                ui.label(
                    RichText::new(
                        "The APK uses Visualizer FFT data to pick a hue and sends 0x04 frames. This port uses the same idea on the decoded file.",
                    )
                    .color(MUTED)
                    .size(12.0),
                );
            });
        });
    }

    fn load_track(&mut self, index: usize) {
        let Some(path) = self.settings.playlist.get(index).cloned() else {
            return;
        };
        self.selected_track = Some(index);
        match self.music.load(&path) {
            Ok(duration) => {
                self.status = format!("Loaded {} ({})", display_name(&path), format_time(duration));
                self.append_log(self.status.clone());
                if let Err(error) = self.music.play() {
                    self.status = error.clone();
                    self.append_log(error);
                }
            }
            Err(error) => {
                self.status = format!("Music: {error}");
                self.append_log(self.status.clone());
            }
        }
    }

    fn step_track(&mut self, direction: i32) {
        if self.settings.playlist.is_empty() {
            return;
        }
        let current = self.selected_track.unwrap_or(0) as i32;
        let count = self.settings.playlist.len() as i32;
        let next = (current + direction).rem_euclid(count) as usize;
        self.load_track(next);
    }

    fn schedule_page(&mut self, ui: &mut egui::Ui) {
        let mut changed = false;
        ui.horizontal_top(|ui| {
            changed |= schedule_card(ui, "Schedule On", &mut self.settings.on);
            ui.add_space(14.0);
            changed |= schedule_card(ui, "Schedule Off", &mut self.settings.off);
        });
        if changed {
            self.persist();
        }
        ui.add_space(14.0);
        card(ui, "Device clock", |ui| {
            ui.horizontal(|ui| {
                if ui
                    .add(
                        egui::Button::new(RichText::new("Send schedule").strong())
                            .fill(ACCENT)
                            .stroke(Stroke::new(1.0_f32, ACCENT)),
                    )
                    .clicked()
                {
                    self.send_schedule(true);
                    self.send_schedule(false);
                    self.append_log("Schedule frames sent");
                }
                if ui.button("Read from device").clicked() {
                    self.send_frame(protocol::request_timer());
                    self.append_log("Requested schedules");
                }
                if ui.button("Sync computer time").clicked() {
                    self.send_frame(protocol::sync_time());
                    self.sync_status = "Sent computer time".into();
                    self.append_log("Clock sync frame sent");
                }
            });
            ui.label(
                RichText::new(
                    "The light reports schedules over 0xFFF4 (command 0x0D). Clock sync is reproduced exactly, including the APK's terminator-before-weekday quirk.",
                )
                .color(MUTED)
                .size(12.0),
            );
        });
    }

    fn settings_page(&mut self, ui: &mut egui::Ui) {
        ui.horizontal_top(|ui| {
            ui.vertical(|ui| {
                card(ui, "Strip wiring", |ui| {
                    ui.label(RichText::new("Colour order").color(MUTED));
                    let old_order = self.settings.color_order;
                    egui::ComboBox::from_id_salt("colour-order")
                        .selected_text(
                            protocol::COLOR_ORDERS
                                .get(self.settings.color_order)
                                .copied()
                                .unwrap_or("RGB"),
                        )
                        .show_ui(ui, |ui| {
                            for (index, name) in protocol::COLOR_ORDERS.iter().enumerate() {
                                ui.selectable_value(
                                    &mut self.settings.color_order,
                                    index,
                                    *name,
                                );
                            }
                        });
                    if old_order != self.settings.color_order {
                        self.send_frame(protocol::color_order(
                            self.settings.color_order as i32 + 1,
                        ));
                        self.persist();
                    }
                    ui.horizontal(|ui| {
                        ui.label("Pixels");
                        let mut pixels = self.settings.pixels;
                        if ui
                            .add(egui::DragValue::new(&mut pixels).range(8..=300))
                            .changed()
                        {
                            self.settings.pixels = pixels;
                        }
                        if ui.button("Apply").clicked() {
                            self.send_frame(protocol::color_order(
                                self.settings.color_order as i32 + 1,
                            ));
                            self.send_frame(protocol::pixel_count(self.settings.pixels));
                            self.append_log(format!(
                                "Applied {} order and {} pixels",
                                protocol::COLOR_ORDERS[self.settings.color_order],
                                self.settings.pixels
                            ));
                            self.persist();
                        }
                    });
                    ui.label(
                        RichText::new(
                            "Colour order (0x02) and pixel count (0x03) are global device settings. The APK accepts 8...300 pixels.",
                        )
                        .color(MUTED)
                        .size(12.0),
                    );
                });
                ui.add_space(14.0);
                card(ui, "Clock", |ui| {
                    if ui.button("Send computer time").clicked() {
                        self.send_frame(protocol::sync_time());
                        self.sync_status = "Sent computer time".into();
                        self.append_log("Clock sync frame sent");
                    }
                    ui.label(RichText::new(&self.sync_status).color(MUTED).size(12.0));
                });
                ui.add_space(14.0);
                card(ui, "Connection", |ui| {
                    ui.label(
                        RichText::new(format!(
                            "{} connected  ·  {} discovered",
                            self.connected_count(),
                            self.devices.len()
                        ))
                        .color(MUTED),
                    );
                    if ui.button("Disconnect all").clicked() {
                        self.ble.disconnect_all();
                    }
                });
            });
            ui.add_space(14.0);
            card(ui, "Protocol console", |ui| {
                ui.horizontal(|ui| {
                    ui.add(
                        egui::TextEdit::singleline(&mut self.raw_hex)
                            .hint_text("BC 05 06 03 E8 00 00 00 00 55")
                            .desired_width(320.0),
                    );
                    if ui.button("Send").clicked() {
                        match protocol::parse_hex(&self.raw_hex) {
                            Some(frame) => {
                                self.send_frame(frame);
                                self.raw_hex.clear();
                            }
                            None => {
                                self.status = "Invalid hex string.".into();
                                self.append_log("Invalid hex string.");
                            }
                        }
                    }
                });
                egui::ScrollArea::vertical()
                    .stick_to_bottom(true)
                    .max_height(470.0)
                    .auto_shrink([false, false])
                    .show(ui, |ui| {
                        for line in &self.log {
                            ui.label(RichText::new(line).monospace().size(11.0).color(MUTED));
                        }
                    });
            });
        });
    }
}

impl Drop for MrStarApp {
    fn drop(&mut self) {
        self.mic.stop();
        self.music.close();
        self.settings.save();
        self.ble.disconnect_all();
    }
}

impl eframe::App for MrStarApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.handle_events(ctx);
        if let Some(frame) = self.pending_color.take() {
            if self.last_color_sent.elapsed() >= Duration::from_millis(50) {
                self.send_frame(frame);
                self.last_color_sent = Instant::now();
            } else {
                self.pending_color = Some(frame);
            }
        }
        self.tick_audio();
        if self.dirty && self.last_save.elapsed() >= Duration::from_secs(1) {
            self.settings.save();
            self.dirty = false;
            self.last_save = Instant::now();
        }
        self.sidebar(ctx);
        self.main_panel(ctx);
        ctx.request_repaint_after(Duration::from_millis(100));
    }
}

fn configure_style(ctx: &egui::Context) {
    let mut style = (*ctx.style()).clone();
    style.visuals = egui::Visuals::dark();
    style.visuals.panel_fill = PANEL;
    style.visuals.window_fill = CARD;
    style.visuals.extreme_bg_color = Color32::from_rgb(15, 19, 26);
    style.visuals.override_text_color = Some(TEXT);
    style.visuals.widgets.inactive.bg_fill = Color32::from_rgb(35, 42, 56);
    style.visuals.widgets.hovered.bg_fill = Color32::from_rgb(43, 52, 69);
    style.visuals.widgets.active.bg_fill = Color32::from_rgb(30, 37, 49);
    style.visuals.selection.bg_fill = ACCENT;
    style.spacing.item_spacing = Vec2::new(8.0, 8.0);
    style.spacing.button_padding = Vec2::new(10.0, 6.0);
    style
        .text_styles
        .insert(egui::TextStyle::Heading, FontId::proportional(22.0));
    ctx.set_style(style);
}

fn card(ui: &mut egui::Ui, title: &str, add: impl FnOnce(&mut egui::Ui)) {
    egui::Frame::new()
        .fill(CARD)
        .stroke(Stroke::new(1.0_f32, BORDER))
        .corner_radius(12.0)
        .inner_margin(16.0)
        .show(ui, |ui| {
            ui.set_width(ui.available_width());
            ui.label(RichText::new(title).size(15.0).strong());
            ui.add_space(2.0);
            add(ui);
        });
}

fn level_meter(ui: &mut egui::Ui, value: f32) {
    let (rect, _) = ui.allocate_exact_size(Vec2::new(ui.available_width(), 12.0), Sense::hover());
    ui.painter()
        .rect_filled(rect, 6.0, Color32::from_rgb(30, 37, 49));
    let fill = egui::Rect::from_min_size(
        rect.min,
        Vec2::new(rect.width() * value.clamp(0.0, 1.0), rect.height()),
    );
    ui.painter().rect_filled(fill, 6.0, ACCENT);
}

fn spectrum_view(ui: &mut egui::Ui, bands: &[f32; BAND_COUNT]) {
    let (rect, _) = ui.allocate_exact_size(Vec2::new(ui.available_width(), 82.0), Sense::hover());
    ui.painter()
        .rect_filled(rect, 8.0, Color32::from_rgb(15, 19, 26));
    let gap = 2.0;
    let width = (rect.width() - gap * (BAND_COUNT as f32 + 1.0)) / BAND_COUNT as f32;
    for (index, value) in bands.iter().enumerate() {
        let height = (rect.height() - 8.0) * value.clamp(0.0, 1.0);
        let x = rect.left() + gap + index as f32 * (width + gap);
        let bar = egui::Rect::from_min_max(
            egui::pos2(x, rect.bottom() - 4.0 - height),
            egui::pos2(x + width, rect.bottom() - 4.0),
        );
        ui.painter().rect_filled(
            bar,
            2.0,
            Color32::from_rgb(60 + (index as u8 * 5), 130 + (index as u8 * 3), 230),
        );
    }
}

fn schedule_card(ui: &mut egui::Ui, title: &str, schedule: &mut Schedule) -> bool {
    let mut changed = false;
    card(ui, title, |ui| {
        changed |= ui.checkbox(&mut schedule.enabled, "Enabled").changed();
        ui.horizontal(|ui| {
            ui.label("Time");
            changed |= ui
                .add(egui::DragValue::new(&mut schedule.hour).range(0..=23))
                .changed();
            ui.label(":");
            changed |= ui
                .add(egui::DragValue::new(&mut schedule.minute).range(0..=59))
                .changed();
        });
        ui.horizontal(|ui| {
            for (index, label) in ["M", "T", "W", "TH", "F", "SA", "SU"].iter().enumerate() {
                if ui
                    .selectable_label(schedule.weekdays[index], *label)
                    .clicked()
                {
                    schedule.weekdays[index] = !schedule.weekdays[index];
                    changed = true;
                }
            }
        });
    });
    changed
}

fn rgb_to_hue_sat(red: u8, green: u8, blue: u8) -> (f32, f32) {
    let r = red as f32 / 255.0;
    let g = green as f32 / 255.0;
    let b = blue as f32 / 255.0;
    let max = r.max(g).max(b);
    let min = r.min(g).min(b);
    let delta = max - min;
    let hue = if delta == 0.0 {
        0.0
    } else if max == r {
        60.0 * (((g - b) / delta) % 6.0)
    } else if max == g {
        60.0 * ((b - r) / delta + 2.0)
    } else {
        60.0 * ((r - g) / delta + 4.0)
    };
    (
        (hue + 360.0) % 360.0,
        if max == 0.0 { 0.0 } else { delta / max },
    )
}

fn describe_notification(notification: &Notification) -> String {
    match &notification.value {
        NotificationValue::Brightness(value) => format!("brightness {value}"),
        NotificationValue::Speed(value) => format!("speed {value}"),
        NotificationValue::MicGain(value) => format!("mic gain {value}"),
        NotificationValue::Timer(timer) => format!(
            "timer {} {}:{:02} enabled={}",
            timer.slot, timer.hour, timer.minute, timer.enabled
        ),
        NotificationValue::None => format!("unknown {}", protocol::hexdump(&notification.raw)),
    }
}

fn display_name(path: &str) -> String {
    Path::new(path)
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_else(|| path.to_string())
}

fn format_time(seconds: f64) -> String {
    let seconds = seconds.max(0.0) as u64;
    format!("{}:{:02}", seconds / 60, seconds % 60)
}
