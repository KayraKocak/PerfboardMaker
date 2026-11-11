"""
nRF24L01+PA+LNA Wireless Module with SMA connector and antenna.
"""
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QLinearGradient, QRadialGradient, QPainterPath
)
from PyQt6.QtCore import Qt, QRectF, QPointF
from app.models.component_def import ComponentDef, PinDef, PropertyDef
from app.components.draw_utils import draw_solder_joint, draw_top_pin, draw_unmirrored_text
from app.components.nrf24l01 import NRF_PINS

class NRF24L01PALNADef(ComponentDef):
    def __init__(self):
        super().__init__(
            type_id="nrf24l01_pa_lna",
            name="nRF24L01+PA+LNA Module",
            category="Wireless & RF",
            default_label="nRF+PA",
            description="Long-range 2.4GHz RF transceiver with Power Amp, LNA, and external SMA rubber duck antenna.",
            pins=NRF_PINS,
            properties=[
                PropertyDef(id="label", label="Label", type="str", default="nRF+PA"),
                PropertyDef(id="show_antenna", label="Show Antenna", type="choice", default="Yes",
                            choices=["Yes", "SMA Only"])
            ],
            anchor_pin_index=0,
            tags=["nrf24l01", "pa", "lna", "rf", "wireless", "antenna", "long-range"]
        )

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        p = pitch_px
        bx = -0.9 * p
        by = -14.2 * p
        bw = 4.8 * p
        bh = 16.0 * p
        path = QPainterPath()
        # PCB area
        path.addRoundedRect(QRectF(bx, by, bw, bh), 3.0, 3.0)
        # SMA connector area
        sma_w = 2.4 * p
        sma_h = 2.2 * p
        sma_x = bx + bw / 2.0 - sma_w / 2.0
        sma_y = by - 1.8 * p
        path.addRoundedRect(QRectF(sma_x, sma_y, sma_w, sma_h), 1.5, 1.5)
        # Antenna area if visible
        show_ant = instance.custom_props.get("show_antenna", "Yes") == "Yes"
        if show_ant:
            ant_w = 2.2 * p
            ant_h = 10.0 * p
            ant_x = bx + bw / 2.0 - ant_w / 2.0
            ant_y = sma_y - ant_h
            path.addRoundedRect(QRectF(ant_x, ant_y, ant_w, ant_h), 4.0, 4.0)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        bx = -0.9 * p
        by = -14.2 * p
        bw = 4.8 * p
        bh = 16.0 * p

        # Shadow
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 50))
        painter.drawRoundedRect(QRectF(bx + 2, by + 2, bw, bh), 3.0, 3.0)

        # Black PCB
        pcb_grad = QLinearGradient(bx, by, bx + bw, by + bh)
        pcb_grad.setColorAt(0.0, QColor(32, 32, 36))
        pcb_grad.setColorAt(0.5, QColor(22, 22, 25))
        pcb_grad.setColorAt(1.0, QColor(14, 14, 16))
        painter.setBrush(QBrush(pcb_grad))
        painter.setPen(QPen(QColor(50, 50, 55), 1.0))
        painter.drawRoundedRect(QRectF(bx, by, bw, bh), 3.0, 3.0)

        # SMA Connector at top edge (Gold plated)
        sma_w = 2.4 * p
        sma_h = 2.2 * p
        sma_x = bx + bw / 2.0 - sma_w / 2.0
        sma_y = by - 1.8 * p

        sma_grad = QLinearGradient(sma_x, sma_y, sma_x + sma_w, sma_y)
        sma_grad.setColorAt(0.0, QColor(190, 150, 40))
        sma_grad.setColorAt(0.5, QColor(250, 215, 80))
        sma_grad.setColorAt(1.0, QColor(180, 140, 30))
        painter.setBrush(QBrush(sma_grad))
        painter.setPen(QPen(QColor(140, 100, 20), 0.8))
        painter.drawRoundedRect(QRectF(sma_x, sma_y, sma_w, sma_h), 1.5, 1.5)

        # SMA barrel threading
        painter.setPen(QPen(QColor(150, 110, 25), 0.8))
        for line_y in (sma_y + 0.5 * p, sma_y + 0.9 * p, sma_y + 1.3 * p):
            painter.drawLine(QPointF(sma_x + 1, line_y), QPointF(sma_x + sma_w - 1, line_y))

        # Rubber duck antenna (if enabled)
        show_ant = instance.custom_props.get("show_antenna", "Yes") == "Yes"
        if show_ant:
            ant_w = 2.2 * p
            ant_h = 10.0 * p
            ant_x = bx + bw / 2.0 - ant_w / 2.0
            ant_y = sma_y - ant_h
            # Antenna shadow
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 40))
            painter.drawRoundedRect(QRectF(ant_x + 3, ant_y + 2, ant_w, ant_h), 4.0, 4.0)

            # Antenna rubber body
            ant_grad = QLinearGradient(ant_x, ant_y, ant_x + ant_w, ant_y)
            ant_grad.setColorAt(0.0, QColor(45, 45, 50))
            ant_grad.setColorAt(0.4, QColor(65, 65, 72))
            ant_grad.setColorAt(1.0, QColor(30, 30, 34))
            painter.setBrush(QBrush(ant_grad))
            painter.setPen(QPen(QColor(25, 25, 28), 1.0))
            painter.drawRoundedRect(QRectF(ant_x, ant_y, ant_w, ant_h), 4.0, 4.0)

            # Knurled grip ridges on antenna base
            painter.setPen(QPen(QColor(80, 80, 90), 0.8))
            for line_y in (ant_y + ant_h - 1.2 * p, ant_y + ant_h - 0.8 * p, ant_y + ant_h - 0.4 * p):
                painter.drawLine(QPointF(ant_x + 2, line_y), QPointF(ant_x + ant_w - 2, line_y))

        # Metal RF Shielding Can (Silver box covering PA+LNA)
        can_w = bw - 1.0 * p
        can_h = 5.6 * p
        can_x = bx + 0.5 * p
        can_y = by + 1.2 * p

        can_grad = QLinearGradient(can_x, can_y, can_x + can_w, can_y + can_h)
        can_grad.setColorAt(0.0, QColor(225, 230, 235))
        can_grad.setColorAt(0.5, QColor(195, 200, 205))
        can_grad.setColorAt(1.0, QColor(170, 175, 180))
        painter.setBrush(QBrush(can_grad))
        painter.setPen(QPen(QColor(130, 135, 140), 1.0))
        painter.drawRoundedRect(QRectF(can_x, can_y, can_w, can_h), 2.0, 2.0)

        # Embossed label on shield can
        font_can = QFont("Arial", int(max(5, p * 0.22)), QFont.Weight.Bold)
        painter.setFont(font_can)
        painter.setPen(QColor(100, 105, 110))
        painter.drawText(QRectF(can_x, can_y + 1.2 * p, can_w, 1.2 * p), Qt.AlignmentFlag.AlignCenter, "RF SHIELD")
        painter.drawText(QRectF(can_x, can_y + 2.5 * p, can_w, 1.2 * p), Qt.AlignmentFlag.AlignCenter, "PA + LNA")

        # Silkscreen text on PCB below shield
        font = QFont("Arial", int(max(6, p * 0.24)), QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(230, 230, 240))
        label_text = instance.label if instance.label else "nRF+PA+LNA"
        painter.drawText(QRectF(bx, by + 7.5 * p, bw, 1.2 * p), Qt.AlignmentFlag.AlignCenter, label_text)

        # 2x4 Header plastic block at bottom
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
        by = -14.2 * p
        bw = 4.8 * p
        bh = 16.0 * p

        # Ghost outline
        painter.setPen(QPen(QColor(180, 180, 190, 60), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(50, 50, 60, 20))
        painter.drawRoundedRect(QRectF(bx, by, bw, bh), 3.0, 3.0)

        # Label in ghost
        label_text = instance.label if instance.label else "nRF+PA+LNA"
        font = QFont("Arial", int(max(6, p * 0.25)), QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(180, 180, 200, 80))
        draw_unmirrored_text(painter, QRectF(bx, by + 7.0 * p, bw, 2.0 * p), Qt.AlignmentFlag.AlignCenter, f"[{label_text}]")

        # 8 Solder joints for 2x4 header
        for pin in NRF_PINS:
            draw_solder_joint(painter, pin.grid_x * p, pin.grid_y * p, p)
