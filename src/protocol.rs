//! Wire protocol for the MR Star BLE light controller.
//!
//! This is a direct port of the Python implementation and preserves the
//! Android app's quirks, including the mode divide-by-255 and the clock frame
//! whose terminator sits before the weekday.

use chrono::{DateTime, Datelike, Local, Timelike};
use serde::{Deserialize, Serialize};

pub const SERVICE_UUID: &str = "0000fff0-0000-1000-8000-00805f9b34fb";
pub const WRITE_UUID: &str = "0000fff3-0000-1000-8000-00805f9b34fb";
pub const NOTIFY_UUID: &str = "0000fff4-0000-1000-8000-00805f9b34fb";
pub const MANUFACTURER_ID: u16 = 0x2022;

pub const START_BYTE: u8 = 0xBC;
pub const END_BYTE: u8 = 0x55;

pub const CMD_POWER: u8 = 0x01;
pub const CMD_COLOR_ORDER: u8 = 0x02;
pub const CMD_PIXEL_COUNT: u8 = 0x03;
pub const CMD_COLOR: u8 = 0x04;
pub const CMD_BRIGHTNESS: u8 = 0x05;
pub const CMD_MODE: u8 = 0x06;
pub const CMD_DIRECTION: u8 = 0x07;
pub const CMD_SPEED: u8 = 0x08;
pub const CMD_MIC_COLOR: u8 = 0x09;
pub const CMD_SYNC_TIME: u8 = 0x0B;
pub const CMD_READ_TIMER: u8 = 0x0C;
pub const CMD_SET_TIMER: u8 = 0x0D;
pub const CMD_MIC_SOURCE: u8 = 0x0F;
pub const CMD_MIC_EFFECT: u8 = 0x11;
pub const CMD_MIC_GAIN: u8 = 0x12;
#[allow(dead_code)]
pub const CMD_HUE_ONLY: u8 = 0x13;

pub const MIN_BRIGHTNESS: i32 = 3;
pub const MAX_BRIGHTNESS: i32 = 1000;
pub const MIN_PIXELS: u16 = 8;
pub const MAX_PIXELS: u16 = 300;

pub const COLOR_ORDERS: [&str; 6] = ["RGB", "RBG", "GRB", "GBR", "BRG", "BGR"];
pub const MIC_EFFECTS: [(u8, &str); 4] =
    [(1, "Energy"), (2, "Rhythm"), (3, "Spectrum"), (4, "Scroll")];

pub fn frame(command: u8, payload: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(payload.len() + 4);
    out.push(START_BYTE);
    out.push(command);
    out.push(payload.len() as u8);
    out.extend_from_slice(payload);
    out.push(END_BYTE);
    out
}

fn u16_bytes(value: u16) -> [u8; 2] {
    [(value >> 8) as u8, value as u8]
}

pub fn power(on: bool) -> Vec<u8> {
    frame(CMD_POWER, &[if on { 0 } else { 1 }])
}

pub fn color_order(index: i32) -> Vec<u8> {
    frame(CMD_COLOR_ORDER, &[index.clamp(1, 6) as u8])
}

pub fn pixel_count(count: i32) -> Vec<u8> {
    let value = count.clamp(MIN_PIXELS as i32, MAX_PIXELS as i32) as u16;
    let bytes = u16_bytes(value);
    frame(CMD_PIXEL_COUNT, &bytes)
}

pub fn brightness(value: i32) -> Vec<u8> {
    let bytes = u16_bytes(value.clamp(0, 0xFFFF) as u16);
    frame(CMD_BRIGHTNESS, &[bytes[0], bytes[1], 0, 0, 0, 0])
}

pub fn mode(mode_id: i32) -> Vec<u8> {
    let value = mode_id.clamp(0, 0xFFFF) as u32;
    frame(
        CMD_MODE,
        &[((value / 255) & 0xFF) as u8, (value % 255) as u8],
    )
}

pub fn direction(forward: bool) -> Vec<u8> {
    frame(CMD_DIRECTION, &[if forward { 0 } else { 1 }])
}

pub fn speed(value: i32) -> Vec<u8> {
    frame(CMD_SPEED, &[value.clamp(0, 100) as u8])
}

#[allow(dead_code)]
pub fn hue_only(hue_degrees: i32) -> Vec<u8> {
    let bytes = u16_bytes(hue_degrees.clamp(0, 360) as u16);
    frame(CMD_HUE_ONLY, &bytes)
}

pub fn mic_source(device_mic: bool) -> Vec<u8> {
    frame(CMD_MIC_SOURCE, &[if device_mic { 1 } else { 0 }])
}

pub fn mic_effect(effect: i32) -> Vec<u8> {
    frame(CMD_MIC_EFFECT, &[effect.clamp(1, 4) as u8])
}

pub fn mic_gain(value: i32) -> Vec<u8> {
    frame(CMD_MIC_GAIN, &[value.clamp(0, 100) as u8])
}

pub fn hsv_to_rgb(hue_degrees: f32, saturation: f32, value: f32) -> (u8, u8, u8) {
    let h = (hue_degrees.rem_euclid(360.0)) / 60.0;
    let s = saturation.clamp(0.0, 1.0);
    let v = value.clamp(0.0, 1.0);
    let sector = h.floor();
    let f = h - sector;
    let p = v * (1.0 - s);
    let q = v * (1.0 - f * s);
    let t = v * (1.0 - (1.0 - f) * s);
    let (r, g, b) = match sector as i32 % 6 {
        0 => (v, t, p),
        1 => (q, v, p),
        2 => (p, v, t),
        3 => (p, q, v),
        4 => (t, p, v),
        _ => (v, p, q),
    };
    ((r * 255.0) as u8, (g * 255.0) as u8, (b * 255.0) as u8)
}

pub fn rgb_to_hsv_android(red: u8, green: u8, blue: u8) -> (f32, f32, f32) {
    let r = red as f32 / 255.0;
    let g = green as f32 / 255.0;
    let b = blue as f32 / 255.0;
    let max = r.max(g).max(b);
    let min = r.min(g).min(b);
    let delta = max - min;
    let mut hue = if delta == 0.0 {
        0.0
    } else if max == r {
        60.0 * (((g - b) / delta) % 6.0)
    } else if max == g {
        60.0 * ((b - r) / delta + 2.0)
    } else {
        60.0 * ((r - g) / delta + 4.0)
    };
    if hue < 0.0 {
        hue += 360.0;
    }
    let mut saturation = if max == 0.0 { 0.0 } else { delta / max };
    if saturation > 1.0 || (hue == 0.0 && saturation == 0.0) {
        saturation = 1.0;
    }
    (hue, saturation, max)
}

fn hsv_payload(hue_degrees: f32, saturation: f32) -> [u8; 6] {
    let hue = hue_degrees.clamp(0.0, 360.0) as u16;
    let sat = (saturation.clamp(0.0, 1.0) * 1000.0) as u16;
    let h = u16_bytes(hue);
    let s = u16_bytes(sat);
    [h[0], h[1], s[0], s[1], 0, 0]
}

pub fn color_hsv(hue_degrees: f32, saturation: f32) -> Vec<u8> {
    frame(CMD_COLOR, &hsv_payload(hue_degrees, saturation))
}

pub fn color_rgb(red: u8, green: u8, blue: u8) -> Vec<u8> {
    let (hue, sat, _) = rgb_to_hsv_android(red, green, blue);
    color_hsv(hue, sat)
}

#[allow(dead_code)]
pub fn mic_color_rgb(red: u8, green: u8, blue: u8) -> Vec<u8> {
    let (hue, sat, _) = rgb_to_hsv_android(red, green, blue);
    mic_color_hsv(hue, sat)
}

pub fn mic_color_hsv(hue_degrees: f32, saturation: f32) -> Vec<u8> {
    frame(CMD_MIC_COLOR, &hsv_payload(hue_degrees, saturation))
}

pub fn request_timer() -> Vec<u8> {
    frame(CMD_READ_TIMER, &[1])
}

pub fn set_timer(
    slot_on: bool,
    enabled: bool,
    weekdays: [bool; 7],
    hour: i32,
    minute: i32,
) -> Vec<u8> {
    let mut mask = 0u8;
    for (index, selected) in weekdays.iter().enumerate() {
        if *selected {
            mask |= 1 << index;
        }
    }
    let payload = [
        1,
        if slot_on { 1 } else { 0 },
        if enabled { 1 } else { 0 },
        mask,
        hour.clamp(0, 23) as u8,
        minute.clamp(0, 59) as u8,
    ];
    frame(CMD_SET_TIMER, &payload)
}

pub fn sync_time() -> Vec<u8> {
    sync_time_at(Local::now())
}

pub fn sync_time_at(now: DateTime<Local>) -> Vec<u8> {
    let year = u16_bytes(now.year().clamp(0, 0xFFFF) as u16);
    let weekday = now.weekday().number_from_monday() as u8;
    vec![
        START_BYTE,
        CMD_SYNC_TIME,
        7,
        year[0],
        year[1],
        now.month() as u8,
        now.day() as u8,
        now.hour() as u8,
        now.minute() as u8,
        now.second() as u8,
        END_BYTE,
        weekday,
    ]
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct TimerValue {
    pub slot: String,
    pub enabled: bool,
    pub weekdays: [bool; 7],
    pub hour: u8,
    pub minute: u8,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub enum NotificationValue {
    Brightness(u16),
    Speed(u8),
    MicGain(u8),
    Timer(TimerValue),
    None,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Notification {
    pub command: i16,
    pub kind: String,
    pub value: NotificationValue,
    pub raw: Vec<u8>,
}

pub fn parse_notification(data: &[u8]) -> Notification {
    let raw = data.to_vec();
    if raw.len() < 2 {
        return Notification {
            command: -1,
            kind: "unknown".into(),
            value: NotificationValue::None,
            raw,
        };
    }
    let command = raw[1];
    let mut note = Notification {
        command: command as i16,
        kind: "unknown".into(),
        value: NotificationValue::None,
        raw,
    };
    if command == CMD_BRIGHTNESS && note.raw.len() >= 5 {
        note.kind = "brightness".into();
        note.value =
            NotificationValue::Brightness(((note.raw[3] as u16) << 8) | note.raw[4] as u16);
    } else if command == CMD_SPEED && note.raw.len() >= 4 {
        note.kind = "speed".into();
        note.value = NotificationValue::Speed(note.raw[3]);
    } else if command == CMD_MIC_GAIN && note.raw.len() >= 4 {
        note.kind = "mic_gain".into();
        note.value = NotificationValue::MicGain(note.raw[3]);
    } else if command == CMD_SET_TIMER && note.raw.len() >= 9 {
        note.kind = "timer".into();
        let mut weekdays = [false; 7];
        for (bit, selected) in weekdays.iter_mut().enumerate() {
            *selected = (note.raw[6] >> bit) & 1 == 1;
        }
        note.value = NotificationValue::Timer(TimerValue {
            slot: if note.raw[4] == 1 { "on" } else { "off" }.into(),
            enabled: note.raw[5] == 1,
            weekdays,
            hour: note.raw[7],
            minute: note.raw[8],
        });
    }
    note
}

pub fn hexdump(data: &[u8]) -> String {
    data.iter()
        .map(|byte| format!("{byte:02X}"))
        .collect::<Vec<_>>()
        .join(" ")
}

pub fn parse_hex(text: &str) -> Option<Vec<u8>> {
    let cleaned = text.replace(',', " ").replace("0x", " ").replace("0X", " ");
    let mut bytes = Vec::new();
    for token in cleaned.split_whitespace() {
        if token.is_empty() {
            continue;
        }
        if token.len() % 2 == 0 && token.len() > 2 {
            for chunk in token.as_bytes().chunks(2) {
                let part = std::str::from_utf8(chunk).ok()?;
                bytes.push(u8::from_str_radix(part, 16).ok()?);
            }
        } else {
            bytes.push(u8::from_str_radix(token, 16).ok()?);
        }
    }
    if bytes.is_empty() {
        None
    } else {
        Some(bytes)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hex(frame: &[u8]) -> String {
        frame.iter().map(|b| format!("{b:02x}")).collect()
    }

    #[test]
    fn frames_match_apk() {
        assert_eq!(hex(&power(true)), "bc01010055");
        assert_eq!(hex(&power(false)), "bc01010155");
        assert_eq!(hex(&pixel_count(300)), "bc0302012c55");
        assert_eq!(hex(&brightness(1000)), "bc050603e80000000055");
        assert_eq!(hex(&mode(300)), "bc0602012d55");
        assert_eq!(hex(&mode(0xFFFF)), "bc0602010055");
        assert_eq!(hex(&color_rgb(0, 255, 0)), "bc0406007803e8000055");
        assert_eq!(hex(&color_hsv(200.0, 0.5)), "bc040600c801f4000055");
        assert_eq!(hex(&mic_color_hsv(120.0, 1.0)), "bc0906007803e8000055");
        assert_eq!(
            hex(&set_timer(
                true,
                true,
                [true, false, false, false, false, false, false],
                7,
                5
            )),
            "bc0d0601010101070555"
        );
        assert_eq!(
            hex(&set_timer(
                false,
                false,
                [false, false, false, false, false, false, true],
                23,
                59
            )),
            "bc0d0601000040173b55"
        );
    }

    #[test]
    fn achromatic_quirk() {
        for color in [(0, 0, 0), (255, 255, 255), (128, 128, 128)] {
            let (hue, saturation, _) = rgb_to_hsv_android(color.0, color.1, color.2);
            assert_eq!(hue, 0.0);
            assert_eq!(saturation, 1.0);
        }
    }

    #[test]
    fn notifications() {
        let n = parse_notification(&[0xbc, 0x05, 0x06, 0x03, 0xe8, 0, 0, 0, 0, 0x55]);
        assert_eq!(n.kind, "brightness");
        assert_eq!(n.value, NotificationValue::Brightness(1000));
        let n = parse_notification(&[0xbc, 0x0d, 0x06, 0x01, 0x01, 0x01, 0x01, 0x07, 0x05, 0x55]);
        assert!(matches!(n.value, NotificationValue::Timer(_)));
    }

    #[test]
    fn parse_raw_hex() {
        assert_eq!(
            parse_hex("BC 05 06 03 E8 00 00 00 00 55").unwrap().len(),
            10
        );
        assert_eq!(parse_hex("bc,05,06").unwrap(), vec![0xbc, 0x05, 0x06]);
    }

    #[test]
    fn clock_frame_keeps_apk_quirk() {
        use chrono::TimeZone;
        let when = Local
            .with_ymd_and_hms(2026, 10, 20, 15, 30, 0)
            .single()
            .unwrap();
        let frame = sync_time_at(when);
        assert_eq!(hex(&frame), "bc0b0707ea0a140f1e005502");
        assert_eq!(frame[2], 7);
        assert_eq!(frame[frame.len() - 2], 0x55);
        assert_eq!(frame[frame.len() - 1], 2);
    }
}
