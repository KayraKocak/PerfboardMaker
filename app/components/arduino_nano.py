"""
Arduino Nano component definition.
"""
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QLinearGradient, QRadialGradient, QPainterPath
)
from PyQt6.QtCore import Qt, QRectF, QPointF
from app.models.component_def import ComponentDef, PinDef, PropertyDef
from app.components.draw_utils import draw_solder_joint, draw_top_pin, draw_unmirrored_text

LEFT_PINS = [
    ("D13", "io"), ("3V3", "power"), ("REF", "io"), ("A0", "io"),
    ("A1", "io"), ("A2", "io"), ("A3", "io"), ("A4", "io"),
    ("A5", "io"), ("A6", "io"), ("A7", "io"), ("5V", "power"),
    ("RST", "io"), ("GND", "ground"), ("VIN", "power")
]

RIGHT_PINS = [
    ("D12", "io"), ("D11", "io"), ("D10", "io"), ("D9", "io"),
    ("D8", "io"), ("D7", "io"), ("D6", "io"), ("D5", "io"),
    ("D4", "io"), ("D3", "io"), ("D2", "io"), ("GND", "ground"),
    ("RST", "io"), ("RX0", "io"), ("TX1", "io")
]

class ArduinoNanoDef(ComponentDef):
    def __init__(self):
        pins = []
        for i, (name, ptype) in enumerate(LEFT_PINS):
            pins.append(PinDef(name=name, grid_x=0, grid_y=i, description=f"Pin {name}", pin_type=ptype))
        for i, (name, ptype) in enumerate(RIGHT_PINS):
            pins.append(PinDef(name=name, grid_x=6, grid_y=i, description=f"Pin {name}", pin_type=ptype))

        super().__init__(
            type_id="arduino_nano",
            name="Arduino Nano",
            category="Microcontrollers",
            default_label="Nano",
            description="ATmega328P based microcontroller board with 30 DIP pins (0.6\" span).",
            pins=pins,
            properties=[
                PropertyDef(id="label", label="Label", type="str", default="Nano")
            ],
            anchor_pin_index=0,
            tags=["arduino", "mcu", "avr", "atmega328p"]
        )

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        p = pitch_px
        bx = -0.65 * p
        by = -2.3 * p  # Includes USB overhang
        bw = 7.3 * p
        bh = 17.9 * p
        path = QPainterPath()
        path.addRoundedRect(QRectF(bx, by, bw, bh), 4.0, 4.0)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        # Board dimensions in pixels
        # 6 units wide between pin centers. PCB width is about 7.2 units (-0.6 to 6.6)
        # Pins y: 0 to 14. PCB length is about 17.5 units (-1.6 to 15.6)
        bx = -0.65 * p
        by = -1.6 * p
        bw = 7.3 * p
        bh = 17.2 * p

        # PCB Shadow
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 45))
        painter.drawRoundedRect(QRectF(bx + 2, by + 3, bw, bh), 4.0, 4.0)

        # Blue PCB Substrate
        pcb_grad = QLinearGradient(bx, by, bx + bw, by + bh)
        pcb_grad.setColorAt(0.0, QColor(0, 85, 150))
        pcb_grad.setColorAt(0.5, QColor(0, 70, 130))
        pcb_grad.setColorAt(1.0, QColor(0, 50, 100))
        painter.setBrush(QBrush(pcb_grad))
        painter.setPen(QPen(QColor(0, 110, 190), 1.0))
        painter.drawRoundedRect(QRectF(bx, by, bw, bh), 4.0, 4.0)

        # USB Connector (Mini-B / Type-C) at top
        usb_w = 3.2 * p
        usb_h = 2.0 * p
        usb_x = (bx + bw / 2.0) - usb_w / 2.0
        usb_y = by - 0.7 * p
        usb_grad = QLinearGradient(usb_x, usb_y, usb_x + usb_w, usb_y)
        usb_grad.setColorAt(0.0, QColor(180, 185, 190))
        usb_grad.setColorAt(0.5, QColor(230, 235, 240))
        usb_grad.setColorAt(1.0, QColor(160, 165, 170))
        painter.setBrush(QBrush(usb_grad))
        painter.setPen(QPen(QColor(100, 105, 110), 1.0))
        painter.drawRoundedRect(QRectF(usb_x, usb_y, usb_w, usb_h), 2.0, 2.0)
        # USB inner port
        painter.setBrush(QColor(30, 30, 30))
        painter.drawRect(QRectF(usb_x + 0.4 * p, usb_y, usb_w - 0.8 * p, 0.4 * p))

        # ICSP Header (2x3 pins near bottom)
        icsp_x = bx + bw / 2.0 - 0.5 * p
        icsp_y = by + bh - 2.8 * p
        painter.setBrush(QColor(25, 25, 25))
        painter.setPen(QPen(QColor(60, 60, 60), 0.8))
        painter.drawRect(QRectF(icsp_x - 0.4 * p, icsp_y - 0.4 * p, 1.8 * p, 1.2 * p))
        for ix in (0, 1):
            for iy in (0, 1, 2):
                draw_top_pin(painter, icsp_x + ix * 0.8 * p, icsp_y + iy * 0.35 * p, 1.8)

        # ATmega328P QFP-32 package in center (tilted 45 degrees)
        painter.save()
        cx = bx + bw / 2.0
        cy = by + bh * 0.48
        painter.translate(cx, cy)
        painter.rotate(45)
        chip_size = 2.4 * p
        painter.setBrush(QColor(20, 20, 20))
        painter.setPen(QPen(QColor(40, 40, 40), 1.0))
        painter.drawRect(QRectF(-chip_size / 2, -chip_size / 2, chip_size, chip_size))
        # Pin 1 dot
        painter.setBrush(QColor(90, 90, 90))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(-chip_size / 2 + 3, -chip_size / 2 + 3), 1.5, 1.5)
        painter.restore()

        # Reset button
        rst_w = 1.6 * p
        rst_h = 1.2 * p
        rst_x = cx - rst_w / 2.0
        rst_y = by + 2.0 * p
        painter.setBrush(QColor(200, 205, 210))
        painter.setPen(QPen(QColor(130, 135, 140), 0.8))
        painter.drawRoundedRect(QRectF(rst_x, rst_y, rst_w, rst_h), 1.5, 1.5)
        painter.setBrush(QColor(210, 50, 40)) # Red actuator button
        painter.drawEllipse(QRectF(cx - 0.3 * p, rst_y + 0.25 * p, 0.6 * p, 0.6 * p))

        # Crystal oscillator
        xtal_w = 1.0 * p
        xtal_h = 2.0 * p
        painter.setBrush(QColor(190, 195, 200))
        painter.setPen(QPen(QColor(120, 120, 120), 0.8))
        painter.drawRoundedRect(QRectF(cx - xtal_w / 2, cy - 2.8 * p, xtal_w, xtal_h), 1.5, 1.5)

        # Silkscreen text
        font = QFont("Arial", int(max(7, p * 0.28)), QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(245, 245, 255))
        label_text = instance.label if instance.label else "NANO"
        painter.drawText(QRectF(bx, cy + 1.8 * p, bw, 1.5 * p), Qt.AlignmentFlag.AlignCenter, label_text)

        # Pin labels silkscreen
        lbl_font = QFont("Arial", int(max(5, p * 0.22)), QFont.Weight.Normal)
        painter.setFont(lbl_font)
        painter.setPen(QColor(230, 235, 245, 220))
        for i, (name, _) in enumerate(LEFT_PINS):
            painter.drawText(QRectF(0.4 * p, i * p - 0.4 * p, 2.2 * p, 0.8 * p),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)
        for i, (name, _) in enumerate(RIGHT_PINS):
            painter.drawText(QRectF(3.4 * p, i * p - 0.4 * p, 2.2 * p, 0.8 * p),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, name)

        # Draw pin headers & pins entering the board
        header_w = 0.85 * p
        painter.setBrush(QColor(30, 30, 30))
        painter.setPen(QPen(QColor(50, 50, 50), 0.8))
        # Left header strip
        painter.drawRoundedRect(QRectF(-0.45 * p, -0.45 * p, 0.9 * p, 14.9 * p), 2.0, 2.0)
        # Right header strip
        painter.drawRoundedRect(QRectF(5.55 * p, -0.45 * p, 0.9 * p, 14.9 * p), 2.0, 2.0)

        for i in range(15):
            draw_top_pin(painter, 0, i * p, 2.6)
            draw_top_pin(painter, 6 * p, i * p, 2.6)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        # Ghost silhouette of Nano on bottom view
        bx = -0.65 * p
        by = -1.6 * p
        bw = 7.3 * p
        bh = 17.2 * p

        # Draw faint ghosted PCB outline
        painter.setPen(QPen(QColor(0, 100, 180, 70), 1.2, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(0, 80, 150, 25))
        painter.drawRoundedRect(QRectF(bx, by, bw, bh), 4.0, 4.0)

        # Label inside ghost
        font = QFont("Arial", int(max(7, p * 0.3)), QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(100, 180, 255, 90))
        label_text = instance.label if instance.label else "NANO"
        draw_unmirrored_text(painter, QRectF(bx, by + bh * 0.45, bw, 2.0 * p), Qt.AlignmentFlag.AlignCenter, f"[{label_text}]")

        # Solder joints for all 30 pins
        for i in range(15):
            draw_solder_joint(painter, 0, i * p, p)
            draw_solder_joint(painter, 6 * p, i * p, p)
