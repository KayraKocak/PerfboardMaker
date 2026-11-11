"""
Standard 0.3" (7.62mm = 3-hole) DIP IC Package definitions: DIP-8, DIP-14, DIP-16, DIP-28.
"""
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QLinearGradient, QPainterPath
)
from PyQt6.QtCore import Qt, QRectF, QPointF
from app.models.component_def import ComponentDef, PinDef, PropertyDef
from app.components.draw_utils import draw_solder_joint, draw_top_pin, draw_unmirrored_text


_DEFAULT_DIP_LABELS = {
    8: ("NE555", ["dip", "dip8", "ic", "555", "lm358", "opamp", "attiny85"]),
    14: ("74HC00", ["dip", "dip14", "ic", "logic", "lm324", "74hc"]),
    16: ("74HC595", ["dip", "dip16", "ic", "shift", "l293d", "uln2003"]),
    28: ("ATmega328P", ["dip", "dip28", "ic", "mcu", "atmega328", "mcp23017"]),
}


class DIPPackageDef(ComponentDef):
    def __init__(self, pin_count: int = 8):
        assert pin_count in (8, 14, 16, 28)
        self.pin_count = pin_count
        self.half = pin_count // 2
        default_lbl, tags = _DEFAULT_DIP_LABELS[pin_count]

        pins: list[PinDef] = []
        # Left column top-to-bottom: Pin 1 .. N/2
        for i in range(self.half):
            pins.append(PinDef(name=str(i + 1), grid_x=0, grid_y=i, description=f"Pin {i + 1}", pin_type="io"))
        # Right column bottom-to-top: Pin N/2+1 .. N
        for i in range(self.half):
            pin_num = self.half + i + 1
            gy = self.half - 1 - i
            pins.append(PinDef(name=str(pin_num), grid_x=3, grid_y=gy, description=f"Pin {pin_num}", pin_type="io"))

        super().__init__(
            type_id=f"dip_{pin_count}",
            name=f"DIP-{pin_count} IC Package",
            category="Semiconductors & ICs",
            default_label=default_lbl,
            description=f"{pin_count}-pin narrow 0.3\" (7.62mm) dual inline IC package.",
            pins=pins,
            properties=[
                PropertyDef(id="label", label="Part Number / Label", type="str", default=default_lbl),
                PropertyDef(id="socket", label="Mounting", type="choice", default="Bare IC",
                            choices=["Bare IC", "In DIP Socket"]),
            ],
            anchor_pin_index=0,
            tags=tags
        )

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        p = pitch_px
        path = QPainterPath()
        path.addRoundedRect(QRectF(-0.42 * p, -0.55 * p, 3.84 * p, (self.half + 0.1) * p), 2.5, 2.5)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        in_socket = instance.custom_props.get("socket", "Bare IC") == "In DIP Socket"

        # Optional plastic DIP socket underneath
        if in_socket:
            sx, sy, sw, sh = -0.35 * p, -0.45 * p, 3.7 * p, (self.half - 0.1) * p
            painter.setBrush(QColor(22, 22, 26))
            painter.setPen(QPen(QColor(55, 55, 62), 0.9))
            painter.drawRoundedRect(QRectF(sx, sy, sw, sh), 1.5, 1.5)

        # Metallic IC leads reaching to grid_x=0 and grid_x=3
        painter.setPen(QPen(QColor(185, 190, 200), 2.3))
        for i in range(self.half):
            py = i * p
            painter.drawLine(QPointF(0, py), QPointF(0.45 * p, py))
            painter.drawLine(QPointF(2.55 * p, py), QPointF(3.0 * p, py))

        # Epoxy IC package body centered between x=0 and x=3
        bx, by = 0.35 * p, -0.42 * p
        bw, bh = 2.3 * p, (self.half - 0.16) * p

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 45))
        painter.drawRoundedRect(QRectF(bx + 1.5, by + 2.0, bw, bh), 2.0, 2.0)

        grad = QLinearGradient(bx, by, bx + bw, by)
        grad.setColorAt(0.0, QColor(48, 48, 54))
        grad.setColorAt(0.5, QColor(32, 32, 36))
        grad.setColorAt(1.0, QColor(22, 22, 26))
        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(QColor(68, 68, 75), 0.9))
        painter.drawRoundedRect(QRectF(bx, by, bw, bh), 2.0, 2.0)

        # Top U-notch indicating Pin 1 end
        notch_r = 0.35 * p
        cx = bx + bw / 2.0
        painter.setBrush(QColor(18, 18, 22))
        painter.setPen(QPen(QColor(75, 75, 82), 0.7))
        painter.drawChord(QRectF(cx - notch_r, by - notch_r, notch_r * 2, notch_r * 2), 180 * 16, 180 * 16)

        # Pin 1 dimple dot
        painter.setBrush(QColor(150, 150, 160))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(bx + 0.38 * p, by + 0.42 * p), max(1.4, p * 0.08), max(1.4, p * 0.08))

        # Vertical part number text along IC spine
        label = instance.label if instance.label else self.default_label
        painter.save()
        painter.translate(cx, by + bh / 2.0)
        painter.rotate(90)
        painter.setFont(QFont("Arial", int(max(5, p * 0.25)), QFont.Weight.Bold))
        painter.setPen(QColor(220, 225, 232))
        painter.drawText(QRectF(-bh / 2.0 + 6, -bw / 2.0, bh - 12, bw), Qt.AlignmentFlag.AlignCenter, label)
        painter.restore()

        # Pins entering perfboard holes
        for pin in self.pins:
            draw_top_pin(painter, pin.grid_x * p, pin.grid_y * p, 2.2)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        bx, by, bw, bh = 0.35 * p, -0.42 * p, 2.3 * p, (self.half - 0.16) * p
        painter.setPen(QPen(QColor(180, 180, 190, 60), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(60, 60, 70, 20))
        painter.drawRoundedRect(QRectF(bx, by, bw, bh), 2.0, 2.0)

        label = instance.label if instance.label else self.default_label
        painter.setFont(QFont("Arial", int(max(5, p * 0.2)), QFont.Weight.Bold))
        painter.setPen(QColor(200, 200, 215, 85))
        draw_unmirrored_text(painter, QRectF(bx, by, bw, bh), Qt.AlignmentFlag.AlignCenter, label)

        for pin in self.pins:
            draw_solder_joint(painter, pin.grid_x * p, pin.grid_y * p, p)
