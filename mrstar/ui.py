"""Qt user interface for the MR Star desktop controller."""

from __future__ import annotations

import colorsys
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QPointF, QRectF, QSettings, QSize, Qt, QTime, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTimeEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import __version__, protocol
from .audio import BAND_COUNT, MusicPlayer, MicAnalyzer
from .ble import BleClient, DeviceRecord
from .modes import CATEGORIES, CATEGORY_BY_NAME

ICON_PATH = Path(__file__).resolve().parent / "assets" / "icon.png"
DEFAULT_COLORS = (
    (255, 0, 0),
    (255, 255, 0),
    (0, 255, 0),
    (0, 255, 255),
    (0, 0, 255),
    (255, 0, 255),
    (255, 255, 255),
)
FIXED_COLORS = (
    (255, 0, 0),
    (255, 255, 0),
    (0, 255, 0),
    (0, 255, 255),
    (0, 0, 255),
    (255, 0, 255),
    (255, 254, 255),
)
WEEK_LABELS = ("M", "T", "W", "TH", "F", "SA", "SU")


# --------------------------------------------------------------------------- widgets
class LabeledSlider(QWidget):
    changed = Signal(int)
    released = Signal(int)

    def __init__(self, text: str, minimum: int, maximum: int, value: int, suffix: str = "") -> None:
        super().__init__()
        self._suffix = suffix
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        header = QHBoxLayout()
        self._label = QLabel(text)
        self._value = QLabel()
        self._value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._value.setObjectName("muted")
        header.addWidget(self._label)
        header.addStretch(1)
        header.addWidget(self._value)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(value)
        layout.addLayout(header)
        layout.addWidget(self.slider)
        self.slider.valueChanged.connect(self._on_value)
        self.slider.sliderReleased.connect(lambda: self.released.emit(self.slider.value()))
        self._on_value(value)

    def _on_value(self, value: int) -> None:
        self._value.setText(f"{value}{self._suffix}")
        self.changed.emit(value)

    def value(self) -> int:
        return self.slider.value()

    def set_value(self, value: int) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(int(value))
        self.slider.blockSignals(False)
        self._on_value(self.slider.value())


class ColorWheel(QWidget):
    picked = Signal(int, int, int)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(240, 240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._hue = 0.0
        self._sat = 1.0
        self._image: QImage | None = None
        self._image_size = 0
        self._dragging = False

    def set_rgb(self, red: int, green: int, blue: int, emit: bool = False) -> None:
        hue, sat, _ = colorsys.rgb_to_hsv(red / 255.0, green / 255.0, blue / 255.0)
        self._hue = hue * 360.0
        self._sat = sat if sat > 0.0 else 0.0
        self.update()
        if emit:
            self.picked.emit(red, green, blue)

    def rgb(self) -> tuple[int, int, int]:
        red, green, blue = colorsys.hsv_to_rgb(self._hue / 360.0, self._sat, 1.0)
        return int(red * 255), int(green * 255), int(blue * 255)

    def _wheel_image(self, size: int) -> QImage:
        if self._image is not None and self._image_size == size:
            return self._image
        yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
        cx = cy = (size - 1) / 2.0
        radius = size / 2.0 - 1.0
        dx = xx - cx
        dy = yy - cy
        distance = np.sqrt(dx * dx + dy * dy)
        inside = distance <= radius
        hue = (np.arctan2(dy, dx) / (2.0 * np.pi)) % 1.0
        sat = np.clip(distance / radius, 0.0, 1.0)
        value = np.ones_like(hue)
        sector = np.floor(hue * 6.0)
        fraction = hue * 6.0 - sector
        p = value * (1.0 - sat)
        q = value * (1.0 - fraction * sat)
        t = value * (1.0 - (1.0 - fraction) * sat)
        red = np.select(
            [sector == 0, sector == 1, sector == 2, sector == 3, sector == 4, sector == 5],
            [value, q, p, p, t, value],
        )
        green = np.select(
            [sector == 0, sector == 1, sector == 2, sector == 3, sector == 4, sector == 5],
            [t, value, value, q, p, p],
        )
        blue = np.select(
            [sector == 0, sector == 1, sector == 2, sector == 3, sector == 4, sector == 5],
            [p, p, t, value, value, q],
        )
        rgba = np.zeros((size, size, 4), dtype=np.uint8)
        rgba[..., 0] = (red * 255).astype(np.uint8)
        rgba[..., 1] = (green * 255).astype(np.uint8)
        rgba[..., 2] = (blue * 255).astype(np.uint8)
        rgba[..., 3] = np.where(inside, 255, 0).astype(np.uint8)
        self._image = QImage(
            rgba.tobytes(), size, size, size * 4, QImage.Format_RGBA8888
        ).copy()
        self._image_size = size
        return self._image

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height())
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        image = self._wheel_image(max(2, int(side)))
        painter.drawImage(rect, image)
        radius = side / 2.0 - 1.0
        cx = rect.center().x()
        cy = rect.center().y()
        angle = math.radians(self._hue)
        marker = QPointF(
            cx + math.cos(angle) * radius * self._sat,
            cy + math.sin(angle) * radius * self._sat,
        )
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(0, 0, 0, 190), 4))
        painter.drawEllipse(marker, 8, 8)
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.drawEllipse(marker, 8, 8)

    def _pick(self, position: QPointF) -> None:
        side = min(self.width(), self.height())
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        radius = side / 2.0 - 1.0
        dx = position.x() - cx
        dy = position.y() - cy
        distance = math.hypot(dx, dy)
        self._sat = min(1.0, distance / radius) if radius > 0 else 0.0
        self._hue = math.degrees(math.atan2(dy, dx)) % 360.0
        self.update()
        self.picked.emit(*self.rgb())

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._pick(event.position())

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self._pick(event.position())

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._dragging = False


class LevelMeter(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(12)
        self._level = 0.0

    def set_level(self, level: float) -> None:
        level = max(0.0, min(1.0, float(level)))
        if abs(level - self._level) > 0.005:
            self._level = level
            self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#232a38"))
        painter.drawRoundedRect(rect, 6, 6)
        if self._level > 0:
            fill = QRectF(0, 0, self.width() * self._level, self.height())
            gradient = QLinearGradient(0, 0, self.width(), 0)
            gradient.setColorAt(0.0, QColor("#37d67a"))
            gradient.setColorAt(0.7, QColor("#ffd166"))
            gradient.setColorAt(1.0, QColor("#ff5c7a"))
            painter.setBrush(gradient)
            painter.drawRoundedRect(fill, 6, 6)


class SpectrumView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(90)
        self._bars = np.zeros(BAND_COUNT, dtype=np.float32)

    def set_bars(self, bars) -> None:
        self._bars = np.asarray(bars, dtype=np.float32)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        width = self.width()
        height = self.height()
        gap = 2
        bar_width = max(1.0, (width - gap * (BAND_COUNT - 1)) / BAND_COUNT)
        for index, value in enumerate(self._bars):
            x = index * (bar_width + gap)
            bar_height = max(2.0, float(value) * (height - 4))
            gradient = QLinearGradient(0, height, 0, height - bar_height)
            gradient.setColorAt(0.0, QColor("#2f81f7"))
            gradient.setColorAt(0.6, QColor("#57d9c4"))
            gradient.setColorAt(1.0, QColor("#ffd166"))
            painter.fillRect(QRectF(x, height - bar_height, bar_width, bar_height), gradient)


class WeekdaySelector(QWidget):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._buttons: list[QToolButton] = []
        for label in WEEK_LABELS:
            button = QToolButton()
            button.setText(label)
            button.setCheckable(True)
            button.setFixedSize(38, 30)
            button.setObjectName("weekday")
            button.toggled.connect(self._on_toggled)
            layout.addWidget(button)
            self._buttons.append(button)
        layout.addStretch(1)
        self._updating = False

    def _on_toggled(self, _checked: bool) -> None:
        if not self._updating:
            self.changed.emit()

    def mask(self) -> int:
        mask = 0
        for index, button in enumerate(self._buttons):
            if button.isChecked():
                mask |= 1 << index
        return mask

    def weekdays(self) -> tuple[bool, ...]:
        return tuple(button.isChecked() for button in self._buttons)

    def set_mask(self, mask: int) -> None:
        self._updating = True
        for index, button in enumerate(self._buttons):
            button.setChecked(bool(mask & (1 << index)))
        self._updating = False


class ColorButton(QPushButton):
    def __init__(self, color: QColor, savable: bool = False) -> None:
        super().__init__()
        self.setFixedSize(38, 38)
        self.setCursor(Qt.PointingHandCursor)
        self._color = QColor(color)
        self.savable = savable
        self._apply()

    def _apply(self) -> None:
        self.setStyleSheet(
            "QPushButton {"
            f"background: {self._color.name()};"
            "border: 2px solid rgba(255,255,255,0.22);"
            "border-radius: 9px;"
            "}"
            "QPushButton:hover { border-color: rgba(255,255,255,0.65); }"
        )
        self.setToolTip(self._color.name().upper())

    def color(self) -> QColor:
        return QColor(self._color)

    def set_color(self, color: QColor) -> None:
        self._color = QColor(color)
        self._apply()


class DeviceBridge(QObject):
    state = Signal()
    notification = Signal(object)
    log = Signal(str)


# --------------------------------------------------------------------------- main window
class MainWindow(QMainWindow):
    PAGE_TITLES = (
        "Colour adjustment",
        "Light modes",
        "Microphone",
        "Music",
        "Schedule",
        "Settings",
    )

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MR Star")
        self.resize(1180, 780)
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))

        self.settings = QSettings("MRStar", "MRStarDesktop")
        self.bridge = DeviceBridge()
        self.ble = BleClient(
            on_state=self.bridge.state.emit,
            on_notification=self.bridge.notification.emit,
            on_log=self.bridge.log.emit,
        )
        self.mic = MicAnalyzer()
        self.player = MusicPlayer()

        self._device_signature: tuple = ()
        self._device_items: dict[str, QListWidgetItem] = {}
        self._connected_count = 0
        self._pc_mic = False
        self._pending_color: bytes | None = None
        self._color_timer = QTimer(self)
        self._color_timer.setSingleShot(True)
        self._color_timer.setInterval(50)
        self._color_timer.timeout.connect(self._flush_color)
        self._custom_colors = [QColor(*c) for c in DEFAULT_COLORS]
        self._selected_slot = 0
        self._pixels = 60
        self._mode_selection: dict[str, int] = {}
        self._initializing = True
        self._applying_notification = False
        self._last_music_send = 0.0
        self._last_mic_send = 0.0
        self._playlist: list[str] = []
        self._play_index = -1
        self._seek_dragging = False
        self._inputs_loaded = False

        self._build()
        self._load_settings()
        self._connect_signals()
        self._start_timers()
        self.ble.start()
        self._initializing = False
        self._refresh_status()

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(24, 18, 24, 14)
        right_layout.setSpacing(14)
        root.addWidget(right, 1)

        top = QHBoxLayout()
        self.page_title = QLabel(self.PAGE_TITLES[0])
        self.page_title.setObjectName("pageTitle")
        self.status_pill = QLabel("Disconnected")
        self.status_pill.setObjectName("statusPill")
        top.addWidget(self.page_title)
        top.addStretch(1)
        top.addWidget(self.status_pill)
        right_layout.addLayout(top)

        nav = QHBoxLayout()
        nav.setSpacing(6)
        self._nav_buttons: list[QPushButton] = []
        for index, title in enumerate(("Colour", "Modes", "Mic", "Music", "Schedule", "Settings")):
            button = QPushButton(title)
            button.setCheckable(True)
            button.setObjectName("navButton")
            button.clicked.connect(lambda _checked=False, i=index: self._show_page(i))
            nav.addWidget(button)
            self._nav_buttons.append(button)
        nav.addStretch(1)
        self._nav_buttons[0].setChecked(True)
        right_layout.addLayout(nav)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_color_page())
        self.stack.addWidget(self._build_mode_page())
        self.stack.addWidget(self._build_mic_page())
        self.stack.addWidget(self._build_music_page())
        self.stack.addWidget(self._build_schedule_page())
        self.stack.addWidget(self._build_settings_page())
        right_layout.addWidget(self.stack, 1)

        self.status_label = QLabel("Ready. Press Scan to find lights.")
        self.status_label.setObjectName("muted")
        right_layout.addWidget(self.status_label)

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(300)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(18, 20, 18, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        if ICON_PATH.exists():
            icon = QLabel()
            pixmap = QIcon(str(ICON_PATH)).pixmap(QSize(40, 40))
            icon.setPixmap(pixmap)
            header.addWidget(icon)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel("MR Star")
        title.setObjectName("brand")
        subtitle = QLabel("BLE light controller")
        subtitle.setObjectName("muted")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch(1)
        layout.addLayout(header)

        self.scan_button = QPushButton("Scan for lights")
        self.scan_button.setObjectName("primary")
        self.scan_button.clicked.connect(self._toggle_scan)
        layout.addWidget(self.scan_button)

        self.scan_status = QLabel("Not scanning")
        self.scan_status.setObjectName("muted")
        layout.addWidget(self.scan_status)

        self.auto_connect = QCheckBox("Auto-connect matching lights")
        self.auto_connect.setChecked(True)
        self.show_all = QCheckBox("Show every named BLE device")
        layout.addWidget(self.auto_connect)
        layout.addWidget(self.show_all)

        devices_label = QLabel("Devices")
        devices_label.setObjectName("sectionLabel")
        layout.addWidget(devices_label)

        self.device_list = QListWidget()
        self.device_list.setObjectName("deviceList")
        self.device_list.itemSelectionChanged.connect(self._update_device_buttons)
        layout.addWidget(self.device_list, 1)

        self.device_hint = QLabel("No lights discovered yet.")
        self.device_hint.setObjectName("muted")
        self.device_hint.setWordWrap(True)
        layout.addWidget(self.device_hint)

        buttons = QHBoxLayout()
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self._connect_selected)
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.clicked.connect(self._disconnect_selected)
        buttons.addWidget(self.connect_button)
        buttons.addWidget(self.disconnect_button)
        layout.addLayout(buttons)

        settings_button = QPushButton("Device settings")
        settings_button.clicked.connect(lambda: self._show_page(5))
        layout.addWidget(settings_button)

        footer = QLabel(f"Desktop {__version__}  •  APK v1.0.0")
        footer.setObjectName("footer")
        layout.addWidget(footer)
        return sidebar

    def _card(self, title: str | None = None) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        if title:
            label = QLabel(title)
            label.setObjectName("cardTitle")
            layout.addWidget(label)
        return frame, layout

    def _build_color_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        wheel_card, wheel_layout = self._card("Colour wheel")
        wheel_card.setFixedWidth(360)
        self.color_wheel = ColorWheel()
        wheel_layout.addWidget(self.color_wheel, 1)
        preview_row = QHBoxLayout()
        self.color_swatch = QLabel()
        self.color_swatch.setFixedSize(44, 44)
        self.color_swatch.setObjectName("swatch")
        self.color_hex = QLabel("#FF0000")
        self.color_hex.setObjectName("mono")
        self.color_rgb = QLabel("255, 0, 0")
        self.color_rgb.setObjectName("muted")
        preview_row.addWidget(self.color_swatch)
        preview_row.addWidget(self.color_hex)
        preview_row.addStretch(1)
        preview_row.addWidget(self.color_rgb)
        wheel_layout.addLayout(preview_row)
        note = QLabel("Hue and saturation are sent to the strip; brightness is separate.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        wheel_layout.addWidget(note)
        layout.addWidget(wheel_card)

        right = QVBoxLayout()
        right.setSpacing(16)

        power_card, power_layout = self._card("Power & brightness")
        self.power_check = QCheckBox("Power")
        self.power_check.setChecked(True)
        power_layout.addWidget(self.power_check)
        self.brightness_slider = LabeledSlider(
            "Brightness", protocol.MIN_BRIGHTNESS, protocol.MAX_BRIGHTNESS, 1000
        )
        power_layout.addWidget(self.brightness_slider)
        brightness_hint = QLabel("The APK clamps brightness to 3…1000.")
        brightness_hint.setObjectName("muted")
        power_layout.addWidget(brightness_hint)
        right.addWidget(power_card)

        preset_card, preset_layout = self._card("Colour presets")
        custom_label = QLabel("Custom slots  ·  right-click a slot to save the wheel colour")
        custom_label.setObjectName("muted")
        preset_layout.addWidget(custom_label)
        custom_grid = QGridLayout()
        custom_grid.setSpacing(8)
        self._custom_buttons: list[ColorButton] = []
        for index, color in enumerate(self._custom_colors):
            button = ColorButton(color, savable=True)
            button.clicked.connect(lambda _checked=False, i=index: self._apply_custom(i))
            button.setContextMenuPolicy(Qt.CustomContextMenu)
            button.customContextMenuRequested.connect(
                lambda _pos, i=index: self._save_custom(i)
            )
            custom_grid.addWidget(button, 0, index)
            self._custom_buttons.append(button)
        preset_layout.addLayout(custom_grid)

        fixed_label = QLabel("Fixed palette")
        fixed_label.setObjectName("muted")
        preset_layout.addWidget(fixed_label)
        fixed_grid = QGridLayout()
        fixed_grid.setSpacing(8)
        for index, color in enumerate(FIXED_COLORS):
            button = ColorButton(QColor(*color))
            button.clicked.connect(
                lambda _checked=False, c=color: self._send_rgb(*c)
            )
            fixed_grid.addWidget(button, 0, index)
        preset_layout.addLayout(fixed_grid)
        preset_layout.addStretch(1)
        right.addWidget(preset_card, 1)

        layout.addLayout(right, 1)
        return page

    def _build_mode_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        category_card, category_layout = self._card("Categories")
        category_card.setFixedWidth(280)
        self.category_list = QListWidget()
        for category in CATEGORIES:
            label = category.name + ("  (not in APK UI)" if category.hidden else "")
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, category.name)
            self.category_list.addItem(item)
        category_layout.addWidget(self.category_list, 1)
        category_note = QLabel(
            "Flow (63…75) exists in the APK resources but the shipped tab strip never exposes it."
        )
        category_note.setObjectName("muted")
        category_note.setWordWrap(True)
        category_layout.addWidget(category_note)
        layout.addWidget(category_card)

        mode_card, mode_layout = self._card("Animations")
        self.mode_list = QListWidget()
        mode_layout.addWidget(self.mode_list, 1)
        self.mode_id_label = QLabel("Mode id: —")
        self.mode_id_label.setObjectName("muted")
        mode_layout.addWidget(self.mode_id_label)

        self.speed_slider = LabeledSlider("Speed", 0, 100, 50)
        self.mode_brightness_slider = LabeledSlider(
            "Brightness", protocol.MIN_BRIGHTNESS, protocol.MAX_BRIGHTNESS, 1000
        )
        mode_layout.addWidget(self.speed_slider)
        mode_layout.addWidget(self.mode_brightness_slider)
        self.direction_check = QCheckBox("Reverse direction")
        mode_layout.addWidget(self.direction_check)
        layout.addWidget(mode_card, 1)
        return page

    def _build_mic_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        device_card, device_layout = self._card("Microphone source")
        device_card.setFixedWidth(340)
        self.mic_source = QComboBox()
        self.mic_source.addItem("Light's own microphone", True)
        self.mic_source.addItem("This computer's microphone", False)
        device_layout.addWidget(self.mic_source)

        effect_label = QLabel("Effect")
        effect_label.setObjectName("muted")
        device_layout.addWidget(effect_label)
        self.mic_effect = QComboBox()
        for value, label in protocol.MIC_EFFECTS.items():
            self.mic_effect.addItem(label, value)
        device_layout.addWidget(self.mic_effect)

        self.gain_slider = LabeledSlider("Sensitivity", 0, 100, 100)
        device_layout.addWidget(self.gain_slider)
        device_hint = QLabel(
            "Device mode programs the strip's built-in microphone. The APK labels the "
            "four effects Energy, Rhythm, Spectrum and Scroll."
        )
        device_hint.setObjectName("muted")
        device_hint.setWordWrap(True)
        device_layout.addWidget(device_hint)
        device_layout.addStretch(1)
        layout.addWidget(device_card)

        pc_card, pc_layout = self._card("Computer microphone")
        input_row = QHBoxLayout()
        self.input_combo = QComboBox()
        self.input_combo.addItem("Default input", None)
        refresh_inputs = QPushButton("Refresh")
        refresh_inputs.clicked.connect(self._populate_inputs)
        input_row.addWidget(self.input_combo, 1)
        input_row.addWidget(refresh_inputs)
        pc_layout.addLayout(input_row)
        self.mic_toggle = QPushButton("Start listening")
        self.mic_toggle.setObjectName("primary")
        self.mic_toggle.clicked.connect(self._toggle_pc_mic)
        pc_layout.addWidget(self.mic_toggle)
        self.mic_level = LevelMeter()
        pc_layout.addWidget(self.mic_level)
        self.mic_spectrum = SpectrumView()
        pc_layout.addWidget(self.mic_spectrum)
        live_row = QHBoxLayout()
        self.mic_preview = QLabel()
        self.mic_preview.setFixedSize(44, 44)
        self.mic_preview.setObjectName("swatch")
        self.mic_color_label = QLabel("Audio-reactive colour")
        self.mic_color_label.setObjectName("muted")
        live_row.addWidget(self.mic_preview)
        live_row.addWidget(self.mic_color_label)
        live_row.addStretch(1)
        pc_layout.addLayout(live_row)
        pc_hint = QLabel(
            "PC mode sends 0x09 colour frames about five times per second, matching "
            "VoiceUtils in the APK. The strip's own mic is disabled while listening."
        )
        pc_hint.setObjectName("muted")
        pc_hint.setWordWrap(True)
        pc_layout.addWidget(pc_hint)
        pc_layout.addStretch(1)
        layout.addWidget(pc_card, 1)
        return page

    def _build_music_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        list_card, list_layout = self._card("Playlist")
        list_card.setFixedWidth(340)
        self.playlist = QListWidget()
        self.playlist.itemDoubleClicked.connect(self._play_selected)
        list_layout.addWidget(self.playlist, 1)
        list_buttons = QHBoxLayout()
        add_button = QPushButton("Add files…")
        add_button.clicked.connect(self._add_files)
        remove_button = QPushButton("Remove")
        remove_button.clicked.connect(self._remove_track)
        list_buttons.addWidget(add_button)
        list_buttons.addWidget(remove_button)
        list_layout.addLayout(list_buttons)
        list_hint = QLabel("Double-click a track to play it. Audio is decoded with ffmpeg.")
        list_hint.setObjectName("muted")
        list_hint.setWordWrap(True)
        list_layout.addWidget(list_hint)
        layout.addWidget(list_card)

        player_card, player_layout = self._card("Player")
        self.now_playing = QLabel("Nothing playing")
        self.now_playing.setObjectName("cardTitle")
        player_layout.addWidget(self.now_playing)
        transport = QHBoxLayout()
        self.prev_button = QPushButton("⏮")
        self.play_button = QPushButton("▶  Play")
        self.play_button.setObjectName("primary")
        self.stop_button = QPushButton("⏹")
        self.next_button = QPushButton("⏭")
        self.prev_button.clicked.connect(lambda: self._step_track(-1))
        self.play_button.clicked.connect(self._toggle_play)
        self.stop_button.clicked.connect(self._stop_playback)
        self.next_button.clicked.connect(lambda: self._step_track(1))
        transport.addWidget(self.prev_button)
        transport.addWidget(self.play_button)
        transport.addWidget(self.stop_button)
        transport.addWidget(self.next_button)
        transport.addStretch(1)
        player_layout.addLayout(transport)
        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.sliderPressed.connect(self._seek_pressed)
        self.seek_slider.sliderReleased.connect(self._seek_released)
        player_layout.addWidget(self.seek_slider)
        time_row = QHBoxLayout()
        self.position_label = QLabel("0:00")
        self.duration_label = QLabel("0:00")
        self.position_label.setObjectName("mono")
        self.duration_label.setObjectName("mono")
        time_row.addWidget(self.position_label)
        time_row.addStretch(1)
        time_row.addWidget(self.duration_label)
        player_layout.addLayout(time_row)
        self.volume_slider = LabeledSlider("Volume", 0, 100, 80, "%")
        player_layout.addWidget(self.volume_slider)
        self.music_send = QCheckBox("Send audio-reactive colours to the light")
        self.music_send.setChecked(True)
        player_layout.addWidget(self.music_send)
        self.music_spectrum = SpectrumView()
        player_layout.addWidget(self.music_spectrum)
        self.music_level = LevelMeter()
        player_layout.addWidget(self.music_level)
        music_hint = QLabel(
            "The APK uses Visualizer FFT data to pick a hue and sends 0x04 frames. "
            "This port uses the same idea on the decoded file."
        )
        music_hint.setObjectName("muted")
        music_hint.setWordWrap(True)
        player_layout.addWidget(music_hint)
        player_layout.addStretch(1)
        layout.addWidget(player_card, 1)
        return page

    def _build_schedule_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(16)

        cards = QHBoxLayout()
        cards.setSpacing(16)
        self._schedule_widgets = {}
        for slot, title in (("on", "Schedule On"), ("off", "Schedule Off")):
            card, layout = self._card(title)
            enabled = QCheckBox("Enabled")
            time_edit = QTimeEdit()
            time_edit.setDisplayFormat("HH:mm")
            time_edit.setTime(QTime(0, 0))
            weekdays = WeekdaySelector()
            layout.addWidget(enabled)
            layout.addWidget(time_edit)
            layout.addWidget(weekdays)
            layout.addStretch(1)
            self._schedule_widgets[slot] = {
                "enabled": enabled,
                "time": time_edit,
                "weekdays": weekdays,
            }
            cards.addWidget(card, 1)
        outer.addLayout(cards)

        actions_card, actions = self._card("Device clock")
        row = QHBoxLayout()
        send_button = QPushButton("Send schedule")
        send_button.setObjectName("primary")
        send_button.clicked.connect(self._send_schedule)
        read_button = QPushButton("Read from device")
        read_button.clicked.connect(self._read_schedule)
        sync_button = QPushButton("Sync computer time")
        sync_button.clicked.connect(self._sync_time)
        row.addWidget(send_button)
        row.addWidget(read_button)
        row.addWidget(sync_button)
        row.addStretch(1)
        actions.addLayout(row)
        self.schedule_status = QLabel(
            "The light reports schedules over 0xFFF4 (command 0x0D). Clock sync is "
            "reproduced exactly, including the APK's terminator-before-weekday quirk."
        )
        self.schedule_status.setObjectName("muted")
        self.schedule_status.setWordWrap(True)
        actions.addWidget(self.schedule_status)
        outer.addWidget(actions_card)
        outer.addStretch(1)
        return page

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(16)
        wiring_card, wiring = self._card("Strip wiring")
        wiring.addWidget(QLabel("Colour order"))
        self.order_combo = QComboBox()
        self.order_combo.addItems(protocol.COLOR_ORDERS)
        wiring.addWidget(self.order_combo)
        pixel_row = QHBoxLayout()
        pixel_row.addWidget(QLabel("Pixels"))
        self.pixel_spin = QSpinBox()
        self.pixel_spin.setRange(protocol.MIN_PIXELS, protocol.MAX_PIXELS)
        self.pixel_spin.setValue(60)
        pixel_row.addWidget(self.pixel_spin)
        apply_pixels = QPushButton("Apply")
        apply_pixels.clicked.connect(self._apply_pixels)
        pixel_row.addWidget(apply_pixels)
        pixel_row.addStretch(1)
        wiring.addLayout(pixel_row)
        wiring_hint = QLabel(
            "Colour order (0x02) and pixel count (0x03) are global device settings. "
            "The APK accepts 8…300 pixels."
        )
        wiring_hint.setObjectName("muted")
        wiring_hint.setWordWrap(True)
        wiring.addWidget(wiring_hint)
        left.addWidget(wiring_card)

        clock_card, clock = self._card("Clock")
        sync_button = QPushButton("Send computer time")
        sync_button.clicked.connect(self._sync_time)
        clock.addWidget(sync_button)
        self.sync_status = QLabel("Not sent yet")
        self.sync_status.setObjectName("muted")
        clock.addWidget(self.sync_status)
        left.addWidget(clock_card)

        left.addStretch(1)
        layout.addLayout(left, 1)

        console_card, console = self._card("Protocol console")
        raw_row = QHBoxLayout()
        self.raw_input = QLineEdit()
        self.raw_input.setPlaceholderText("BC 05 06 03 E8 00 00 00 00 55")
        send_raw = QPushButton("Send")
        send_raw.clicked.connect(self._send_raw)
        raw_row.addWidget(self.raw_input, 1)
        raw_row.addWidget(send_raw)
        console.addLayout(raw_row)
        console_hint = QLabel(
            "Frames are sent verbatim to all connected lights. TX/RX traffic is logged below."
        )
        console_hint.setObjectName("muted")
        console_hint.setWordWrap(True)
        console.addWidget(console_hint)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setObjectName("log")
        self.log_view.setMaximumBlockCount(1000)
        console.addWidget(self.log_view, 1)
        layout.addWidget(console_card, 2)
        return page

    # ------------------------------------------------------------------ wiring
    def _connect_signals(self) -> None:
        self.bridge.state.connect(self._on_ble_state)
        self.bridge.notification.connect(self._on_notification)
        self.bridge.log.connect(self._append_log)

        self.color_wheel.picked.connect(self._on_wheel_picked)
        self.power_check.toggled.connect(
            lambda checked: self.ble.send(protocol.power(checked))
        )
        self.brightness_slider.released.connect(self._on_brightness_released)
        self.mode_brightness_slider.released.connect(self._on_brightness_released)
        self.speed_slider.released.connect(
            lambda value: self.ble.send(protocol.speed(value))
        )
        self.direction_check.toggled.connect(
            lambda reversed_: self.ble.send(protocol.direction(not reversed_))
        )
        self.category_list.currentRowChanged.connect(self._on_category_changed)
        self.mode_list.itemClicked.connect(self._on_mode_clicked)

        self.auto_connect.toggled.connect(self._on_auto_connect)
        self.show_all.toggled.connect(self._on_show_all)

        self.mic_source.currentIndexChanged.connect(self._on_mic_source)
        self.mic_effect.currentIndexChanged.connect(self._on_mic_effect)
        self.gain_slider.released.connect(self._on_gain_released)

        self.playlist.currentRowChanged.connect(self._on_playlist_row)
        self.volume_slider.changed.connect(
            lambda value: setattr(self.player, "volume", value / 100.0)
        )
        self.order_combo.currentIndexChanged.connect(self._on_color_order)
        self.pixel_spin.valueChanged.connect(self._on_pixel_value)

        for slot in ("on", "off"):
            widgets = self._schedule_widgets[slot]
            widgets["enabled"].toggled.connect(lambda _c, s=slot: self._send_schedule_slot(s))
            widgets["time"].timeChanged.connect(lambda _t, s=slot: self._send_schedule_slot(s))
            widgets["weekdays"].changed.connect(lambda s=slot: self._send_schedule_slot(s))

    def _start_timers(self) -> None:
        self._device_timer = QTimer(self)
        self._device_timer.setInterval(500)
        self._device_timer.timeout.connect(self._refresh_devices)
        self._device_timer.start()

        self._live_timer = QTimer(self)
        self._live_timer.setInterval(100)
        self._live_timer.timeout.connect(self._tick_audio)
        self._live_timer.start()

    def _show_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.page_title.setText(self.PAGE_TITLES[index])
        for position, button in enumerate(self._nav_buttons):
            button.setChecked(position == index)
        if index == 2 and not self._inputs_loaded:
            self._populate_inputs()
        if index == 4:
            self._read_schedule()

    # ------------------------------------------------------------------ settings
    def _load_settings(self) -> None:
        brightness = int(self.settings.value("brightness", 1000))
        self.brightness_slider.set_value(brightness)
        self.mode_brightness_slider.set_value(brightness)
        speed = int(self.settings.value("speed", 50))
        self.speed_slider.set_value(speed)
        gain = int(self.settings.value("gain", 100))
        self.gain_slider.set_value(gain)
        self.direction_check.setChecked(bool(self.settings.value("reverse", False, bool)))
        self.order_combo.setCurrentIndex(int(self.settings.value("color_order", 0)))
        self._pixels = int(self.settings.value("pixels", 60))
        self.pixel_spin.setValue(self._pixels)
        self.music_send.setChecked(bool(self.settings.value("music_send", True, bool)))
        self.volume_slider.set_value(int(self.settings.value("volume", 80)))
        self.auto_connect.setChecked(bool(self.settings.value("auto_connect", True, bool)))
        self.show_all.setChecked(bool(self.settings.value("show_all", False, bool)))
        self.power_check.setChecked(bool(self.settings.value("power", True, bool)))

        colors = self.settings.value("custom_colors", "")
        if colors:
            try:
                parsed = json.loads(colors)
                for index, value in enumerate(parsed[:7]):
                    self._custom_colors[index] = QColor(value)
            except (ValueError, TypeError):
                pass
        for button, color in zip(self._custom_buttons, self._custom_colors):
            button.set_color(color)

        stored_modes = self.settings.value("mode_selection", "")
        if stored_modes:
            try:
                self._mode_selection = {
                    str(key): int(value) for key, value in json.loads(stored_modes).items()
                }
            except (ValueError, TypeError):
                self._mode_selection = {}

        category_name = str(self.settings.value("mode_category", "Basic"))
        category_row = 0
        for row in range(self.category_list.count()):
            if self.category_list.item(row).data(Qt.UserRole) == category_name:
                category_row = row
                break
        self.category_list.setCurrentRow(category_row)
        self._populate_modes(category_name, send=False)

        self.mic_effect.setCurrentIndex(int(self.settings.value("mic_effect", 1)) - 1)
        self.mic_source.setCurrentIndex(int(self.settings.value("mic_source", 0)))

        for slot in ("on", "off"):
            enabled = bool(self.settings.value(f"{slot}_enabled", False, bool))
            mask = int(self.settings.value(f"{slot}_weekdays", 0))
            time_value = str(self.settings.value(f"{slot}_time", "00:00"))
            widgets = self._schedule_widgets[slot]
            widgets["enabled"].setChecked(enabled)
            widgets["weekdays"].set_mask(mask)
            hour, _, minute = time_value.partition(":")
            widgets["time"].setTime(QTime(int(hour or 0), int(minute or 0)))

    def _save_settings(self) -> None:
        self.settings.setValue("brightness", self.brightness_slider.value())
        self.settings.setValue("speed", self.speed_slider.value())
        self.settings.setValue("gain", self.gain_slider.value())
        self.settings.setValue("reverse", self.direction_check.isChecked())
        self.settings.setValue("color_order", self.order_combo.currentIndex())
        self.settings.setValue("pixels", self._pixels)
        self.settings.setValue("music_send", self.music_send.isChecked())
        self.settings.setValue("volume", self.volume_slider.value())
        self.settings.setValue("auto_connect", self.auto_connect.isChecked())
        self.settings.setValue("show_all", self.show_all.isChecked())
        self.settings.setValue("power", self.power_check.isChecked())
        self.settings.setValue(
            "custom_colors", json.dumps([color.name() for color in self._custom_colors])
        )
        self.settings.setValue("mode_selection", json.dumps(self._mode_selection))
        current_category = self.category_list.currentItem()
        if current_category:
            self.settings.setValue("mode_category", current_category.data(Qt.UserRole))
        self.settings.setValue("mic_effect", self.mic_effect.currentData() or 1)
        self.settings.setValue("mic_source", self.mic_source.currentIndex())
        for slot in ("on", "off"):
            widgets = self._schedule_widgets[slot]
            self.settings.setValue(f"{slot}_enabled", widgets["enabled"].isChecked())
            self.settings.setValue(f"{slot}_weekdays", widgets["weekdays"].mask())
            self.settings.setValue(f"{slot}_time", widgets["time"].time().toString("HH:mm"))
        self.settings.sync()

    # ------------------------------------------------------------------ page logic
    def _on_wheel_picked(self, red: int, green: int, blue: int) -> None:
        self._set_preview(red, green, blue)
        self._pending_color = protocol.color_rgb(red, green, blue)
        if not self._color_timer.isActive():
            self._color_timer.start()

    def _flush_color(self) -> None:
        if self._pending_color is None:
            return
        self.ble.send(self._pending_color, coalesce="color")
        self._pending_color = None

    def _set_preview(self, red: int, green: int, blue: int) -> None:
        self.color_swatch.setStyleSheet(
            f"background:{QColor(red, green, blue).name()}; border-radius:10px;"
        )
        self.color_hex.setText(QColor(red, green, blue).name().upper())
        self.color_rgb.setText(f"{red}, {green}, {blue}")

    def _send_rgb(self, red: int, green: int, blue: int) -> None:
        self.color_wheel.set_rgb(red, green, blue)
        self._set_preview(red, green, blue)
        self.ble.send(protocol.color_rgb(red, green, blue), coalesce="color")

    def _apply_custom(self, index: int) -> None:
        self._selected_slot = index
        color = self._custom_colors[index]
        self._send_rgb(color.red(), color.green(), color.blue())

    def _save_custom(self, index: int) -> None:
        red, green, blue = self.color_wheel.rgb()
        self._custom_colors[index] = QColor(red, green, blue)
        self._custom_buttons[index].set_color(self._custom_colors[index])
        self._append_log(f"Saved {QColor(red, green, blue).name().upper()} to slot {index + 1}")

    def _on_brightness_released(self, value: int) -> None:
        value = max(protocol.MIN_BRIGHTNESS, value)
        self.brightness_slider.set_value(value)
        self.mode_brightness_slider.set_value(value)
        self.ble.send(protocol.brightness(value), coalesce="brightness")

    def _on_category_changed(self, row: int) -> None:
        item = self.category_list.item(row)
        if item is None:
            return
        self._populate_modes(item.data(Qt.UserRole), send=not self._initializing)

    def _populate_modes(self, category_name: str, send: bool) -> None:
        category = CATEGORY_BY_NAME.get(category_name)
        if category is None:
            return
        self.mode_list.clear()
        selected_id = self._mode_selection.get(category_name, category.modes[0][0])
        selected_row = 0
        for row, (ident, label) in enumerate(category.modes):
            item = QListWidgetItem(f"{label}   [{ident}]")
            item.setData(Qt.UserRole, ident)
            self.mode_list.addItem(item)
            if ident == selected_id:
                selected_row = row
        self.mode_list.setCurrentRow(selected_row)
        self.mode_id_label.setText(f"Mode id: {selected_id}")
        if send:
            self.ble.send(protocol.mode(selected_id), coalesce="mode")

    def _on_mode_clicked(self, item: QListWidgetItem) -> None:
        ident = int(item.data(Qt.UserRole))
        category = self.category_list.currentItem()
        if category:
            self._mode_selection[category.data(Qt.UserRole)] = ident
        self.mode_id_label.setText(f"Mode id: {ident}")
        self.ble.send(protocol.mode(ident), coalesce="mode")

    # ------------------------------------------------------------------ microphone
    def _populate_inputs(self) -> None:
        current = self.input_combo.currentData()
        self.input_combo.clear()
        try:
            devices = MicAnalyzer.input_devices()
        except Exception as exc:
            self._append_log(f"Could not list audio inputs: {exc}")
            devices = []
        for index, name in devices:
            self.input_combo.addItem(name, index)
        if not devices:
            self.input_combo.addItem("No input devices", -1)
        elif current not in (None, -1):
            selected = self.input_combo.findData(current)
            if selected >= 0:
                self.input_combo.setCurrentIndex(selected)
        self._inputs_loaded = True

    def _on_mic_source(self, index: int) -> None:
        device_mode = bool(self.mic_source.itemData(index))
        if device_mode:
            if self._pc_mic:
                self._stop_pc_mic()
            self.ble.send(protocol.mic_source(True))
        else:
            self.ble.send(protocol.mic_source(False))

    def _on_mic_effect(self, _index: int) -> None:
        effect = self.mic_effect.currentData()
        if effect:
            self.ble.send(protocol.mic_effect(int(effect)))

    def _on_gain_released(self, value: int) -> None:
        self.ble.send(protocol.mic_gain(value), coalesce="gain")

    def _toggle_pc_mic(self) -> None:
        if self._pc_mic:
            self._stop_pc_mic()
        else:
            self._start_pc_mic()

    def _start_pc_mic(self) -> None:
        device = self.input_combo.currentData()
        device_index = None if device in (None, -1) else int(device)
        try:
            self.mic.start(device_index)
        except Exception as exc:
            QMessageBox.warning(self, "Microphone", f"Could not open the input device:\n{exc}")
            return
        self._pc_mic = True
        self.mic_toggle.setText("Stop listening")
        self._select_mic_source(device=False)
        self.ble.send(protocol.mic_source(False))
        self._append_log("PC microphone started")

    def _stop_pc_mic(self) -> None:
        self.mic.stop()
        if self._pc_mic:
            self._select_mic_source(device=True)
            self.ble.send(protocol.mic_source(True))
        self._pc_mic = False
        self.mic_toggle.setText("Start listening")
        self.mic_level.set_level(0.0)
        self.mic_spectrum.set_bars(np.zeros(BAND_COUNT))
        self.mic_preview.setStyleSheet("")
        self._append_log("PC microphone stopped")

    def _select_mic_source(self, device: bool) -> None:
        index = self.mic_source.findData(device)
        if index < 0 or index == self.mic_source.currentIndex():
            return
        self.mic_source.blockSignals(True)
        self.mic_source.setCurrentIndex(index)
        self.mic_source.blockSignals(False)

    # ------------------------------------------------------------------ music
    def _add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Add audio files",
            "",
            "Audio (*.mp3 *.m4a *.aac *.flac *.wav *.ogg *.opus);;All files (*)",
        )
        for path in files:
            if path and path not in self._playlist:
                self._playlist.append(path)
                item = QListWidgetItem(Path(path).name)
                item.setToolTip(path)
                self.playlist.addItem(item)
        if files and self.playlist.currentRow() < 0:
            self.playlist.setCurrentRow(0)

    def _remove_track(self) -> None:
        row = self.playlist.currentRow()
        if row < 0:
            return
        self.playlist.takeItem(row)
        del self._playlist[row]
        if row == self._play_index:
            self.player.stop()
            self._play_index = -1
            self.now_playing.setText("Nothing playing")
            self.play_button.setText("▶  Play")
            self.seek_slider.setValue(0)
            self.position_label.setText("0:00")
            if self._playlist:
                self.playlist.setCurrentRow(min(row, len(self._playlist) - 1))
        elif row < self._play_index:
            self._play_index -= 1

    def _on_playlist_row(self, row: int) -> None:
        if 0 <= row < len(self._playlist):
            self._append_log(f"Selected {Path(self._playlist[row]).name}")

    def _play_selected(self, _item=None) -> None:
        row = self.playlist.currentRow()
        if row < 0:
            return
        self._load_and_play(row)

    def _load_and_play(self, row: int) -> None:
        if not (0 <= row < len(self._playlist)):
            return
        path = self._playlist[row]
        try:
            if self.player.path != path:
                duration = self.player.load(path)
                self.seek_slider.setRange(0, max(1, int(duration)))
                self.duration_label.setText(self._format_time(duration))
            self.player.play()
            self._play_index = row
            self.playlist.setCurrentRow(row)
            self.now_playing.setText(Path(path).name)
            self.play_button.setText("⏸  Pause")
        except Exception as exc:
            QMessageBox.warning(self, "Playback", f"Could not play this file:\n{exc}")

    def _toggle_play(self) -> None:
        if self.player.playing:
            self.player.pause()
            self.play_button.setText("▶  Play")
            return
        row = self.playlist.currentRow()
        if row < 0:
            if self._playlist:
                row = 0
            else:
                return
        if self.player.path != self._playlist[row]:
            self._load_and_play(row)
        else:
            self.player.play()
            self.play_button.setText("⏸  Pause")

    def _stop_playback(self) -> None:
        self.player.stop()
        self.play_button.setText("▶  Play")
        self.seek_slider.setValue(0)
        self.position_label.setText("0:00")

    def _step_track(self, delta: int) -> None:
        if not self._playlist:
            return
        row = self._play_index
        if row < 0:
            row = self.playlist.currentRow()
        if row < 0:
            row = 0 if delta > 0 else len(self._playlist) - 1
        else:
            row = (row + delta) % len(self._playlist)
        self._load_and_play(row)

    def _seek_pressed(self) -> None:
        self._seek_dragging = True

    def _seek_released(self) -> None:
        self._seek_dragging = False
        self.player.seek(float(self.seek_slider.value()))

    @staticmethod
    def _format_time(seconds: float) -> str:
        seconds = max(0, int(seconds))
        return f"{seconds // 60}:{seconds % 60:02d}"

    # ------------------------------------------------------------------ schedule
    def _send_schedule(self) -> None:
        for slot in ("on", "off"):
            self._send_schedule_slot(slot)

    def _send_schedule_slot(self, slot: str) -> None:
        if self._initializing or self._applying_notification:
            return
        widgets = self._schedule_widgets[slot]
        time_value = widgets["time"].time()
        frame = protocol.set_timer(
            slot,
            widgets["enabled"].isChecked(),
            widgets["weekdays"].weekdays(),
            time_value.hour(),
            time_value.minute(),
        )
        self.ble.send(frame, coalesce=f"timer_{slot}")

    def _read_schedule(self) -> None:
        self.ble.send(protocol.sync_time(), coalesce="clock")
        self.ble.send(protocol.request_timer())

    def _sync_time(self) -> None:
        self.ble.send(protocol.sync_time(), coalesce="clock")
        self.sync_status.setText("Computer time sent")
        self._append_log("Clock sync sent")

    # ------------------------------------------------------------------ settings actions
    def _on_color_order(self, index: int) -> None:
        if self._initializing:
            return
        self.ble.send(protocol.color_order(index + 1))

    def _on_pixel_value(self, value: int) -> None:
        self._pixels = value

    def _apply_pixels(self) -> None:
        self._pixels = self.pixel_spin.value()
        self.ble.send(protocol.pixel_count(self._pixels))

    def _send_raw(self) -> None:
        text = self.raw_input.text().strip()
        if not text:
            return
        try:
            frame = bytes.fromhex(text.replace(",", " ").replace("0x", ""))
        except ValueError:
            QMessageBox.warning(self, "Protocol console", "Invalid hex string.")
            return
        self.ble.send(frame)
        self.raw_input.clear()

    # ------------------------------------------------------------------ BLE events
    def _on_ble_state(self) -> None:
        self._refresh_status()
        self._update_device_buttons()

    def _on_notification(self, notification: protocol.Notification) -> None:
        if notification.kind == "brightness":
            self.brightness_slider.set_value(int(notification.value))
            self.mode_brightness_slider.set_value(int(notification.value))
        elif notification.kind == "speed":
            self.speed_slider.set_value(int(notification.value))
        elif notification.kind == "mic_gain":
            self.gain_slider.set_value(int(notification.value))
        elif notification.kind == "timer":
            value = notification.value
            widgets = self._schedule_widgets.get(value["slot"])
            if widgets:
                self._applying_notification = True
                try:
                    widgets["enabled"].setChecked(bool(value["enabled"]))
                    widgets["weekdays"].set_mask(
                        sum(1 << bit for bit, on in enumerate(value["weekdays"]) if on)
                    )
                    widgets["time"].setTime(QTime(int(value["hour"]), int(value["minute"])))
                finally:
                    self._applying_notification = False
                self.schedule_status.setText(
                    f"Device {value['slot']} schedule: "
                    f"{'enabled' if value['enabled'] else 'disabled'}, "
                    f"{value['hour']:02d}:{value['minute']:02d}"
                )

    def _append_log(self, message: str) -> None:
        log_view = getattr(self, "log_view", None)
        if log_view is None:
            # The mic page probes audio devices while the UI is still being
            # built, before the protocol console exists.
            return
        timestamp = time.strftime("%H:%M:%S")
        log_view.appendPlainText(f"[{timestamp}] {message}")

    def _on_auto_connect(self, checked: bool) -> None:
        self.ble.auto_connect = checked

    def _on_show_all(self, checked: bool) -> None:
        self.ble.show_all = checked

    def _refresh_status(self) -> None:
        addresses = self.ble.connected_addresses()
        self._connected_count = len(addresses)
        if self._connected_count:
            self.status_pill.setText(f"Connected · {self._connected_count}")
            self.status_pill.setProperty("status", "ok")
            self.status_label.setText(
                f"{self._connected_count} light(s) connected. Commands are broadcast to all."
            )
        elif self.ble.scanning:
            self.status_pill.setText("Scanning…")
            self.status_pill.setProperty("status", "scan")
            self.status_label.setText("Scanning for advertisements with company id 0x2022…")
        else:
            self.status_pill.setText("Disconnected")
            self.status_pill.setProperty("status", "off")
            self.status_label.setText("No light connected. Press Scan to look for one.")
        self.status_pill.style().unpolish(self.status_pill)
        self.status_pill.style().polish(self.status_pill)

    def _refresh_devices(self) -> None:
        records: list[DeviceRecord] = self.ble.devices()
        signature = tuple((r.address, r.status, r.name) for r in records)
        if signature != self._device_signature:
            selected = self._selected_address()
            self._device_signature = signature
            self.device_list.blockSignals(True)
            self.device_list.clear()
            self._device_items.clear()
            for record in records:
                item = QListWidgetItem(self._device_text(record))
                item.setData(Qt.UserRole, record.address)
                color = {
                    "connected": QColor("#37d67a"),
                    "connecting": QColor("#ffd166"),
                    "disconnected": QColor("#ff8a8a"),
                }.get(record.status, QColor("#c6d0e0"))
                item.setForeground(color)
                self.device_list.addItem(item)
                self._device_items[record.address] = item
                if record.address == selected:
                    self.device_list.setCurrentItem(item)
            self.device_list.blockSignals(False)
            self.device_hint.setText(
                "" if records else "No lights discovered yet. Press Scan."
            )
            self._update_device_buttons()
        else:
            for record in records:
                item = self._device_items.get(record.address)
                if item is not None:
                    item.setText(self._device_text(record))
        self.scan_button.setText("Stop scan" if self.ble.scanning else "Scan for lights")
        self.scan_status.setText("Scanning…" if self.ble.scanning else "Not scanning")

    @staticmethod
    def _device_text(record: DeviceRecord) -> str:
        dot = {
            "connected": "●",
            "connecting": "◌",
            "disconnected": "○",
        }.get(record.status, "·")
        name = record.name or "Unknown light"
        extra = "MR Star" if record.matched else "other BLE"
        return f"{dot}  {name}\n{record.address} · {record.rssi} dBm · {extra}"

    def _selected_address(self) -> str | None:
        item = self.device_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _update_device_buttons(self) -> None:
        address = self._selected_address()
        connected = address in self.ble.connected_addresses() if address else False
        self.connect_button.setEnabled(bool(address) and not connected)
        self.disconnect_button.setEnabled(connected)

    def _toggle_scan(self) -> None:
        if self.ble.scanning:
            self.ble.stop_scan()
        else:
            self.ble.scan()

    def _connect_selected(self) -> None:
        address = self._selected_address()
        if address:
            self.ble.connect(address)

    def _disconnect_selected(self) -> None:
        address = self._selected_address()
        if address:
            self.ble.disconnect(address)

    # ------------------------------------------------------------------ live audio
    def _tick_audio(self) -> None:
        now = time.monotonic()
        if self._pc_mic and self.mic.running:
            snapshot = self.mic.snapshot()
            peak = float(snapshot["peak"])
            self.mic_level.set_level(min(1.0, peak * 3.0))
            self.mic_spectrum.set_bars(snapshot["bands"])
            if now - self._last_mic_send >= 0.2 and peak > 0.004:
                gain = self.gain_slider.value()
                volume = peak * 32767.0 * gain / 500.0
                hue = (int(volume) % 140) * (360.0 / 140.0)
                saturation = 1.0
                red, green, blue = colorsys.hsv_to_rgb(hue / 360.0, saturation, 1.0)
                self.mic_preview.setStyleSheet(
                    f"background:{QColor(int(red * 255), int(green * 255), int(blue * 255)).name()};"
                    "border-radius:10px;"
                )
                self.ble.send(protocol.mic_color_hsv(hue, saturation), coalesce="mic")
                self._last_mic_send = now

        if self.player.duration > 0:
            position = self.player.position
            if not self._seek_dragging:
                self.seek_slider.blockSignals(True)
                self.seek_slider.setValue(int(position))
                self.seek_slider.blockSignals(False)
            self.position_label.setText(self._format_time(position))
            self.duration_label.setText(self._format_time(self.player.duration))
            if self.player.playing:
                self.play_button.setText("⏸  Pause")
            else:
                self.play_button.setText("▶  Play")
            analysis = self.player.analysis()
            self.music_level.set_level(min(1.0, analysis["level"] * 5.0))
            self.music_spectrum.set_bars(analysis["bands"])
            if (
                self.music_send.isChecked()
                and self.player.playing
                and now - self._last_music_send >= 0.2
                and analysis["level"] > 0.002
            ):
                frequency = analysis["dominant"]
                hue = (int(frequency) % 140) * (360.0 / 140.0)
                saturation = min(1.0, 0.35 + analysis["level"] * 12.0)
                self.ble.send(protocol.color_hsv(hue, saturation), coalesce="music")
                self._last_music_send = now

    # ------------------------------------------------------------------ shutdown
    def closeEvent(self, event) -> None:
        self._stop_pc_mic()
        self._save_settings()
        self._device_timer.stop()
        self._live_timer.stop()
        self.player.close()
        self.ble.shutdown()
        super().closeEvent(event)


# --------------------------------------------------------------------------- theme
STYLE = """
QWidget {
    background: #11151c;
    color: #e7edf7;
    font-family: "Inter", "Segoe UI", "SF Pro Text", "Ubuntu", "Noto Sans", sans-serif;
    font-size: 13px;
}
QMainWindow { background: #11151c; }
QFrame#sidebar {
    background: #161b24;
    border-right: 1px solid #232b3a;
}
QFrame#card {
    background: #191f2a;
    border: 1px solid #263041;
    border-radius: 12px;
}
QLabel#brand { font-size: 20px; font-weight: 700; }
QLabel#pageTitle { font-size: 22px; font-weight: 700; }
QLabel#cardTitle { font-size: 15px; font-weight: 600; }
QLabel#sectionLabel {
    color: #8b98ad;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    margin-top: 6px;
}
QLabel#muted { color: #8b98ad; }
QLabel#footer { color: #5f6c81; font-size: 11px; }
QLabel#mono { font-family: "JetBrains Mono", "DejaVu Sans Mono", monospace; }
QLabel#statusPill {
    border-radius: 10px;
    padding: 5px 12px;
    font-weight: 600;
    background: #232a38;
    color: #aab6c8;
}
QLabel#statusPill[status="ok"] { background: #143526; color: #6ee7a5; }
QLabel#statusPill[status="scan"] { background: #3a3115; color: #ffd166; }
QLabel#statusPill[status="off"] { background: #232a38; color: #aab6c8; }
QPushButton {
    background: #232a38;
    border: 1px solid #303a4d;
    border-radius: 8px;
    padding: 7px 12px;
}
QPushButton:hover { background: #2b3445; border-color: #3a475e; }
QPushButton:pressed { background: #1e2531; }
QPushButton:disabled { color: #667286; border-color: #252d3b; }
QPushButton#primary {
    background: #2f81f7;
    border-color: #2f81f7;
    color: white;
    font-weight: 600;
}
QPushButton#primary:hover { background: #3d8efc; }
QPushButton#navButton {
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    padding: 7px 10px;
    color: #8b98ad;
}
QPushButton#navButton:hover { color: #dbe5f3; }
QPushButton#navButton:checked {
    color: #e7edf7;
    border-bottom: 2px solid #2f81f7;
    font-weight: 600;
}
QListWidget {
    background: #141922;
    border: 1px solid #232b3a;
    border-radius: 8px;
    padding: 4px;
}
QListWidget::item {
    padding: 7px 8px;
    border-radius: 6px;
}
QListWidget::item:selected { background: #24344d; color: #e7edf7; }
QListWidget::item:hover { background: #1d2634; }
QLineEdit, QComboBox, QSpinBox, QTimeEdit {
    background: #121821;
    border: 1px solid #2a3445;
    border-radius: 7px;
    padding: 5px 8px;
    selection-background-color: #2f81f7;
}
QComboBox QAbstractItemView {
    background: #191f2a;
    border: 1px solid #2a3445;
    selection-background-color: #24344d;
}
QCheckBox { spacing: 8px; }
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #3a475e;
    background: #121821;
}
QCheckBox::indicator:checked { background: #2f81f7; border-color: #2f81f7; }
QSlider::groove:horizontal {
    height: 5px;
    background: #263041;
    border-radius: 2px;
}
QSlider::sub-page:horizontal { background: #2f81f7; border-radius: 2px; }
QSlider::handle:horizontal {
    background: #e7edf7;
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QToolButton#weekday {
    background: #1b2230;
    border: 1px solid #2a3445;
    border-radius: 7px;
    color: #8b98ad;
    font-weight: 600;
}
QToolButton#weekday:checked {
    background: #2f81f7;
    border-color: #2f81f7;
    color: white;
}
QPlainTextEdit#log {
    background: #0d1117;
    border: 1px solid #232b3a;
    border-radius: 8px;
    font-family: "JetBrains Mono", "DejaVu Sans Mono", monospace;
    font-size: 11px;
    color: #b8c4d6;
}
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #303a4d;
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: #3d4a61; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QToolTip {
    background: #1f2632;
    color: #e7edf7;
    border: 1px solid #303a4d;
    padding: 4px 6px;
}
"""


def create_application(argv: list[str]) -> QApplication:
    app = QApplication(argv)
    app.setApplicationName("MR Star")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("MRStar")
    app.setStyle("Fusion")
    if sys.platform.startswith("linux"):
        app.setDesktopFileName("mrstar")
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    app.setStyleSheet(STYLE)
    return app
