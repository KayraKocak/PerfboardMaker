"""
ESP8266 and ESP32 microcontroller board definitions:
- Wemos D1 Mini (ESP8266)
- NodeMCU v2 Amica (Narrow) & v3 LoLin (Wide)
- ESP-01 Module (2x4 Header)
- ESP32 DevKit (30-pin) & DevKitC (38-pin)
- ESP32-C3 SuperMini & ESP32-C6 SuperMini
"""
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QLinearGradient, QPainterPath
)
from PyQt6.QtCore import Qt, QRectF, QPointF
from app.models.component_def import ComponentDef, PinDef, PropertyDef
from app.components.draw_utils import draw_solder_joint, draw_top_pin, draw_unmirrored_text


def _infer_pin_type(name: str) -> str:
    u = name.upper()
    if u in ("GND", "G", "GND-"):
        return "ground"
    if u in ("3V3", "3.3V", "5V", "VIN", "VU", "VCC"):
        return "power"
    return "io"


class DualRowDevBoardDef(ComponentDef):
    """Shared base for dual-row WiFi/BLE dev boards with RF shield, USB port, and buttons."""

    def __init__(
        self,
        type_id: str,
        name: str,
        default_label: str,
        description: str,
        left_names: list[str],
        right_names: list[str],
        row_span: int,
        pcb_colors: tuple[QColor, QColor, QColor],
        pad_top: float = 2.4,
        pad_bottom: float = 0.8,
        pad_side: float = 0.6,
        usb_type: str = "micro",
        rf_antenna: str = "pcb",
        tags: list[str] | None = None,
    ):
        assert len(left_names) == len(right_names)
        self.left_names = left_names
        self.right_names = right_names
        self.row_count = len(left_names)
        self.row_span = row_span
        self.pcb_colors = pcb_colors
        self.pad_top = pad_top
        self.pad_bottom = pad_bottom
        self.pad_side = pad_side
        self.usb_type = usb_type
        self.rf_antenna = rf_antenna

        pins: list[PinDef] = []
        for i, pname in enumerate(left_names):
            pins.append(PinDef(name=pname, grid_x=0, grid_y=i, description=f"Left {pname}", pin_type=_infer_pin_type(pname)))
        for i, pname in enumerate(right_names):
            pins.append(PinDef(name=pname, grid_x=row_span, grid_y=i, description=f"Right {pname}", pin_type=_infer_pin_type(pname)))

        super().__init__(
            type_id=type_id,
            name=name,
            category="Microcontrollers",
            default_label=default_label,
            description=description,
            pins=pins,
            properties=[
                PropertyDef(id="label", label="Label", type="str", default=default_label),
            ],
            anchor_pin_index=0,
            tags=tags or ["esp", "wifi", "mcu"]
        )

    def _pcb_rect(self, p: float) -> QRectF:
        bx = -self.pad_side * p
        by = -self.pad_top * p
        bw = (self.row_span + 2.0 * self.pad_side) * p
        bh = ((self.row_count - 1) + self.pad_top + self.pad_bottom) * p
        return QRectF(bx, by, bw, bh)

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        p = pitch_px
        rect = self._pcb_rect(p)
        # Include slight USB overhang at bottom
        shape_rect = QRectF(rect.left(), rect.top(), rect.width(), rect.height() + 0.55 * p)
        path = QPainterPath()
        path.addRoundedRect(shape_rect, 3.5, 3.5)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        rect = self._pcb_rect(p)
        bx, by, bw, bh = rect.x(), rect.y(), rect.width(), rect.height()
        cx = bx + bw / 2.0

        # Shadow
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 48))
        painter.drawRoundedRect(rect.translated(2.0, 3.0), 3.5, 3.5)

        # PCB Substrate
        c_top, c_bot, c_edge = self.pcb_colors
        pcb_grad = QLinearGradient(bx, by, bx + bw, by + bh)
        pcb_grad.setColorAt(0.0, c_top)
        pcb_grad.setColorAt(1.0, c_bot)
        painter.setBrush(QBrush(pcb_grad))
        painter.setPen(QPen(c_edge, 1.0))
        painter.drawRoundedRect(rect, 3.5, 3.5)

        # Top antenna + RF module area
        ant_h = max(1.1 * p, (self.pad_top - 0.5) * p)
        if self.rf_antenna == "ceramic":
            # Small ceramic chip antenna + gold feed pad
            cw, ch = 1.6 * p, 0.7 * p
            painter.setBrush(QColor(235, 225, 200))
            painter.setPen(QPen(QColor(180, 165, 130), 0.8))
            painter.drawRoundedRect(QRectF(cx - cw / 2.0, by + 0.35 * p, cw, ch), 1.0, 1.0)
            shield_y = by + 1.35 * p
            shield_w = min(bw * 0.64, 4.4 * p)
            shield_h = min(bh * 0.34, 3.4 * p)
        else:
            # Meander PCB antenna trace at top edge
            ant_w = min(bw * 0.52, 4.4 * p)
            ax0 = cx - ant_w / 2.0
            ay0 = by + 0.35 * p
            ah = min(ant_h * 0.75, 1.5 * p)
            painter.setPen(QPen(QColor(215, 175, 65), max(1.4, p * 0.08)))
            ap = QPainterPath()
            ap.moveTo(ax0, ay0 + ah)
            steps = 5
            sw = ant_w / steps
            for s in range(steps):
                x1 = ax0 + s * sw
                x2 = x1 + sw
                if s % 2 == 0:
                    ap.lineTo(x1, ay0)
                    ap.lineTo(x2, ay0)
                else:
                    ap.lineTo(x1, ay0 + ah)
                    ap.lineTo(x2, ay0 + ah)
            painter.drawPath(ap)

            # Metallic ESP RF shield can below antenna
            shield_y = by + ah + 0.55 * p
            shield_w = min(bw * 0.62, 6.2 * p)
            shield_h = min(bh * 0.36, 6.0 * p)

        # Draw RF metallic shield
        sx = cx - shield_w / 2.0
        s_grad = QLinearGradient(sx, shield_y, sx + shield_w, shield_y + shield_h)
        s_grad.setColorAt(0.0, QColor(225, 230, 236))
        s_grad.setColorAt(0.5, QColor(185, 190, 200))
        s_grad.setColorAt(1.0, QColor(145, 150, 160))
        painter.setBrush(QBrush(s_grad))
        painter.setPen(QPen(QColor(95, 100, 110), 0.9))
        painter.drawRoundedRect(QRectF(sx, shield_y, shield_w, shield_h), 1.5, 1.5)

        # Label etched on shield
        label = instance.label if instance.label else self.default_label
        painter.setFont(QFont("Arial", int(max(4, min(p * 0.28, shield_w * 0.14))), QFont.Weight.Bold))
        painter.setPen(QColor(45, 50, 58))
        painter.drawText(QRectF(sx + 2, shield_y + 2, shield_w - 4, shield_h - 4),
                         Qt.AlignmentFlag.AlignCenter, label)

        # USB port at bottom edge
        usb_w = 2.6 * p if self.usb_type == "usbc" else 2.8 * p
        usb_h = 1.6 * p
        ux = cx - usb_w / 2.0
        uy = by + bh - usb_h * 0.65
        u_grad = QLinearGradient(ux, uy, ux + usb_w, uy)
        u_grad.setColorAt(0.0, QColor(175, 180, 188))
        u_grad.setColorAt(0.5, QColor(232, 236, 242))
        u_grad.setColorAt(1.0, QColor(155, 160, 168))
        painter.setBrush(QBrush(u_grad))
        painter.setPen(QPen(QColor(95, 100, 108), 0.9))
        r_usb = usb_h * 0.35 if self.usb_type == "usbc" else 1.5
        painter.drawRoundedRect(QRectF(ux, uy, usb_w, usb_h), r_usb, r_usb)

        # RST / BOOT mini tactile buttons near USB
        btn_y = by + bh - 2.35 * p
        if btn_y > shield_y + shield_h + 0.2 * p:
            for off in (-1.45 * p, 0.75 * p):
                if abs(off) < bw * 0.35:
                    painter.setBrush(QColor(210, 215, 220))
                    painter.setPen(QPen(QColor(110, 115, 120), 0.7))
                    painter.drawRoundedRect(QRectF(cx + off, btn_y, 0.85 * p, 0.65 * p), 1.0, 1.0)
                    painter.setBrush(QColor(45, 45, 50))
                    painter.drawEllipse(QPointF(cx + off + 0.425 * p, btn_y + 0.325 * p), 0.18 * p, 0.18 * p)

        # Pin header strips & silkscreen names
        header_w = 0.82 * p
        painter.setBrush(QColor(24, 24, 28))
        painter.setPen(QPen(QColor(55, 55, 62), 0.7))
        painter.drawRoundedRect(QRectF(-header_w / 2.0, -0.45 * p, header_w, (self.row_count - 0.1) * p), 1.5, 1.5)
        painter.drawRoundedRect(QRectF(self.row_span * p - header_w / 2.0, -0.45 * p, header_w, (self.row_count - 0.1) * p), 1.5, 1.5)

        lbl_font = QFont("Arial", int(max(4, p * 0.2)), QFont.Weight.Bold)
        painter.setFont(lbl_font)
        painter.setPen(QColor(235, 240, 248, 225))
        for i, pname in enumerate(self.left_names):
            painter.drawText(QRectF(0.45 * p, i * p - 0.38 * p, 2.0 * p, 0.76 * p),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, pname)
        for i, pname in enumerate(self.right_names):
            painter.drawText(QRectF((self.row_span - 2.45) * p, i * p - 0.38 * p, 2.0 * p, 0.76 * p),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, pname)

        for pin in self.pins:
            draw_top_pin(painter, pin.grid_x * p, pin.grid_y * p, 2.2)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        rect = self._pcb_rect(p)
        painter.setPen(QPen(QColor(180, 185, 200, 65), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(50, 70, 100, 22))
        painter.drawRoundedRect(rect, 3.5, 3.5)

        label = instance.label if instance.label else self.default_label
        painter.setFont(QFont("Arial", int(max(5, p * 0.32)), QFont.Weight.Bold))
        painter.setPen(QColor(200, 210, 225, 85))
        draw_unmirrored_text(painter, rect, Qt.AlignmentFlag.AlignCenter, f"[{label}]")

        for pin in self.pins:
            draw_solder_joint(painter, pin.grid_x * p, pin.grid_y * p, p)


class WemosD1MiniDef(DualRowDevBoardDef):
    def __init__(self):
        super().__init__(
            type_id="wemos_d1_mini",
            name="ESP8266 Wemos D1 Mini",
            default_label="D1 Mini",
            description="Compact ESP8266 Wemos D1 Mini WiFi board (2x8 pins, 0.9\" / 9-hole span).",
            left_names=["RST", "A0", "D0", "D5", "D6", "D7", "D8", "3V3"],
            right_names=["TX", "RX", "D1", "D2", "D3", "D4", "GND", "5V"],
            row_span=9,
            pcb_colors=(QColor(18, 95, 185), QColor(12, 65, 135), QColor(30, 125, 225)),
            pad_top=2.8,
            pad_bottom=0.8,
            pad_side=0.55,
            usb_type="micro",
            rf_antenna="pcb",
            tags=["esp8266", "wemos", "d1", "mini", "wifi", "lolin", "mcu"]
        )


class NodeMCUv2Def(DualRowDevBoardDef):
    def __init__(self):
        super().__init__(
            type_id="nodemcu_v2",
            name="ESP8266 NodeMCU v2 (Narrow)",
            default_label="NodeMCU v2",
            description="Amica NodeMCU v2 CP2102 ESP8266 dev board (30 pins, 0.9\" / 9-hole span).",
            left_names=["A0", "RSV1", "RSV2", "SD3", "SD2", "SD1", "CMD", "SD0", "CLK", "GND", "3V3", "EN", "RST", "GND", "VIN"],
            right_names=["D0", "D1", "D2", "D3", "D4", "3V3", "GND", "D5", "D6", "D7", "D8", "RX", "TX", "GND", "3V3"],
            row_span=9,
            pcb_colors=(QColor(35, 38, 44), QColor(20, 22, 26), QColor(65, 70, 78)),
            pad_top=3.0,
            pad_bottom=1.2,
            pad_side=0.55,
            usb_type="micro",
            rf_antenna="pcb",
            tags=["esp8266", "nodemcu", "v2", "amica", "wifi", "mcu"]
        )


class NodeMCUv3Def(DualRowDevBoardDef):
    def __init__(self):
        super().__init__(
            type_id="nodemcu_v3",
            name="ESP8266 NodeMCU v3 (Wide)",
            default_label="NodeMCU v3",
            description="LoLin NodeMCU v3 CH340 ESP8266 dev board (30 pins, 1.1\" / 11-hole wide span).",
            left_names=["A0", "GND", "VU", "SD3", "SD2", "SD1", "CMD", "SD0", "CLK", "GND", "3V3", "EN", "RST", "GND", "VIN"],
            right_names=["D0", "D1", "D2", "D3", "D4", "3V3", "GND", "D5", "D6", "D7", "D8", "RX", "TX", "GND", "3V3"],
            row_span=11,
            pcb_colors=(QColor(32, 34, 40), QColor(18, 20, 24), QColor(62, 66, 74)),
            pad_top=3.2,
            pad_bottom=1.4,
            pad_side=0.65,
            usb_type="micro",
            rf_antenna="pcb",
            tags=["esp8266", "nodemcu", "v3", "lolin", "ch340", "wifi", "mcu"]
        )


class ESP32DevKit30Def(DualRowDevBoardDef):
    def __init__(self):
        super().__init__(
            type_id="esp32_30p",
            name="ESP32 DevKit v1 (30-pin)",
            default_label="ESP32-30",
            description="DOIT ESP32 DevKit v1 WiFi/BLE board (30 pins, 1.0\" / 10-hole span).",
            left_names=["EN", "VP", "VN", "D34", "D35", "D32", "D33", "D25", "D26", "D27", "D14", "D12", "D13", "GND", "VIN"],
            right_names=["D23", "D22", "TX0", "RX0", "D21", "D19", "D18", "D5", "TX2", "RX2", "D4", "D2", "D15", "GND", "3V3"],
            row_span=10,
            pcb_colors=(QColor(34, 36, 42), QColor(18, 20, 24), QColor(65, 68, 76)),
            pad_top=3.4,
            pad_bottom=1.3,
            pad_side=0.55,
            usb_type="micro",
            rf_antenna="pcb",
            tags=["esp32", "devkit", "30pin", "wroom", "wifi", "ble", "mcu"]
        )


class ESP32DevKit38Def(DualRowDevBoardDef):
    def __init__(self):
        super().__init__(
            type_id="esp32_38p",
            name="ESP32 DevKitC (38-pin)",
            default_label="ESP32-38",
            description="Espressif ESP32-DevKitC WiFi/BLE board (38 pins, 1.0\" / 10-hole span).",
            left_names=[
                "3V3", "EN", "VP", "VN", "IO34", "IO35", "IO32", "IO33", "IO25", "IO26",
                "IO27", "IO14", "IO12", "GND", "IO13", "SD2", "SD3", "CMD", "5V"
            ],
            right_names=[
                "GND", "IO23", "IO22", "TXD0", "RXD0", "IO21", "IO19", "IO18", "IO5", "IO17",
                "IO16", "IO4", "IO0", "IO2", "IO15", "SD1", "SD0", "CLK", "GND"
            ],
            row_span=10,
            pcb_colors=(QColor(30, 32, 38), QColor(16, 18, 22), QColor(60, 64, 72)),
            pad_top=3.4,
            pad_bottom=1.3,
            pad_side=0.55,
            usb_type="micro",
            rf_antenna="pcb",
            tags=["esp32", "devkitc", "38pin", "wroom", "wifi", "ble", "mcu"]
        )


class ESP32SuperMiniDef(DualRowDevBoardDef):
    def __init__(self, chip: str = "C3"):
        self.chip = chip.upper()
        if self.chip == "C6":
            left = ["IO0", "IO1", "IO2", "IO3", "IO4", "IO5", "IO6", "IO7"]
            right = ["5V", "GND", "3V3", "IO14", "IO15", "IO18", "IO19", "IO20"]
            pcb = (QColor(48, 30, 75), QColor(28, 16, 48), QColor(85, 55, 130))
            desc = "Ultra-compact ESP32-C6 SuperMini RISC-V WiFi6/Zigbee/BLE board (2x8 pins, 0.6\" span)."
            tags = ["esp32", "c6", "supermini", "wifi6", "zigbee", "ble", "usbc", "mcu"]
        else:
            left = ["IO5", "IO6", "IO7", "IO8", "IO9", "IO10", "IO20", "IO21"]
            right = ["5V", "GND", "3V3", "IO4", "IO3", "IO2", "IO1", "IO0"]
            pcb = (QColor(28, 32, 42), QColor(16, 18, 24), QColor(58, 65, 82))
            desc = "Ultra-compact ESP32-C3 SuperMini RISC-V WiFi/BLE board (2x8 pins, 0.6\" span)."
            tags = ["esp32", "c3", "supermini", "wifi", "ble", "usbc", "mcu"]

        super().__init__(
            type_id=f"esp32_{self.chip.lower()}_supermini",
            name=f"ESP32-{self.chip} SuperMini",
            default_label=f"ESP32-{self.chip}",
            description=desc,
            left_names=left,
            right_names=right,
            row_span=6,
            pcb_colors=pcb,
            pad_top=1.35,
            pad_bottom=0.85,
            pad_side=0.5,
            usb_type="usbc",
            rf_antenna="ceramic",
            tags=tags
        )


ESP01_PINS = [
    PinDef(name="GND", grid_x=0, grid_y=0, description="Ground", pin_type="ground"),
    PinDef(name="IO2", grid_x=1, grid_y=0, description="GPIO2", pin_type="io"),
    PinDef(name="IO0", grid_x=2, grid_y=0, description="GPIO0 / Flash", pin_type="io"),
    PinDef(name="RX", grid_x=3, grid_y=0, description="UART RX", pin_type="io"),
    PinDef(name="TX", grid_x=0, grid_y=1, description="UART TX", pin_type="io"),
    PinDef(name="CH_PD", grid_x=1, grid_y=1, description="Chip Enable (Active High)", pin_type="io"),
    PinDef(name="RST", grid_x=2, grid_y=1, description="Reset (Active Low)", pin_type="io"),
    PinDef(name="VCC", grid_x=3, grid_y=1, description="3.3V Supply", pin_type="power"),
]


class ESP01Def(ComponentDef):
    def __init__(self):
        super().__init__(
            type_id="esp_01",
            name="ESP-01 Module (ESP8266)",
            category="Wireless & RF",
            default_label="ESP-01",
            description="ESP-01 / ESP-01S WiFi module with 2x4 2.54mm header and PCB meander antenna.",
            pins=ESP01_PINS,
            properties=[
                PropertyDef(id="label", label="Label", type="str", default="ESP-01"),
            ],
            anchor_pin_index=0,
            tags=["esp01", "esp-01", "esp8266", "wifi", "serial", "wireless"]
        )

    def _pcb_rect(self, p: float) -> QRectF:
        return QRectF(-1.1 * p, -7.8 * p, 5.2 * p, 9.5 * p)

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(self._pcb_rect(pitch_px), 3.0, 3.0)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        rect = self._pcb_rect(p)
        bx, by, bw, bh = rect.x(), rect.y(), rect.width(), rect.height()
        cx = bx + bw / 2.0

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 45))
        painter.drawRoundedRect(rect.translated(2.0, 2.5), 3.0, 3.0)

        # Black ESP-01S / Deep Blue PCB
        grad = QLinearGradient(bx, by, bx + bw, by + bh)
        grad.setColorAt(0.0, QColor(32, 34, 40))
        grad.setColorAt(1.0, QColor(18, 20, 24))
        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(QColor(58, 62, 70), 1.0))
        painter.drawRoundedRect(rect, 3.0, 3.0)

        # PCB meander antenna at top
        ant_x = bx + 0.7 * p
        ant_y = by + 0.4 * p
        ant_w = bw - 1.4 * p
        ant_h = 2.1 * p
        painter.setPen(QPen(QColor(215, 175, 65), 1.8))
        ap = QPainterPath()
        ap.moveTo(ant_x, ant_y + ant_h)
        step = ant_h / 4.0
        for i in range(4):
            y1 = ant_y + ant_h - i * step
            y2 = ant_y + ant_h - (i + 1) * step
            if i % 2 == 0:
                ap.lineTo(ant_x + ant_w, y1)
                ap.lineTo(ant_x + ant_w, y2)
            else:
                ap.lineTo(ant_x, y1)
                ap.lineTo(ant_x, y2)
        painter.drawPath(ap)

        # ESP8266EX QFN IC + SPI Flash IC
        painter.setBrush(QColor(20, 20, 22))
        painter.setPen(QPen(QColor(55, 55, 62), 0.7))
        painter.drawRect(QRectF(cx - 1.6 * p, by + 3.4 * p, 1.5 * p, 1.5 * p))
        painter.drawRect(QRectF(cx + 0.3 * p, by + 3.4 * p, 1.3 * p, 1.7 * p))

        label = instance.label if instance.label else "ESP-01"
        painter.setFont(QFont("Arial", int(max(5, p * 0.24)), QFont.Weight.Bold))
        painter.setPen(QColor(230, 235, 242))
        painter.drawText(QRectF(bx, by + 5.2 * p, bw, 1.1 * p), Qt.AlignmentFlag.AlignCenter, label)

        # 2x4 header shroud
        painter.setBrush(QColor(24, 24, 28))
        painter.setPen(QPen(QColor(55, 55, 62), 0.8))
        painter.drawRoundedRect(QRectF(-0.45 * p, -0.45 * p, 3.9 * p, 1.9 * p), 1.5, 1.5)

        for pin in ESP01_PINS:
            draw_top_pin(painter, pin.grid_x * p, pin.grid_y * p, 2.2)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        rect = self._pcb_rect(p)
        painter.setPen(QPen(QColor(180, 180, 190, 60), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(45, 48, 56, 20))
        painter.drawRoundedRect(rect, 3.0, 3.0)

        label = instance.label if instance.label else "ESP-01"
        painter.setFont(QFont("Arial", int(max(5, p * 0.25)), QFont.Weight.Bold))
        painter.setPen(QColor(195, 200, 215, 85))
        draw_unmirrored_text(painter, QRectF(rect.left(), rect.top() + 2.5 * p, rect.width(), 2.0 * p),
                             Qt.AlignmentFlag.AlignCenter, f"[{label}]")

        for pin in ESP01_PINS:
            draw_solder_joint(painter, pin.grid_x * p, pin.grid_y * p, p)
