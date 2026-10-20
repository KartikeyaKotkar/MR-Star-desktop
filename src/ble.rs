//! Threaded BLE transport built on btleplug.

use std::collections::{HashMap, HashSet};
use std::time::{Duration, Instant};

use btleplug::api::{Central, CharPropFlags, Manager as _, Peripheral as _, ScanFilter, WriteType};
use btleplug::platform::{Adapter, Manager, Peripheral};
use crossbeam_channel::{Receiver, Sender};
use futures::StreamExt;
use tokio::sync::mpsc::{self, UnboundedReceiver, UnboundedSender};
use uuid::Uuid;

use crate::protocol;

pub const MAX_CONNECTIONS: usize = 7;
pub const SCAN_SECONDS: f32 = 8.0;

#[derive(Clone, Debug)]
pub struct DeviceRecord {
    pub address: String,
    pub name: String,
    pub rssi: i16,
    pub matched: bool,
    pub status: String,
}

#[derive(Clone, Debug)]
pub enum BleEvent {
    Devices(Vec<DeviceRecord>),
    Notification(String, protocol::Notification),
    Log(String),
    Scanning(bool),
}

#[derive(Debug)]
enum BleCommand {
    Scan(bool),
    Connect(String),
    Disconnect(String),
    DisconnectAll,
    Send(Vec<u8>),
    Config { auto_connect: bool, show_all: bool },
    Shutdown,
}

struct ConnectedDevice {
    peripheral: Peripheral,
    write: btleplug::api::Characteristic,
}

fn is_mr_star_advertisement(manufacturer_data: &HashMap<u16, Vec<u8>>, services: &[Uuid]) -> bool {
    manufacturer_data.contains_key(&protocol::MANUFACTURER_ID)
        || Uuid::parse_str(protocol::SERVICE_UUID)
            .map(|uuid| services.contains(&uuid))
            .unwrap_or(false)
}

struct Worker {
    central: Adapter,
    events: Sender<BleEvent>,
    devices: HashMap<String, DeviceRecord>,
    peripherals: HashMap<String, Peripheral>,
    connected: HashMap<String, ConnectedDevice>,
    attempted: HashSet<String>,
    manual_disconnect: HashSet<String>,
    reconnect_attempts: HashMap<String, u8>,
    reconnect_at: HashMap<String, Instant>,
    scanning: bool,
    scan_started: Option<Instant>,
    auto_connect: bool,
    show_all: bool,
}

impl Worker {
    fn new(central: Adapter, events: Sender<BleEvent>) -> Self {
        Self {
            central,
            events,
            devices: HashMap::new(),
            peripherals: HashMap::new(),
            connected: HashMap::new(),
            attempted: HashSet::new(),
            manual_disconnect: HashSet::new(),
            reconnect_attempts: HashMap::new(),
            reconnect_at: HashMap::new(),
            scanning: false,
            scan_started: None,
            auto_connect: true,
            show_all: false,
        }
    }

    fn log(&self, message: impl Into<String>) {
        let _ = self.events.send(BleEvent::Log(message.into()));
    }

    fn publish(&self) {
        let mut devices = self.devices.values().cloned().collect::<Vec<_>>();
        devices.sort_by(|left, right| {
            right
                .rssi
                .cmp(&left.rssi)
                .then_with(|| left.name.to_lowercase().cmp(&right.name.to_lowercase()))
                .then_with(|| left.address.cmp(&right.address))
        });
        let _ = self.events.send(BleEvent::Devices(devices));
        let _ = self.events.send(BleEvent::Scanning(self.scanning));
    }

    async fn start_scan(&mut self) -> Result<(), String> {
        if self.scanning {
            return Ok(());
        }
        self.devices
            .retain(|address, _| self.connected.contains_key(address));
        self.peripherals.clear();
        self.attempted.clear();
        // Publish the cleared list before awaiting the adapter. Otherwise a
        // failed or slow scan leaves stale rows in the UI whose peripherals
        // have already been dropped, so Connect reports "device is no longer
        // available".
        self.publish();
        if let Err(first_error) = self.central.start_scan(ScanFilter::default()).await {
            let retry = match Uuid::parse_str(protocol::SERVICE_UUID) {
                Ok(uuid) => {
                    self.central
                        .start_scan(ScanFilter {
                            services: vec![uuid],
                        })
                        .await
                }
                Err(_) => Err(first_error),
            };
            retry.map_err(|error| format!("BLE scan failed: {error}"))?;
        }
        self.scanning = true;
        self.scan_started = Some(Instant::now());
        self.log(format!(
            "Scanning for MR Star devices ({SCAN_SECONDS:.0}s)..."
        ));
        self.publish();
        Ok(())
    }

    async fn stop_scan(&mut self) {
        if !self.scanning {
            return;
        }
        if let Err(error) = self.central.stop_scan().await {
            self.log(format!("Could not stop scan: {error}"));
        }
        self.scanning = false;
        self.scan_started = None;
        self.log(format!("Scan finished ({} device(s))", self.devices.len()));
        self.publish();
    }

    async fn refresh(&mut self) {
        if let Some(started) = self.scan_started {
            if started.elapsed() >= Duration::from_secs_f32(SCAN_SECONDS) {
                self.stop_scan().await;
                return;
            }
        }
        match self.central.peripherals().await {
            Ok(peripherals) => {
                for peripheral in peripherals {
                    let id = peripheral.id().to_string();
                    let Ok(Some(properties)) = peripheral.properties().await else {
                        continue;
                    };
                    let name = properties
                        .local_name
                        .clone()
                        .or_else(|| properties.advertisement_name.clone())
                        .unwrap_or_default();
                    let matched = is_mr_star_advertisement(
                        &properties.manufacturer_data,
                        &properties.services,
                    );
                    if !matched && !(self.show_all && !name.is_empty()) {
                        continue;
                    }
                    if !self.peripherals.contains_key(&id) {
                        self.peripherals.insert(id.clone(), peripheral);
                    }
                    let status = if self.connected.contains_key(&id) {
                        "connected"
                    } else {
                        self.devices
                            .get(&id)
                            .map(|device| device.status.as_str())
                            .filter(|status| *status != "discovered")
                            .unwrap_or("discovered")
                    };
                    self.devices.insert(
                        id.clone(),
                        DeviceRecord {
                            address: id.clone(),
                            name: if name.is_empty() {
                                "MR Star device".into()
                            } else {
                                name
                            },
                            rssi: properties.rssi.unwrap_or(-127),
                            matched,
                            status: status.to_string(),
                        },
                    );
                }
            }
            Err(error) => self.log(format!("BLE discovery error: {error}")),
        }
        self.publish();
        self.auto_connect_candidates().await;
    }

    async fn auto_connect_candidates(&mut self) {
        if !self.auto_connect {
            return;
        }
        let candidates = self
            .devices
            .values()
            .filter(|device| {
                device.matched
                    && !self.connected.contains_key(&device.address)
                    && !self.attempted.contains(&device.address)
                    && !self.manual_disconnect.contains(&device.address)
            })
            .map(|device| device.address.clone())
            .collect::<Vec<_>>();
        for address in candidates {
            if self.connected.len() >= MAX_CONNECTIONS {
                break;
            }
            self.attempted.insert(address.clone());
            let _ = self.connect_device(&address).await;
        }
    }

    async fn connect_device(&mut self, address: &str) -> Result<(), String> {
        if self.connected.contains_key(address) {
            return Ok(());
        }
        if self.connected.len() >= MAX_CONNECTIONS {
            return Err(format!("connection limit ({MAX_CONNECTIONS}) reached"));
        }
        let peripheral = match self.peripherals.get(address).cloned() {
            Some(peripheral) => Some(peripheral),
            None => {
                // A scan restart clears the map before the OS list does. Look
                // the device up again instead of failing on an otherwise live
                // row.
                match self.central.peripherals().await {
                    Ok(peripherals) => peripherals
                        .into_iter()
                        .find(|peripheral| peripheral.id().to_string() == address),
                    Err(error) => {
                        self.log(format!("Could not refresh the BLE device list: {error}"));
                        None
                    }
                }
            }
        };
        let Some(peripheral) = peripheral else {
            let error = format!(
                "{address} is no longer visible to Bluetooth. Power the light on, keep it near the PC, and scan again."
            );
            log_error(&self.events, format!("Connect failed: {error}"));
            return Err(error);
        };
        self.peripherals
            .insert(address.to_string(), peripheral.clone());
        if let Some(record) = self.devices.get_mut(address) {
            record.status = "connecting".into();
        }
        self.publish();
        self.log(format!(
            "Connecting to {}...",
            self.devices
                .get(address)
                .map(|device| device.name.as_str())
                .unwrap_or(address)
        ));
        let result = async {
            peripheral
                .connect_with_timeout(Duration::from_secs(20))
                .await
                .map_err(|error| error.to_string())?;
            peripheral
                .discover_services_with_timeout(Duration::from_secs(15))
                .await
                .map_err(|error| error.to_string())?;
            let write_uuid =
                Uuid::parse_str(protocol::WRITE_UUID).map_err(|error| error.to_string())?;
            let notify_uuid =
                Uuid::parse_str(protocol::NOTIFY_UUID).map_err(|error| error.to_string())?;
            let characteristics = peripheral.characteristics();
            let Some(write) = characteristics
                .iter()
                .find(|characteristic| characteristic.uuid == write_uuid)
                .cloned()
            else {
                let found = characteristics
                    .iter()
                    .map(|characteristic| {
                        format!("{} ({:?})", characteristic.uuid, characteristic.properties)
                    })
                    .collect::<Vec<_>>()
                    .join(", ");
                return Err(if found.is_empty() {
                    "MR Star write characteristic 0xFFF3 not found; the device exposes no GATT characteristics".to_string()
                } else {
                    format!(
                        "MR Star write characteristic 0xFFF3 not found; device exposes: {found}"
                    )
                });
            };
            if let Some(notify) = characteristics
                .iter()
                .find(|characteristic| characteristic.uuid == notify_uuid)
            {
                if notify.properties.contains(CharPropFlags::NOTIFY)
                    || notify.properties.contains(CharPropFlags::INDICATE)
                {
                    peripheral
                        .subscribe(notify)
                        .await
                        .map_err(|error| format!("notifications unavailable: {error}"))?;
                    let mut stream = peripheral
                        .notifications()
                        .await
                        .map_err(|error| format!("notifications unavailable: {error}"))?;
                    let events = self.events.clone();
                    let label = self
                        .devices
                        .get(address)
                        .map(|device| device.name.clone())
                        .unwrap_or_else(|| address.to_string());
                    tokio::spawn(async move {
                        while let Some(notification) = stream.next().await {
                            let parsed = protocol::parse_notification(&notification.value);
                            let _ = events.send(BleEvent::Notification(label.clone(), parsed));
                        }
                    });
                }
            }
            Ok::<_, String>((peripheral.clone(), write))
        }
        .await;

        match result {
            Ok((peripheral, write)) => {
                self.connected
                    .insert(address.to_string(), ConnectedDevice { peripheral, write });
                self.attempted.remove(address);
                self.manual_disconnect.remove(address);
                self.reconnect_attempts.remove(address);
                self.reconnect_at.remove(address);
                if let Some(record) = self.devices.get_mut(address) {
                    record.status = "connected".into();
                }
                self.log(format!(
                    "Connected to {}",
                    self.devices
                        .get(address)
                        .map(|device| device.name.as_str())
                        .unwrap_or(address)
                ));
                self.publish();
                self.write_to(address, &protocol::request_timer()).await;
                Ok(())
            }
            Err(error) => {
                log_error(&self.events, format!("Connect failed: {error}"));
                let _ = peripheral.disconnect().await;
                if let Some(record) = self.devices.get_mut(address) {
                    record.status = "disconnected".into();
                }
                self.publish();
                Err(error)
            }
        }
    }

    async fn disconnect_device(&mut self, address: &str) {
        self.manual_disconnect.insert(address.to_string());
        self.attempted.remove(address);
        self.reconnect_at.remove(address);
        if let Some(connected) = self.connected.remove(address) {
            let _ = connected.peripheral.disconnect().await;
            self.log(format!("Disconnected from {address}"));
        }
        if let Some(record) = self.devices.get_mut(address) {
            record.status = "disconnected".into();
        }
        self.publish();
    }

    async fn disconnect_all(&mut self) {
        let addresses = self.connected.keys().cloned().collect::<Vec<_>>();
        for address in addresses {
            self.disconnect_device(&address).await;
        }
    }

    async fn write_to(&self, address: &str, frame: &[u8]) {
        let Some(connected) = self.connected.get(address) else {
            return;
        };
        let attempts = if frame.len() > 1
            && matches!(
                frame[1],
                protocol::CMD_SYNC_TIME | protocol::CMD_READ_TIMER | 0x50
            ) {
            2
        } else {
            1
        };
        for attempt in 0..attempts {
            match connected
                .peripheral
                .write(&connected.write, frame, WriteType::WithResponse)
                .await
            {
                Ok(()) => break,
                Err(error) => {
                    if attempt + 1 < attempts {
                        tokio::time::sleep(Duration::from_millis(50)).await;
                    } else {
                        log_error(&self.events, format!("Write failed ({address}): {error}"));
                    }
                }
            }
        }
    }

    async fn send(&mut self, frame: Vec<u8>) {
        if frame.is_empty() {
            return;
        }
        if self.connected.is_empty() {
            self.log("No lights connected");
            return;
        }
        self.log(format!("TX {}", protocol::hexdump(&frame)));
        let addresses = self.connected.keys().cloned().collect::<Vec<_>>();
        for address in addresses {
            self.write_to(&address, &frame).await;
        }
    }

    async fn health_check(&mut self) {
        let addresses = self.connected.keys().cloned().collect::<Vec<_>>();
        let mut lost = Vec::new();
        for address in addresses {
            if let Some(connected) = self.connected.get(&address) {
                match connected.peripheral.is_connected().await {
                    Ok(true) => {}
                    _ => lost.push(address),
                }
            }
        }
        for address in lost {
            self.connected.remove(&address);
            if let Some(record) = self.devices.get_mut(&address) {
                record.status = "disconnected".into();
            }
            self.log(format!("Connection lost: {address}"));
            if self.auto_connect && !self.manual_disconnect.contains(&address) {
                let attempts = self.reconnect_attempts.entry(address.clone()).or_insert(0);
                if *attempts < 3 {
                    *attempts += 1;
                    self.reconnect_at
                        .insert(address.clone(), Instant::now() + Duration::from_secs(4));
                }
            }
            self.publish();
        }
        let now = Instant::now();
        let due = self
            .reconnect_at
            .iter()
            .filter(|(_, when)| **when <= now)
            .map(|(address, _)| address.clone())
            .collect::<Vec<_>>();
        for address in due {
            self.reconnect_at.remove(&address);
            if !self.connected.contains_key(&address) {
                let _ = self.connect_device(&address).await;
            }
        }
    }
}

fn log_error(events: &Sender<BleEvent>, message: String) {
    let _ = events.send(BleEvent::Log(message));
}

pub struct BleClient {
    commands: UnboundedSender<BleCommand>,
    events: Receiver<BleEvent>,
}

impl BleClient {
    pub fn new() -> Self {
        let (commands, command_rx) = mpsc::unbounded_channel();
        let (event_tx, event_rx) = crossbeam_channel::unbounded();
        let _ = std::thread::Builder::new()
            .name("mrstar-ble".into())
            .spawn(move || {
                let runtime = match tokio::runtime::Builder::new_multi_thread()
                    .enable_all()
                    .build()
                {
                    Ok(runtime) => runtime,
                    Err(error) => {
                        let _ = event_tx.send(BleEvent::Log(format!(
                            "Could not start BLE runtime: {error}"
                        )));
                        return;
                    }
                };
                runtime.block_on(run(command_rx, event_tx));
            });
        Self {
            commands,
            events: event_rx,
        }
    }

    pub fn scan(&self) {
        let _ = self.commands.send(BleCommand::Scan(true));
    }

    pub fn stop_scan(&self) {
        let _ = self.commands.send(BleCommand::Scan(false));
    }

    pub fn connect(&self, address: String) {
        let _ = self.commands.send(BleCommand::Connect(address));
    }

    pub fn disconnect(&self, address: String) {
        let _ = self.commands.send(BleCommand::Disconnect(address));
    }

    pub fn disconnect_all(&self) {
        let _ = self.commands.send(BleCommand::DisconnectAll);
    }

    pub fn send(&self, frame: Vec<u8>) {
        let _ = self.commands.send(BleCommand::Send(frame));
    }

    pub fn configure(&self, auto_connect: bool, show_all: bool) {
        let _ = self.commands.send(BleCommand::Config {
            auto_connect,
            show_all,
        });
    }

    pub fn drain(&self) -> Vec<BleEvent> {
        let mut events = Vec::new();
        while let Ok(event) = self.events.try_recv() {
            events.push(event);
        }
        events
    }
}

impl Drop for BleClient {
    fn drop(&mut self) {
        let _ = self.commands.send(BleCommand::Shutdown);
    }
}

async fn run(mut commands: UnboundedReceiver<BleCommand>, events: Sender<BleEvent>) {
    let manager = match Manager::new().await {
        Ok(manager) => manager,
        Err(error) => {
            log_error(&events, format!("Bluetooth unavailable: {error}"));
            return;
        }
    };
    let adapters = match manager.adapters().await {
        Ok(adapters) => adapters,
        Err(error) => {
            log_error(
                &events,
                format!("Could not list Bluetooth adapters: {error}"),
            );
            return;
        }
    };
    let Some(central) = adapters.into_iter().next() else {
        log_error(&events, "No Bluetooth adapter found".into());
        return;
    };
    let mut worker = Worker::new(central, events.clone());
    let mut ticker = tokio::time::interval(Duration::from_millis(500));
    let mut health = tokio::time::interval(Duration::from_secs(2));
    loop {
        tokio::select! {
            command = commands.recv() => {
                let Some(command) = command else { break };
                match command {
                    BleCommand::Scan(true) => {
                        if let Err(error) = worker.start_scan().await {
                            worker.log(error);
                        }
                    }
                    BleCommand::Scan(false) => worker.stop_scan().await,
                    BleCommand::Connect(address) => {
                        worker.manual_disconnect.remove(&address);
                        worker.attempted.remove(&address);
                        if let Err(error) = worker.connect_device(&address).await {
                            worker.log(error);
                        }
                    }
                    BleCommand::Disconnect(address) => worker.disconnect_device(&address).await,
                    BleCommand::DisconnectAll => worker.disconnect_all().await,
                    BleCommand::Send(frame) => worker.send(frame).await,
                    BleCommand::Config { auto_connect, show_all } => {
                        worker.auto_connect = auto_connect;
                        worker.show_all = show_all;
                        worker.publish();
                    }
                    BleCommand::Shutdown => {
                        worker.stop_scan().await;
                        worker.disconnect_all().await;
                        break;
                    }
                }
            }
            _ = ticker.tick(), if worker.scanning => {
                worker.refresh().await;
            }
            _ = health.tick() => {
                worker.health_check().await;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn matches_mr_star_company_id() {
        let manufacturer_data = HashMap::from([(protocol::MANUFACTURER_ID, vec![0])]);
        assert!(is_mr_star_advertisement(&manufacturer_data, &[]));
    }

    #[test]
    fn matches_mr_star_service_uuid() {
        let service = Uuid::parse_str(protocol::SERVICE_UUID).unwrap();
        assert!(is_mr_star_advertisement(&HashMap::new(), &[service]));
    }

    #[test]
    fn rejects_unrelated_advertisement() {
        let manufacturer_data = HashMap::from([(0x1234, vec![0])]);
        let service = Uuid::parse_str("0000180f-0000-1000-8000-00805f9b34fb").unwrap();
        assert!(!is_mr_star_advertisement(&manufacturer_data, &[service]));
    }
}
