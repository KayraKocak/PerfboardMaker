"""
Tactile Push Button (6x6mm) component definition.
"""
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QRadialGradient, QLinearGradient, QPainterPath
)
from PyQt6.QtCore import Qt, QRectF, QPointF
from app.models.component_def import ComponentDef, PinDef, PropertyDef
from app.components.draw_utils import draw_solder_joint, draw_top_pin

class PushButtonDef(ComponentDef):
    def __init__(self):
        # 4 pins standard 4x3 hole grid (7.62mm x 5.08mm) by default, configurable to 3x3
        pins = [
            PinDef(name="1", grid_x=0, grid_y=0, description="Terminal 1A", pin_type="passive"),
            PinDef(name="2", grid_x=0, grid_y=2, description="Terminal 1B (tied to 1)", pin_type="passive"),
            PinDef(name="3", grid_x=3, grid_y=0, description="Terminal 2A", pin_type="passive"),
            PinDef(name="4", grid_x=3, grid_y=2, description="Terminal 2B (tied to 3)", pin_type="passive"),
        ]

        super().__init__(
            type_id="push_button",
            name="Push Button (6x6mm)",
            category="Passives & Switches",
            default_label="SW1",
            description="4-pin tactile momentary switch (6x6mm package, selectable 4x3 or 3x3 hole footprint).",
            pins=pins,
            properties=[
                PropertyDef(id="label", label="Label", type="str", default="SW1"),
                PropertyDef(
                    id="footprint", label="Pin Footprint", type="choice",
                    default="4x3 (7.62x5.08mm)",
                    choices=["4x3 (7.62x5.08mm)", "3x3 (5.08x5.08mm)"]
                ),
                PropertyDef(id="color", label="Cap Color", type="choice", default="Black",
                            choices=["Black", "Red", "Blue", "Yellow", "Green"])
            ],
            anchor_pin_index=0,
            tags=["switch", "button", "tactile", "momentary", "6x6"]
        )

    def _dx(self, instance) -> int:
        fp = str(instance.custom_props.get("footprint", "4x3 (7.62x5.08mm)"))
        return 2 if "3x3" in fp else 3

    def get_pins_for_instance(self, instance) -> list[PinDef]:
        dx = self._dx(instance)
        return [
            PinDef(name="1", grid_x=0, grid_y=0, description="Terminal 1A", pin_type="passive"),
            PinDef(name="2", grid_x=0, grid_y=2, description="Terminal 1B (tied to 1)", pin_type="passive"),
            PinDef(name="3", grid_x=dx, grid_y=0, description="Terminal 2A", pin_type="passive"),
            PinDef(name="4", grid_x=dx, grid_y=2, description="Terminal 2B (tied to 3)", pin_type="passive"),
        ]

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        p = pitch_px
        dx = self._dx(instance)
        path = QPainterPath()
        path.addRoundedRect(QRectF(-0.35 * p, -0.3 * p, (dx + 0.7) * p, 2.6 * p), 2.5, 2.5)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        dx = self._dx(instance)
        cx = (dx * p) / 2.0
        cy = 1.0 * p
        bw = 2.4 * p
        bh = 2.4 * p
        bx = cx - bw / 2.0
        by = cy - bh / 2.0

        # Metal terminal leads extending to holes
        painter.setPen(QPen(QColor(160, 165, 175), 2.2))
        # Left pins: (0, 0) and (0, 2)
        painter.drawLine(QPointF(0, 0), QPointF(bx + 2, 0))
        painter.drawLine(QPointF(0, 2 * p), QPointF(bx + 2, 2 * p))
        # Right pins: (dx, 0) and (dx, 2)
        painter.drawLine(QPointF(dx * p, 0), QPointF(bx + bw - 2, 0))
        painter.drawLine(QPointF(dx * p, 2 * p), QPointF(bx + bw - 2, 2 * p))

        # Shadow
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 40))
        painter.drawRoundedRect(QRectF(bx + 1.5, by + 2.0, bw, bh), 2.5, 2.5)

        # Base body (Dark grey / silver metal top)
        plate_grad = QLinearGradient(bx, by, bx + bw, by + bh)
        plate_grad.setColorAt(0.0, QColor(220, 225, 230))
        plate_grad.setColorAt(0.5, QColor(190, 195, 200))
        plate_grad.setColorAt(1.0, QColor(160, 165, 170))
        painter.setBrush(QBrush(plate_grad))
        painter.setPen(QPen(QColor(110, 115, 120), 1.0))
        painter.drawRoundedRect(QRectF(bx, by, bw, bh), 2.5, 2.5)

        # 4 metal corner rivet crimps
        crimp_r = 1.2
        painter.setBrush(QColor(130, 135, 140))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(bx + 2.5, by + 2.5), crimp_r, crimp_r)
        painter.drawEllipse(QPointF(bx + bw - 2.5, by + 2.5), crimp_r, crimp_r)
        painter.drawEllipse(QPointF(bx + 2.5, by + bh - 2.5), crimp_r, crimp_r)
        painter.drawEllipse(QPointF(bx + bw - 2.5, by + bh - 2.5), crimp_r, crimp_r)

        # Actuator button color
        color_name = instance.custom_props.get("color", "Black")
        color_map = {
            "Black": (QColor(40, 40, 45), QColor(20, 20, 25)),
            "Red": (QColor(230, 60, 50), QColor(160, 30, 20)),
            "Blue": (QColor(50, 130, 230), QColor(20, 80, 170)),
            "Yellow": (QColor(240, 200, 40), QColor(190, 150, 20)),
            "Green": (QColor(50, 190, 80), QColor(20, 130, 45)),
        }
        c1, c2 = color_map.get(color_name, color_map["Black"])

        btn_r = 0.65 * p
        btn_grad = QRadialGradient(cx - btn_r * 0.3, cy - btn_r * 0.3, btn_r)
        btn_grad.setColorAt(0.0, c1)
        btn_grad.setColorAt(1.0, c2)
        painter.setBrush(QBrush(btn_grad))
        painter.setPen(QPen(QColor(30, 30, 30, 180), 0.8))
        painter.drawEllipse(QPointF(cx, cy), btn_r, btn_r)

        # Center disc highlight
        painter.setBrush(QColor(255, 255, 255, 40))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx - btn_r * 0.3, cy - btn_r * 0.3), btn_r * 0.25, btn_r * 0.25)

        # Label text
        label_text = instance.label if instance.label else "SW"
        font = QFont("Arial", int(max(6, p * 0.24)), QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(240, 240, 240) if color_name == "Black" else QColor(30, 30, 30))
        painter.drawText(QRectF(cx - btn_r, cy - btn_r, btn_r * 2, btn_r * 2),
                         Qt.AlignmentFlag.AlignCenter, label_text)

        # Pins entering holes
        draw_top_pin(painter, 0, 0, 2.4)
        draw_top_pin(painter, 0, 2 * p, 2.4)
        draw_top_pin(painter, dx * p, 0, 2.4)
        draw_top_pin(painter, dx * p, 2 * p, 2.4)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        dx = self._dx(instance)
        cx = (dx * p) / 2.0
        cy = 1.0 * p

        # Ghost outline
        painter.setPen(QPen(QColor(150, 150, 160, 60), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(160, 165, 175, 20))
        painter.drawRoundedRect(QRectF(cx - 1.2 * p, cy - 1.2 * p, 2.4 * p, 2.4 * p), 2.5, 2.5)

        # Internal trace hint between tied pins (1-2 and 3-4)
        painter.setPen(QPen(QColor(100, 200, 255, 50), 1.5, Qt.PenStyle.DotLine))
        painter.drawLine(QPointF(0, 0), QPointF(0, 2 * p))
        painter.drawLine(QPointF(dx * p, 0), QPointF(dx * p, 2 * p))

        # Solder joints for 4 pins
        draw_solder_joint(painter, 0, 0, p)
        draw_solder_joint(painter, 0, 2 * p, p)
        draw_solder_joint(painter, dx * p, 0, p)
        draw_solder_joint(painter, dx * p, 2 * p, p)
