"""BLE transport for MR Star lights.

The Android app uses com.clj.fastble with:

* service ``0000FFF0-...``
* write characteristic ``0000FFF3-...`` (write with response)
* notify characteristic ``0000FFF4-...``
* advertisement filter company id ``0x2022``
* up to seven simultaneous connections

This module keeps the same behaviour on top of bleak, which works on Linux
(BlueZ), macOS and Windows.  All asyncio work lives on a private thread so
Qt does not need an asyncio event loop.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Callable

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice

from . import protocol

MAX_CONNECTIONS = 7
SCAN_SECONDS = 8.0
RECONNECT_ATTEMPTS = 3
RECONNECT_DELAY = 4.0


@dataclass
class DeviceRecord:
    address: str
    name: str
    rssi: int
    matched: bool
    status: str = "discovered"  # discovered | connecting | connected | disconnected
    ble_device: BLEDevice | None = field(default=None, repr=False)


class BleClient:
    """Threaded BLE client with broadcast writes and auto-reconnect."""

    def __init__(
        self,
        on_state: Callable[[], None] | None = None,
        on_notification: Callable[[protocol.Notification], None] | None = None,
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        self._on_state = on_state or (lambda: None)
        self._on_notification = on_notification or (lambda _n: None)
        self._on_log = on_log or (lambda _m: None)

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="mrstar-ble", daemon=True)
        self._ready = threading.Event()
        # Guards the dictionaries that the Qt thread reads while the BLE
        # thread mutates them.
        self._state_lock = threading.RLock()

        self._devices: dict[str, DeviceRecord] = {}
        self._clients: dict[str, BleakClient] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._reconnect_attempts: dict[str, int] = {}
        self._reconnect_tasks: dict[str, asyncio.Task] = {}
        self._intentional: set[str] = set()
        self._scan_task: asyncio.Task | None = None
        self._scanner: BleakScanner | None = None
        self._scanning = False
        self._auto_connect = True
        self._show_all = False
        self._closing = False

        self._pending: dict[str, bytes] = {}
        self._flushing: set[str] = set()

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._thread.start()
        self._ready.wait(3.0)

    def shutdown(self) -> None:
        self._closing = True
        if not self._loop.is_running():
            return
        future = asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)
        try:
            future.result(5.0)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(3.0)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    async def _shutdown(self) -> None:
        tasks: list[asyncio.Task] = []
        if self._scan_task is not None:
            tasks.append(self._scan_task)
        tasks.extend(self._reconnect_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        scanner = self._scanner
        self._scanner = None
        if scanner is not None:
            try:
                await scanner.stop()
            except Exception:
                pass
        with self._state_lock:
            addresses = list(self._clients)
        if addresses:
            await asyncio.gather(
                *(self._disconnect(address, intentional=True, notify=False) for address in addresses),
                return_exceptions=True,
            )

    def _schedule(self, coroutine) -> None:
        if self._closing or not self._loop.is_running():
            coroutine.close()
            return
        asyncio.run_coroutine_threadsafe(coroutine, self._loop)

    def _emit_state(self) -> None:
        try:
            self._on_state()
        except Exception:
            pass

    def _log(self, message: str) -> None:
        try:
            self._on_log(message)
        except Exception:
            pass

    # ------------------------------------------------------------------ settings
    @property
    def auto_connect(self) -> bool:
        return self._auto_connect

    @auto_connect.setter
    def auto_connect(self, value: bool) -> None:
        self._auto_connect = bool(value)

    @property
    def show_all(self) -> bool:
        return self._show_all

    @show_all.setter
    def show_all(self, value: bool) -> None:
        self._show_all = bool(value)

    @property
    def scanning(self) -> bool:
        return self._scanning

    def devices(self) -> list[DeviceRecord]:
        with self._state_lock:
            records = list(self._devices.values())
        return sorted(
            records,
            key=lambda d: (-d.rssi, d.name.lower(), d.address),
        )

    def connected_addresses(self) -> list[str]:
        with self._state_lock:
            clients = list(self._clients.items())
        return [a for a, c in clients if c.is_connected]

    # ------------------------------------------------------------------ scanning
    def scan(self, duration: float = SCAN_SECONDS) -> None:
        self._schedule(self._scan(duration))

    def stop_scan(self) -> None:
        self._schedule(self._stop_scan())

    async def _stop_scan(self) -> None:
        task = self._scan_task
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
        scanner = self._scanner
        self._scanner = None
        if scanner is not None:
            try:
                await scanner.stop()
            except Exception:
                pass
        self._scanning = False
        self._emit_state()

    async def _scan(self, duration: float) -> None:
        await self._stop_scan()
        self._scan_task = asyncio.current_task()
        # Keep live connections visible, drop stale discoveries like the app.
        with self._state_lock:
            for address in list(self._devices):
                if address not in self._clients:
                    del self._devices[address]
        scanner = BleakScanner(detection_callback=self._on_detection)
        self._scanner = scanner
        try:
            await scanner.start()
        except Exception as exc:
            if self._scanner is scanner:
                self._scanner = None
            self._log(f"BLE scan failed: {exc}")
            self._scanning = False
            self._emit_state()
            return
        self._scanning = True
        self._log(f"Scanning for MR Star devices ({duration:.0f}s)…")
        self._emit_state()
        try:
            await asyncio.sleep(duration)
        finally:
            if self._scanner is scanner:
                self._scanner = None
            try:
                await scanner.stop()
            except Exception:
                pass
            self._scanning = False
            if self._scan_task is asyncio.current_task():
                self._scan_task = None
            self._emit_state()
            self._log(f"Scan finished ({len(self._devices)} device(s))")

    def _on_detection(self, device: BLEDevice, advertisement) -> None:
        if self._closing:
            return
        manufacturer_data = advertisement.manufacturer_data or {}
        matched = protocol.MANUFACTURER_ID in manufacturer_data
        name = advertisement.local_name or device.name or ""
        if not matched and not (self._show_all and name):
            return
        if not name:
            name = "MR Star device"

        address = device.address
        with self._state_lock:
            existing = self._devices.get(address)
            status = existing.status if existing else "discovered"
            if address in self._clients:
                status = "connected"
            self._devices[address] = DeviceRecord(
                address=address,
                name=name,
                rssi=advertisement.rssi
                if advertisement.rssi is not None
                else getattr(device, "rssi", -127),
                matched=matched,
                status=status,
                ble_device=device,
            )
            client_count = len(self._clients)

        if (
            matched
            and self._auto_connect
            and status in ("discovered", "disconnected")
            and client_count < MAX_CONNECTIONS
        ):
            asyncio.ensure_future(self._connect(address))

    # ------------------------------------------------------------------ connections
    def connect(self, address: str) -> None:
        self._schedule(self._connect(address))

    async def _connect(self, address: str) -> None:
        if self._closing:
            return
        if address in self._clients:
            return
        record = self._devices.get(address)
        target = record.ble_device if record and record.ble_device else address
        if record:
            if record.status == "connecting":
                return
            record.status = "connecting"
            self._emit_state()
        self._intentional.discard(address)
        self._log(f"Connecting to {record.name if record else address}…")

        client = BleakClient(
            target,
            timeout=20.0,
            disconnected_callback=lambda c: self._on_disconnect(address, c),
        )
        try:
            await client.connect()
            if not client.is_connected:
                raise RuntimeError("connection lost during setup")
            try:
                await client.start_notify(protocol.NOTIFY_UUID, self._on_notify)
            except Exception as exc:
                # Control still works without the notify characteristic;
                # only device-state reports and schedules are lost.
                self._log(f"Notifications unavailable ({address}): {exc}")
            if not client.is_connected:
                raise RuntimeError("connection lost during setup")
        except Exception as exc:
            try:
                await client.disconnect()
            except Exception:
                pass
            if record:
                record.status = "disconnected"
            self._emit_state()
            self._log(f"Connect failed: {exc}")
            self._schedule_reconnect(address)
            return

        with self._state_lock:
            self._clients[address] = client
            self._locks[address] = asyncio.Lock()
            self._reconnect_attempts[address] = 0
            if record:
                record.status = "connected"
        self._log(f"Connected to {record.name if record else address}")
        self._emit_state()
        # The app only subscribes when the scheduler is opened; doing it on
        # connect simply makes state reports available earlier.
        await self._send_frame(protocol.request_timer())

    def disconnect(self, address: str) -> None:
        self._schedule(self._disconnect(address, intentional=True))

    async def _disconnect(self, address: str, intentional: bool = True, notify: bool = True) -> None:
        if intentional:
            self._intentional.add(address)
        task = self._reconnect_tasks.pop(address, None)
        if task:
            task.cancel()
        with self._state_lock:
            client = self._clients.pop(address, None)
            self._locks.pop(address, None)
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass
            self._log(f"Disconnected from {address}")
        if address in self._devices:
            self._devices[address].status = "disconnected"
        if notify:
            self._emit_state()

    def disconnect_all(self) -> None:
        with self._state_lock:
            addresses = list(self._clients)
        for address in addresses:
            self.disconnect(address)

    def _on_disconnect(self, address: str, client: BleakClient) -> None:
        with self._state_lock:
            if self._clients.get(address) is not client:
                return
            self._clients.pop(address, None)
            self._locks.pop(address, None)
        if address in self._devices:
            self._devices[address].status = "disconnected"
        self._log(f"Connection lost: {address}")
        self._emit_state()
        if not self._closing and address not in self._intentional:
            self._schedule_reconnect(address)

    def _schedule_reconnect(self, address: str) -> None:
        if self._closing or not self._auto_connect or address in self._intentional:
            return
        attempts = self._reconnect_attempts.get(address, 0)
        if attempts >= RECONNECT_ATTEMPTS:
            return
        self._reconnect_attempts[address] = attempts + 1
        existing = self._reconnect_tasks.pop(address, None)
        if existing:
            existing.cancel()

        async def reconnect() -> None:
            await asyncio.sleep(RECONNECT_DELAY)
            if not self._closing and address not in self._clients:
                await self._connect(address)

        self._reconnect_tasks[address] = asyncio.ensure_future(reconnect())

    # ------------------------------------------------------------------ data
    def send(self, frame: bytes, coalesce: str | None = None) -> None:
        """Write a frame to every connected light.

        ``coalesce`` names a replaceable stream (colour updates, for
        example): only the newest frame is kept while a write is in flight.
        """
        if not frame or not self._loop.is_running():
            return
        self._loop.call_soon_threadsafe(self._enqueue, bytes(frame), coalesce)

    def _enqueue(self, frame: bytes, coalesce: str | None) -> None:
        if not self._clients:
            return
        self._log(f"TX {protocol.hexdump(frame)}")
        if coalesce:
            self._pending[coalesce] = frame
            if coalesce not in self._flushing:
                self._flushing.add(coalesce)
                asyncio.ensure_future(self._flush(coalesce))
        else:
            asyncio.ensure_future(self._send_frame(frame))

    async def _flush(self, key: str) -> None:
        try:
            while key in self._pending:
                frame = self._pending.pop(key)
                await self._send_frame(frame)
        finally:
            self._flushing.discard(key)

    async def _send_frame(self, frame: bytes) -> None:
        retry = len(frame) > 1 and frame[1] in protocol.RETRY_COMMANDS
        attempts = 2 if retry else 1
        for address, client in list(self._clients.items()):
            lock = self._locks.get(address)
            if lock is None:
                continue
            async with lock:
                for attempt in range(attempts):
                    try:
                        await client.write_gatt_char(protocol.WRITE_UUID, frame, response=True)
                        break
                    except Exception as exc:
                        if attempt + 1 < attempts:
                            await asyncio.sleep(0.05)
                            continue
                        self._log(f"Write failed ({address}): {exc}")

    # ------------------------------------------------------------------ notifications
    def _on_notify(self, _characteristic, data: bytearray) -> None:
        notification = protocol.parse_notification(bytes(data))
        try:
            self._on_notification(notification)
        except Exception:
            pass
        if notification.kind != "unknown":
            self._log(f"RX {notification.kind}: {notification.value}")
        else:
            self._log(f"RX {protocol.hexdump(bytes(data))}")
