"""
Switches and potentiometers:
- Breadboard Trimmer Potentiometer (Triangle & Inline 2.54mm footprints)
- 16mm Rotary Potentiometer (5.08mm pin spacing)
- Slide Switch (SPDT, 2.54mm spacing)
- Tactile Push Button (12x12mm, 12.7x5.08mm spacing)
"""
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QLinearGradient, QRadialGradient, QPainterPath
)
from PyQt6.QtCore import Qt, QRectF, QPointF
from app.models.component_def import ComponentDef, PinDef, PropertyDef
from app.components.draw_utils import draw_solder_joint, draw_top_pin, draw_unmirrored_text


class TrimmerPotDef(ComponentDef):
    def __init__(self):
        super().__init__(
            type_id="pot_trimmer",
            name="Trimmer Potentiometer",
            category="Passives & Switches",
            default_label="10k",
            description="Breadboard/perfboard trimmer potentiometer (Triangle or Inline 2.54mm footprint).",
            pins=[
                PinDef(name="1", grid_x=0, grid_y=0, description="End Terminal 1 (CCW)", pin_type="passive"),
                PinDef(name="2", grid_x=1, grid_y=-1, description="Wiper", pin_type="passive"),
                PinDef(name="3", grid_x=2, grid_y=0, description="End Terminal 3 (CW)", pin_type="passive"),
            ],
            properties=[
                PropertyDef(id="label", label="Value", type="str", default="10k"),
                PropertyDef(id="footprint", label="Pin Layout", type="choice", default="Triangle (2.54mm)",
                            choices=["Triangle (2.54mm)", "Inline (2.54mm)"]),
                PropertyDef(id="color", label="Body Color", type="choice", default="Blue",
                            choices=["Blue", "Orange"]),
            ],
            anchor_pin_index=0,
            tags=["potentiometer", "trimmer", "trim", "pot", "3362", "rm065", "variable"]
        )

    def _is_inline(self, instance) -> bool:
        return "Inline" in str(instance.custom_props.get("footprint", ""))

    def get_pins_for_instance(self, instance) -> list[PinDef]:
        wy = 0 if self._is_inline(instance) else -1
        return [
            PinDef(name="1", grid_x=0, grid_y=0, description="End Terminal 1 (CCW)", pin_type="passive"),
            PinDef(name="2", grid_x=1, grid_y=wy, description="Wiper", pin_type="passive"),
            PinDef(name="3", grid_x=2, grid_y=0, description="End Terminal 3 (CW)", pin_type="passive"),
        ]

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        p = pitch_px
        path = QPainterPath()
        if self._is_inline(instance):
            path.addRoundedRect(QRectF(-0.4 * p, -1.2 * p, 2.8 * p, 2.2 * p), 2.5, 2.5)
        else:
            path.addRoundedRect(QRectF(-0.45 * p, -1.7 * p, 2.9 * p, 2.4 * p), 2.5, 2.5)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        inline = self._is_inline(instance)
        bx = -0.4 * p
        bw = 2.8 * p
        bh = 2.1 * p if inline else 2.3 * p
        by = -1.1 * p if inline else -1.65 * p
        cx = 1.0 * p
        cy = by + bh / 2.0

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 42))
        painter.drawRoundedRect(QRectF(bx + 1.5, by + 2.0, bw, bh), 2.5, 2.5)

        is_orange = instance.custom_props.get("color", "Blue") == "Orange"
        c1, c2 = (QColor(235, 130, 45), QColor(185, 85, 20)) if is_orange else (QColor(45, 125, 215), QColor(22, 80, 155))
        grad = QLinearGradient(bx, by, bx + bw, by + bh)
        grad.setColorAt(0.0, c1)
        grad.setColorAt(1.0, c2)
        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(c2.darker(140), 1.0))
        painter.drawRoundedRect(QRectF(bx, by, bw, bh), 2.5, 2.5)

        # Rotary screw rotor wheel
        dial_r = 0.72 * p
        painter.setBrush(QColor(235, 240, 245))
        painter.setPen(QPen(QColor(110, 120, 135), 0.9))
        painter.drawEllipse(QPointF(cx, cy), dial_r, dial_r)

        # Cross screwdriver slot
        painter.setPen(QPen(QColor(80, 85, 95), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(cx - dial_r * 0.55, cy), QPointF(cx + dial_r * 0.55, cy))
        painter.drawLine(QPointF(cx, cy - dial_r * 0.55), QPointF(cx, cy + dial_r * 0.55))

        label = instance.label if instance.label else "10k"
        painter.setFont(QFont("Arial", int(max(4, p * 0.19)), QFont.Weight.Bold))
        painter.setPen(QColor(245, 245, 250))
        painter.drawText(QRectF(bx, by + bh - 0.5 * p, bw, 0.5 * p), Qt.AlignmentFlag.AlignCenter, label)

        for pin in self.get_pins_for_instance(instance):
            draw_top_pin(painter, pin.grid_x * p, pin.grid_y * p, 2.2)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        inline = self._is_inline(instance)
        bx, bw = -0.4 * p, 2.8 * p
        bh = 2.1 * p if inline else 2.3 * p
        by = -1.1 * p if inline else -1.65 * p
        painter.setPen(QPen(QColor(180, 180, 190, 60), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(45, 125, 215, 20))
        painter.drawRoundedRect(QRectF(bx, by, bw, bh), 2.5, 2.5)
        for pin in self.get_pins_for_instance(instance):
            draw_solder_joint(painter, pin.grid_x * p, pin.grid_y * p, p)


class RotaryPot16mmDef(ComponentDef):
    def __init__(self):
        super().__init__(
            type_id="pot_rotary_16mm",
            name="Rotary Potentiometer (16mm)",
            category="Passives & Switches",
            default_label="B10K",
            description="Standard 16mm panel/PCB-mount rotary potentiometer (5.08mm pin pitch).",
            pins=[
                PinDef(name="1", grid_x=0, grid_y=0, description="Terminal 1 (CCW)", pin_type="passive"),
                PinDef(name="2", grid_x=2, grid_y=0, description="Wiper", pin_type="passive"),
                PinDef(name="3", grid_x=4, grid_y=0, description="Terminal 3 (CW)", pin_type="passive"),
            ],
            properties=[
                PropertyDef(id="label", label="Value", type="str", default="B10K"),
            ],
            anchor_pin_index=0,
            tags=["potentiometer", "rotary", "16mm", "knob", "volume", "b10k"]
        )

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        p = pitch_px
        cx = 2.0 * p
        cy = -3.4 * p
        r = 3.25 * p
        path = QPainterPath()
        path.addEllipse(QPointF(cx, cy), r, r)
        path.addRoundedRect(QRectF(-0.55 * p, -1.8 * p, 5.1 * p, 2.3 * p), 2.5, 2.5)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        cx = 2.0 * p
        cy = -3.4 * p
        r = 3.15 * p

        # Terminal wafer block
        painter.setPen(QPen(QColor(95, 65, 35), 1.0))
        painter.setBrush(QColor(150, 105, 55))
        painter.drawRoundedRect(QRectF(-0.45 * p, -1.6 * p, 4.9 * p, 1.3 * p), 1.5, 1.5)

        # Metal leads to pin holes
        painter.setPen(QPen(QColor(185, 190, 200), 2.6))
        for px in (0, 2, 4):
            painter.drawLine(QPointF(px * p, -0.35 * p), QPointF(px * p, 0))

        # Shadow
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 48))
        painter.drawEllipse(QPointF(cx + 2, cy + 2.5), r, r)

        # Brushed aluminum 16mm body
        body_grad = QRadialGradient(cx - r * 0.3, cy - r * 0.3, r * 1.25)
        body_grad.setColorAt(0.0, QColor(225, 230, 236))
        body_grad.setColorAt(0.7, QColor(175, 180, 190))
        body_grad.setColorAt(1.0, QColor(120, 125, 135))
        painter.setBrush(QBrush(body_grad))
        painter.setPen(QPen(QColor(90, 95, 105), 1.2))
        painter.drawEllipse(QPointF(cx, cy), r, r)

        # Threaded bushing ring
        bush_r = 1.65 * p
        painter.setBrush(QColor(200, 175, 100))
        painter.setPen(QPen(QColor(135, 115, 55), 1.0))
        painter.drawEllipse(QPointF(cx, cy), bush_r, bush_r)

        # Knurled shaft
        shaft_r = 1.15 * p
        s_grad = QRadialGradient(cx - shaft_r * 0.3, cy - shaft_r * 0.3, shaft_r * 1.2)
        s_grad.setColorAt(0.0, QColor(245, 248, 252))
        s_grad.setColorAt(1.0, QColor(145, 150, 160))
        painter.setBrush(QBrush(s_grad))
        painter.setPen(QPen(QColor(95, 100, 110), 1.0))
        painter.drawEllipse(QPointF(cx, cy), shaft_r, shaft_r)

        # Shaft slot indicator
        painter.setPen(QPen(QColor(55, 60, 65), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(cx, cy - shaft_r * 0.7), QPointF(cx, cy + shaft_r * 0.7))

        # Silkscreen label
        label = instance.label if instance.label else "B10K"
        painter.setFont(QFont("Arial", int(max(5, p * 0.25)), QFont.Weight.Bold))
        painter.setPen(QColor(35, 38, 42))
        painter.drawText(QRectF(cx - r * 0.8, cy + bush_r + 1, r * 1.6, 0.8 * p),
                         Qt.AlignmentFlag.AlignCenter, label)

        for px in (0, 2, 4):
            draw_top_pin(painter, px * p, 0, 2.5)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        cx, cy, r = 2.0 * p, -3.4 * p, 3.15 * p
        painter.setPen(QPen(QColor(180, 180, 190, 60), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(150, 155, 165, 20))
        painter.drawEllipse(QPointF(cx, cy), r, r)
        painter.drawRoundedRect(QRectF(-0.45 * p, -1.6 * p, 4.9 * p, 1.3 * p), 1.5, 1.5)

        label = instance.label if instance.label else "B10K"
        painter.setFont(QFont("Arial", int(max(5, p * 0.25)), QFont.Weight.Bold))
        painter.setPen(QColor(200, 200, 215, 90))
        draw_unmirrored_text(painter, QRectF(cx - r, cy - 0.5 * p, r * 2, p), Qt.AlignmentFlag.AlignCenter, label)

        for px in (0, 2, 4):
            draw_solder_joint(painter, px * p, 0, p)


class SlideSwitchSPDTDef(ComponentDef):
    def __init__(self):
        super().__init__(
            type_id="slide_switch_spdt",
            name="Slide Switch (SPDT)",
            category="Passives & Switches",
            default_label="SW",
            description="Miniature 3-pin SPDT slide switch (SS-12F15, 2.54mm pin spacing).",
            pins=[
                PinDef(name="1", grid_x=0, grid_y=0, description="Throw 1", pin_type="passive"),
                PinDef(name="COM", grid_x=1, grid_y=0, description="Common", pin_type="passive"),
                PinDef(name="2", grid_x=2, grid_y=0, description="Throw 2", pin_type="passive"),
            ],
            properties=[
                PropertyDef(id="label", label="Label", type="str", default="SW"),
                PropertyDef(id="state", label="Slider Position", type="choice", default="Position 1",
                            choices=["Position 1", "Position 2"]),
            ],
            anchor_pin_index=0,
            tags=["switch", "slide", "spdt", "toggle", "power"]
        )

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        p = pitch_px
        path = QPainterPath()
        path.addRoundedRect(QRectF(-0.8 * p, -0.75 * p, 3.6 * p, 1.5 * p), 2.0, 2.0)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        bx, by, bw, bh = -0.75 * p, -0.7 * p, 3.5 * p, 1.4 * p

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 42))
        painter.drawRoundedRect(QRectF(bx + 1.5, by + 2.0, bw, bh), 2.0, 2.0)

        # Brushed steel housing
        grad = QLinearGradient(bx, by, bx, by + bh)
        grad.setColorAt(0.0, QColor(220, 225, 230))
        grad.setColorAt(0.5, QColor(180, 185, 195))
        grad.setColorAt(1.0, QColor(140, 145, 155))
        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(QColor(95, 100, 110), 1.0))
        painter.drawRoundedRect(QRectF(bx, by, bw, bh), 2.0, 2.0)

        # Black inner slide slot
        slot_x, slot_y, slot_w, slot_h = bx + 0.5 * p, by + 0.3 * p, bw - 1.0 * p, bh - 0.6 * p
        painter.setBrush(QColor(18, 18, 22))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(slot_x, slot_y, slot_w, slot_h), 1.0, 1.0)

        # Sliding black actuator nub
        pos2 = "2" in str(instance.custom_props.get("state", "Position 1"))
        knob_w = slot_w * 0.45
        knob_x = (slot_x + slot_w - knob_w) if pos2 else slot_x
        painter.setBrush(QColor(50, 52, 58))
        painter.setPen(QPen(QColor(80, 82, 90), 0.8))
        painter.drawRoundedRect(QRectF(knob_x, slot_y - 1.0, knob_w, slot_h + 2.0), 1.0, 1.0)

        # Label above
        label = instance.label if instance.label else "SW"
        painter.setFont(QFont("Arial", int(max(4, p * 0.2)), QFont.Weight.Bold))
        painter.setPen(QColor(240, 240, 245, 210))
        painter.drawText(QRectF(bx, by - 0.55 * p, bw, 0.5 * p), Qt.AlignmentFlag.AlignCenter, label)

        for px in (0, 1, 2):
            draw_top_pin(painter, px * p, 0, 2.2)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        bx, by, bw, bh = -0.75 * p, -0.7 * p, 3.5 * p, 1.4 * p
        painter.setPen(QPen(QColor(180, 180, 190, 60), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(160, 165, 175, 20))
        painter.drawRoundedRect(QRectF(bx, by, bw, bh), 2.0, 2.0)
        for px in (0, 1, 2):
            draw_solder_joint(painter, px * p, 0, p)


class TactileButton12x12Def(ComponentDef):
    def __init__(self):
        pins = [
            PinDef(name="1", grid_x=0, grid_y=0, description="Terminal 1A", pin_type="passive"),
            PinDef(name="2", grid_x=0, grid_y=2, description="Terminal 1B (tied to 1)", pin_type="passive"),
            PinDef(name="3", grid_x=5, grid_y=0, description="Terminal 2A", pin_type="passive"),
            PinDef(name="4", grid_x=5, grid_y=2, description="Terminal 2B (tied to 3)", pin_type="passive"),
        ]
        super().__init__(
            type_id="push_button_12x12",
            name="Tactile Button (12x12mm)",
            category="Passives & Switches",
            default_label="SW2",
            description="Large 12x12mm 4-pin tactile push button (12.7x5.08mm perfboard spacing).",
            pins=pins,
            properties=[
                PropertyDef(id="label", label="Label", type="str", default="SW2"),
                PropertyDef(id="color", label="Cap Color", type="choice", default="Black",
                            choices=["Black", "Red", "Blue", "Yellow", "Green"]),
            ],
            anchor_pin_index=0,
            tags=["switch", "button", "tactile", "12x12", "momentary"]
        )

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        p = pitch_px
        path = QPainterPath()
        path.addRoundedRect(QRectF(-0.35 * p, -1.45 * p, 5.7 * p, 4.9 * p), 3.0, 3.0)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        cx, cy = 2.5 * p, 1.0 * p
        bw, bh = 4.7 * p, 4.7 * p
        bx, by = cx - bw / 2.0, cy - bh / 2.0

        # Leads extending to holes (0,0), (0,2), (5,0), (5,2)
        painter.setPen(QPen(QColor(170, 175, 185), 2.5))
        for px, py in ((0, 0), (0, 2 * p), (5 * p, 0), (5 * p, 2 * p)):
            painter.drawLine(QPointF(px, py), QPointF(cx, py))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 45))
        painter.drawRoundedRect(QRectF(bx + 2, by + 2.5, bw, bh), 3.0, 3.0)

        # Black plastic housing + silver face plate
        painter.setBrush(QColor(35, 35, 40))
        painter.setPen(QPen(QColor(20, 20, 25), 1.0))
        painter.drawRoundedRect(QRectF(bx, by, bw, bh), 3.0, 3.0)

        plate_m = 0.25 * p
        plate_grad = QLinearGradient(bx, by, bx + bw, by + bh)
        plate_grad.setColorAt(0.0, QColor(225, 230, 235))
        plate_grad.setColorAt(0.5, QColor(190, 195, 200))
        plate_grad.setColorAt(1.0, QColor(155, 160, 168))
        painter.setBrush(QBrush(plate_grad))
        painter.setPen(QPen(QColor(115, 120, 128), 0.9))
        painter.drawRoundedRect(QRectF(bx + plate_m, by + plate_m, bw - 2 * plate_m, bh - 2 * plate_m), 2.5, 2.5)

        # Corner rivets
        painter.setBrush(QColor(125, 130, 138))
        painter.setPen(Qt.PenStyle.NoPen)
        off = 0.55 * p
        for rx, ry in ((bx + off, by + off), (bx + bw - off, by + off),
                       (bx + off, by + bh - off), (bx + bw - off, by + bh - off)):
            painter.drawEllipse(QPointF(rx, ry), 2.0, 2.0)

        # Round actuator cap
        color_name = instance.custom_props.get("color", "Black")
        color_map = {
            "Black": (QColor(48, 48, 54), QColor(22, 22, 26)),
            "Red": (QColor(230, 60, 50), QColor(160, 30, 20)),
            "Blue": (QColor(50, 130, 230), QColor(20, 80, 170)),
            "Yellow": (QColor(240, 200, 40), QColor(190, 150, 20)),
            "Green": (QColor(50, 190, 80), QColor(20, 130, 45)),
        }
        c1, c2 = color_map.get(color_name, color_map["Black"])
        btn_r = 1.45 * p
        btn_grad = QRadialGradient(cx - btn_r * 0.3, cy - btn_r * 0.3, btn_r * 1.1)
        btn_grad.setColorAt(0.0, c1)
        btn_grad.setColorAt(1.0, c2)
        painter.setBrush(QBrush(btn_grad))
        painter.setPen(QPen(QColor(25, 25, 28), 1.0))
        painter.drawEllipse(QPointF(cx, cy), btn_r, btn_r)

        label = instance.label if instance.label else "SW2"
        painter.setFont(QFont("Arial", int(max(5, p * 0.28)), QFont.Weight.Bold))
        painter.setPen(QColor(240, 240, 245) if color_name == "Black" else QColor(25, 25, 25))
        painter.drawText(QRectF(cx - btn_r, cy - btn_r, btn_r * 2, btn_r * 2), Qt.AlignmentFlag.AlignCenter, label)

        for px, py in ((0, 0), (0, 2 * p), (5 * p, 0), (5 * p, 2 * p)):
            draw_top_pin(painter, px, py, 2.5)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        cx, cy = 2.5 * p, 1.0 * p
        bw, bh = 4.7 * p, 4.7 * p
        painter.setPen(QPen(QColor(160, 165, 175, 65), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(160, 165, 175, 20))
        painter.drawRoundedRect(QRectF(cx - bw / 2.0, cy - bh / 2.0, bw, bh), 3.0, 3.0)

        painter.setPen(QPen(QColor(100, 200, 255, 55), 1.5, Qt.PenStyle.DotLine))
        painter.drawLine(QPointF(0, 0), QPointF(0, 2 * p))
        painter.drawLine(QPointF(5 * p, 0), QPointF(5 * p, 2 * p))

        for px, py in ((0, 0), (0, 2 * p), (5 * p, 0), (5 * p, 2 * p)):
            draw_solder_joint(painter, px, py, p)
