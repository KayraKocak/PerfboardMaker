"""
TO-220 Packaged IC component definition (renameable).
"""
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QRadialGradient, QLinearGradient, QPainterPath
)
from PyQt6.QtCore import Qt, QRectF, QPointF
from app.models.component_def import ComponentDef, PinDef, PropertyDef
from app.components.draw_utils import draw_solder_joint, draw_top_pin, draw_unmirrored_text

class TO220Def(ComponentDef):
    def __init__(self):
        pins = [
            PinDef(name="1", grid_x=0, grid_y=0, description="Pin 1 (e.g. IN / Gate)", pin_type="io"),
            PinDef(name="2", grid_x=1, grid_y=0, description="Pin 2 (e.g. GND / Drain)", pin_type="ground"),
            PinDef(name="3", grid_x=2, grid_y=0, description="Pin 3 (e.g. OUT / Source)", pin_type="io"),
        ]

        super().__init__(
            type_id="to220",
            name="TO-220 Package IC",
            category="Semiconductors & ICs",
            default_label="LM7805",
            description="3-pin power transistor / voltage regulator package with metal heatsink tab (renameable).",
            pins=pins,
            properties=[
                PropertyDef(id="label", label="Part Number / Label", type="str", default="LM7805"),
                PropertyDef(id="sublabel", label="Sub-text", type="str", default="+5V Reg")
            ],
            anchor_pin_index=0,
            tags=["to220", "transistor", "regulator", "mosfet", "7805", "lm317"]
        )

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        p = pitch_px
        path = QPainterPath()
        # Covers metal tab, plastic body, and pins
        path.addRoundedRect(QRectF(-1.2 * p, -2.7 * p, 4.4 * p, 3.9 * p), 2.0, 2.0)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        # 3 pins: (0,0), (1,0), (2,0). Center pin is at (1.0*p, 0)
        cx = 1.0 * p
        bw = 4.2 * p
        bx = cx - bw / 2.0

        # Metal heatsink tab at back (y < 0)
        tab_w = 4.0 * p
        tab_h = 2.4 * p
        tab_x = cx - tab_w / 2.0
        tab_y = -2.6 * p

        # Shadow
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 45))
        painter.drawRoundedRect(QRectF(tab_x + 2, tab_y + 2, tab_w, tab_h + 3.8 * p), 2.0, 2.0)

        # Draw Metal Heatsink Tab
        tab_grad = QLinearGradient(tab_x, tab_y, tab_x + tab_w, tab_y)
        tab_grad.setColorAt(0.0, QColor(190, 195, 200))
        tab_grad.setColorAt(0.5, QColor(235, 240, 245))
        tab_grad.setColorAt(1.0, QColor(170, 175, 180))
        painter.setBrush(QBrush(tab_grad))
        painter.setPen(QPen(QColor(120, 125, 130), 1.0))
        painter.drawRoundedRect(QRectF(tab_x, tab_y, tab_w, tab_h), 2.0, 2.0)

        # Tab Mounting Hole
        hole_r = 0.65 * p
        hole_cy = tab_y + tab_h * 0.45
        painter.setBrush(QColor(30, 30, 35))
        painter.setPen(QPen(QColor(130, 135, 140), 1.0))
        painter.drawEllipse(QPointF(cx, hole_cy), hole_r, hole_r)

        # Epoxy body
        body_y = -0.7 * p
        body_h = 1.8 * p
        body_grad = QLinearGradient(bx, body_y, bx, body_y + body_h)
        body_grad.setColorAt(0.0, QColor(45, 45, 50))
        body_grad.setColorAt(0.7, QColor(30, 30, 35))
        body_grad.setColorAt(1.0, QColor(20, 20, 25))
        painter.setBrush(QBrush(body_grad))
        painter.setPen(QPen(QColor(60, 60, 65), 1.0))
        painter.drawRoundedRect(QRectF(bx, body_y, bw, body_h), 1.5, 1.5)

        # Front bevel line
        painter.setPen(QPen(QColor(70, 70, 75), 1.0))
        painter.drawLine(QPointF(bx + 2, body_y + body_h * 0.75), QPointF(bx + bw - 2, body_y + body_h * 0.75))

        # Part label text (renameable!)
        label_text = instance.label if instance.label else "LM7805"
        font = QFont("Arial", int(max(6, p * 0.28)), QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(240, 240, 245))
        painter.drawText(QRectF(bx, body_y + 0.1 * p, bw, body_h * 0.65), Qt.AlignmentFlag.AlignCenter, label_text)

        # Pin leads extending to holes
        painter.setPen(QPen(QColor(180, 185, 195), 2.4))
        painter.drawLine(QPointF(0, body_y + body_h), QPointF(0, 0))
        painter.drawLine(QPointF(1.0 * p, body_y + body_h), QPointF(1.0 * p, 0))
        painter.drawLine(QPointF(2.0 * p, body_y + body_h), QPointF(2.0 * p, 0))

        # Pins entering holes
        draw_top_pin(painter, 0, 0, 2.5)
        draw_top_pin(painter, 1.0 * p, 0, 2.5)
        draw_top_pin(painter, 2.0 * p, 0, 2.5)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        cx = 1.0 * p
        bw = 4.2 * p
        bx = cx - bw / 2.0

        # Ghost outline of tab and body
        painter.setPen(QPen(QColor(180, 180, 190, 60), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(120, 120, 130, 20))
        painter.drawRoundedRect(QRectF(bx, -2.6 * p, bw, 3.7 * p), 2.0, 2.0)

        # Label in ghost
        label_text = instance.label if instance.label else "LM7805"
        font = QFont("Arial", int(max(6, p * 0.25)), QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(200, 200, 210, 80))
        draw_unmirrored_text(painter, QRectF(bx, -1.8 * p, bw, 1.5 * p), Qt.AlignmentFlag.AlignCenter, f"[{label_text}]")

        # Solder joints for 3 pins
        draw_solder_joint(painter, 0, 0, p)
        draw_solder_joint(painter, 1.0 * p, 0, p)
        draw_solder_joint(painter, 2.0 * p, 0, p)
