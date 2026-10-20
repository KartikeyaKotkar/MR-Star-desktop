#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod app;
mod audio;
mod ble;
mod modes;
mod protocol;
mod settings;

use std::sync::Arc;

fn main() {
    if std::env::args().any(|arg| arg == "--smoke-test")
        || std::env::var_os("MRSTAR_SMOKE_TEST").is_some()
    {
        smoke_test();
        return;
    }
    if std::env::args().any(|arg| arg == "--version" || arg == "-V") {
        println!("MR Star Rust {}", env!("CARGO_PKG_VERSION"));
        return;
    }
    if let Err(error) = run() {
        eprintln!("MR Star failed to start: {error}");
        std::process::exit(1);
    }
}

fn run() -> eframe::Result<()> {
    let icon = eframe::icon_data::from_png_bytes(include_bytes!("../../mrstar/assets/icon.png"))
        .ok()
        .map(Arc::new);
    let mut viewport = eframe::egui::ViewportBuilder::default()
        .with_inner_size([1180.0, 780.0])
        .with_min_inner_size([900.0, 600.0])
        .with_title("MR Star");
    if let Some(icon) = icon {
        viewport = viewport.with_icon(icon);
    }
    let options = eframe::NativeOptions {
        viewport,
        renderer: eframe::Renderer::Glow,
        ..Default::default()
    };
    eframe::run_native(
        "MR Star",
        options,
        Box::new(|cc| Ok(Box::new(app::MrStarApp::new(cc)))),
    )
}

fn smoke_test() {
    assert_eq!(protocol::power(true), vec![0xbc, 0x01, 0x01, 0x00, 0x55]);
    assert_eq!(
        protocol::color_rgb(0, 255, 0),
        vec![0xbc, 0x04, 0x06, 0x00, 0x78, 0x03, 0xe8, 0x00, 0x00, 0x55]
    );
    assert_eq!(
        modes::CATEGORIES
            .iter()
            .map(|category| category.modes.len())
            .sum::<usize>(),
        71
    );
    let settings = settings::Settings::default();
    assert!(settings.pixels >= protocol::MIN_PIXELS as i32);
    println!("MR Star Rust smoke test passed");
}
