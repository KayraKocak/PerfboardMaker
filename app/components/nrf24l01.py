"""
nRF24L01 2.4GHz Wireless Module component definition.
"""
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QLinearGradient, QPainterPath
)
from PyQt6.QtCore import Qt, QRectF, QPointF
from app.models.component_def import ComponentDef, PinDef, PropertyDef
from app.components.draw_utils import draw_solder_joint, draw_top_pin, draw_unmirrored_text

NRF_PINS = [
    PinDef(name="GND", grid_x=0, grid_y=0, description="Ground", pin_type="ground"),
    PinDef(name="VCC", grid_x=0, grid_y=1, description="3.3V Supply", pin_type="power"),
    PinDef(name="CE",  grid_x=1, grid_y=0, description="Chip Enable", pin_type="io"),
    PinDef(name="CSN", grid_x=1, grid_y=1, description="SPI Chip Select", pin_type="io"),
    PinDef(name="SCK", grid_x=2, grid_y=0, description="SPI Clock", pin_type="io"),
    PinDef(name="MOSI", grid_x=2, grid_y=1, description="SPI Data In", pin_type="io"),
    PinDef(name="MISO", grid_x=3, grid_y=0, description="SPI Data Out", pin_type="io"),
    PinDef(name="IRQ", grid_x=3, grid_y=1, description="Interrupt Request", pin_type="io"),
]

class NRF24L01Def(ComponentDef):
    def __init__(self):
        super().__init__(
            type_id="nrf24l01",
            name="nRF24L01 Module",
            category="Wireless & RF",
            default_label="nRF24",
            description="2.4GHz RF transceiver module with 2x4 header and integrated PCB antenna.",
            pins=NRF_PINS,
            properties=[
                PropertyDef(id="label", label="Label", type="str", default="nRF24")
            ],
            anchor_pin_index=0,
            tags=["nrf24l01", "rf", "wireless", "transceiver", "spi", "2.4ghz"]
        )

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        p = pitch_px
        bx = -0.9 * p
        by = -9.2 * p
        bw = 4.8 * p
        bh = 11.0 * p
        path = QPainterPath()
        path.addRoundedRect(QRectF(bx, by, bw, bh), 3.0, 3.0)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        # Pins: cols 0..3, rows 0..1
        # PCB boundaries: width ~5.8 grid units, length ~11.5 grid units
        bx = -0.9 * p
        by = -9.2 * p
        bw = 4.8 * p
        bh = 11.0 * p

        # Shadow
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 45))
        painter.drawRoundedRect(QRectF(bx + 2, by + 2, bw, bh), 3.0, 3.0)

        # Black PCB
        pcb_grad = QLinearGradient(bx, by, bx + bw, by + bh)
        pcb_grad.setColorAt(0.0, QColor(35, 35, 38))
        pcb_grad.setColorAt(0.5, QColor(25, 25, 28))
        pcb_grad.setColorAt(1.0, QColor(15, 15, 18))
        painter.setBrush(QBrush(pcb_grad))
        painter.setPen(QPen(QColor(55, 55, 60), 1.0))
        painter.drawRoundedRect(QRectF(bx, by, bw, bh), 3.0, 3.0)

        # PCB Antenna area (top portion)
        ant_y = by + 0.4 * p
        ant_h = 2.8 * p
        # Golden copper serpentine track
        painter.setPen(QPen(QColor(215, 175, 60), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.MiterJoin))
        ant_path = QPainterPath()
        start_x = bx + 0.8 * p
        ant_path.moveTo(start_x, ant_y + ant_h - 2)
        # Serpentine meanders
        meander_w = bw - 1.6 * p
        step = ant_h / 4.0
        for i in range(4):
            y_curr = ant_y + ant_h - i * step
            y_next = ant_y + ant_h - (i + 1) * step
            if i % 2 == 0:
                ant_path.lineTo(start_x + meander_w, y_curr)
                ant_path.lineTo(start_x + meander_w, y_next)
            else:
                ant_path.lineTo(start_x, y_curr)
                ant_path.lineTo(start_x, y_next)
        painter.drawPath(ant_path)

        # nRF24L01 IC (QFN-20 in center)
        ic_size = 1.6 * p
        ic_cx = bx + bw / 2.0
        ic_cy = by + 5.2 * p
        painter.setBrush(QColor(20, 20, 24))
        painter.setPen(QPen(QColor(50, 50, 55), 0.8))
        painter.drawRect(QRectF(ic_cx - ic_size / 2, ic_cy - ic_size / 2, ic_size, ic_size))
        # Pin 1 mark
        painter.setBrush(QColor(120, 120, 120))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(ic_cx - ic_size / 2 + 2, ic_cy - ic_size / 2 + 2), 1.0, 1.0)

        # 16 MHz Crystal oscillator
        xtal_w = 0.8 * p
        xtal_h = 1.4 * p
        painter.setBrush(QColor(185, 190, 195))
        painter.setPen(QPen(QColor(110, 115, 120), 0.8))
        painter.drawRoundedRect(QRectF(ic_cx + 0.9 * p, ic_cy - 0.7 * p, xtal_w, xtal_h), 1.0, 1.0)

        # Silkscreen text
        font = QFont("Arial", int(max(6, p * 0.24)), QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(230, 230, 240))
        label_text = instance.label if instance.label else "nRF24L01"
        painter.drawText(QRectF(bx, by + 3.2 * p, bw, 1.2 * p), Qt.AlignmentFlag.AlignCenter, label_text)

        # 2x4 Header plastic block
        hdr_x = -0.45 * p
        hdr_y = -0.45 * p
        hdr_w = 3.9 * p
        hdr_h = 1.9 * p
        painter.setBrush(QColor(25, 25, 28))
        painter.setPen(QPen(QColor(50, 50, 55), 0.8))
        painter.drawRoundedRect(QRectF(hdr_x, hdr_y, hdr_w, hdr_h), 1.5, 1.5)

        # Pin labels small
        p_font = QFont("Arial", int(max(4, p * 0.16)), QFont.Weight.Normal)
        painter.setFont(p_font)
        painter.setPen(QColor(200, 200, 210, 200))
        for pin in NRF_PINS:
            painter.drawText(QRectF(pin.grid_x * p - 0.4 * p, pin.grid_y * p - 0.4 * p, 0.8 * p, 0.4 * p),
                             Qt.AlignmentFlag.AlignCenter, pin.name)

        # Pins entering holes
        for pin in NRF_PINS:
            draw_top_pin(painter, pin.grid_x * p, pin.grid_y * p, 2.4)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        bx = -0.9 * p
        by = -9.2 * p
        bw = 4.8 * p
        bh = 11.0 * p

        # Ghost outline
        painter.setPen(QPen(QColor(180, 180, 190, 60), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(50, 50, 60, 20))
        painter.drawRoundedRect(QRectF(bx, by, bw, bh), 3.0, 3.0)

        # Label in ghost
        label_text = instance.label if instance.label else "nRF24L01"
        font = QFont("Arial", int(max(6, p * 0.25)), QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(180, 180, 200, 80))
        draw_unmirrored_text(painter, QRectF(bx, by + 4.0 * p, bw, 2.0 * p), Qt.AlignmentFlag.AlignCenter, f"[{label_text}]")

        # 8 Solder joints for 2x4 header
        for pin in NRF_PINS:
            draw_solder_joint(painter, pin.grid_x * p, pin.grid_y * p, p)
