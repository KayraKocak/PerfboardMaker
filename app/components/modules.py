"""
Power, motor driver, relay, and display module definitions:
- MX1508 Motor Driver Module
- L298N Motor Driver Module
- Mini-360 Buck Converter
- LM2596 Buck Converter Module
- 5V Relay Modules (1-Channel & 2-Channel)
- SRD-05VDC-SL-C Bare Relay Footprint
- 0.96" I2C OLED Display (SSD1306)
"""
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QLinearGradient, QRadialGradient, QPainterPath
)
from PyQt6.QtCore import Qt, QRectF, QPointF
from app.models.component_def import ComponentDef, PinDef, PropertyDef
from app.components.draw_utils import draw_solder_joint, draw_top_pin, draw_unmirrored_text


def _draw_pcb_base(painter: QPainter, rect: QRectF, c1: QColor, c2: QColor, edge: QColor, radius: float = 3.0):
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0, 48))
    painter.drawRoundedRect(rect.translated(2.0, 2.5), radius, radius)

    grad = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.bottom())
    grad.setColorAt(0.0, c1)
    grad.setColorAt(1.0, c2)
    painter.setBrush(QBrush(grad))
    painter.setPen(QPen(edge, 1.0))
    painter.drawRoundedRect(rect, radius, radius)


def _draw_mounting_hole(painter: QPainter, x: float, y: float, r: float):
    painter.setBrush(QColor(215, 175, 70))
    painter.setPen(QPen(QColor(135, 105, 35), 0.7))
    painter.drawEllipse(QPointF(x, y), r, r)
    painter.setBrush(QColor(22, 24, 28))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(QPointF(x, y), r * 0.56, r * 0.56)


class MX1508Def(ComponentDef):
    def __init__(self):
        pins = [
            PinDef(name="IN1", grid_x=0, grid_y=0, description="Motor A In 1", pin_type="io"),
            PinDef(name="IN2", grid_x=1, grid_y=0, description="Motor A In 2", pin_type="io"),
            PinDef(name="IN3", grid_x=2, grid_y=0, description="Motor B In 3", pin_type="io"),
            PinDef(name="IN4", grid_x=3, grid_y=0, description="Motor B In 4", pin_type="io"),
            PinDef(name="VCC", grid_x=5, grid_y=0, description="Motor Supply + (2-10V)", pin_type="power"),
            PinDef(name="GND", grid_x=6, grid_y=0, description="Ground", pin_type="ground"),
            PinDef(name="MA+", grid_x=0, grid_y=7, description="Motor A Out +", pin_type="io"),
            PinDef(name="MA-", grid_x=1, grid_y=7, description="Motor A Out -", pin_type="io"),
            PinDef(name="MB+", grid_x=5, grid_y=7, description="Motor B Out +", pin_type="io"),
            PinDef(name="MB-", grid_x=6, grid_y=7, description="Motor B Out -", pin_type="io"),
        ]
        super().__init__(
            type_id="mx1508",
            name="MX1508 Motor Driver",
            category="Power & Motor Drivers",
            default_label="MX1508",
            description="Dual 1.5A DC/stepper H-bridge motor driver module (~25x21mm).",
            pins=pins,
            properties=[PropertyDef(id="label", label="Label", type="str", default="MX1508")],
            anchor_pin_index=0,
            tags=["mx1508", "motor", "driver", "hbridge", "l298n", "mini", "dc", "stepper"]
        )

    def _rect(self, p: float) -> QRectF:
        return QRectF(-1.1 * p, -0.7 * p, 8.2 * p, 8.4 * p)

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(self._rect(pitch_px), 3.0, 3.0)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        rect = self._rect(p)
        _draw_pcb_base(painter, rect, QColor(175, 28, 32), QColor(125, 16, 20), QColor(210, 55, 55))

        # Dual MX1508 driver SOP-16 ICs
        for ix in (1.3 * p, 4.5 * p):
            painter.setBrush(QColor(24, 24, 28))
            painter.setPen(QPen(QColor(60, 60, 66), 0.7))
            painter.drawRect(QRectF(ix, 2.3 * p, 1.4 * p, 2.4 * p))
            # SMD leads
            painter.setPen(QPen(QColor(200, 205, 212), 1.1))
            for k in range(5):
                ly = (2.5 + k * 0.48) * p
                painter.drawLine(QPointF(ix - 0.25 * p, ly), QPointF(ix, ly))
                painter.drawLine(QPointF(ix + 1.4 * p, ly), QPointF(ix + 1.65 * p, ly))

        # Electrolytic/MLCC capacitor hint
        painter.setBrush(QColor(180, 145, 70))
        painter.setPen(QPen(QColor(120, 90, 40), 0.7))
        painter.drawRect(QRectF(3.15 * p, 2.9 * p, 0.8 * p, 1.2 * p))

        # Label & pin silkscreen
        label = instance.label if instance.label else "MX1508"
        painter.setFont(QFont("Arial", int(max(4, p * 0.24)), QFont.Weight.Bold))
        painter.setPen(QColor(245, 245, 248))
        painter.drawText(QRectF(rect.left(), 5.05 * p, rect.width(), 0.9 * p), Qt.AlignmentFlag.AlignCenter, label)

        painter.setFont(QFont("Arial", int(max(4, p * 0.16)), QFont.Weight.Bold))
        for pin in self.pins:
            ty = (pin.grid_y * p + 0.45 * p) if pin.grid_y == 0 else (pin.grid_y * p - 0.8 * p)
            painter.drawText(QRectF(pin.grid_x * p - 0.45 * p, ty, 0.9 * p, 0.4 * p),
                             Qt.AlignmentFlag.AlignCenter, pin.name)
            draw_top_pin(painter, pin.grid_x * p, pin.grid_y * p, 2.2)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        rect = self._rect(p)
        painter.setPen(QPen(QColor(210, 80, 80, 70), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(150, 30, 35, 20))
        painter.drawRoundedRect(rect, 3.0, 3.0)
        label = instance.label if instance.label else "MX1508"
        painter.setFont(QFont("Arial", int(max(5, p * 0.28)), QFont.Weight.Bold))
        painter.setPen(QColor(220, 180, 180, 90))
        draw_unmirrored_text(painter, rect, Qt.AlignmentFlag.AlignCenter, f"[{label}]")
        for pin in self.pins:
            draw_solder_joint(painter, pin.grid_x * p, pin.grid_y * p, p)


class L298NDef(ComponentDef):
    def __init__(self):
        pins = [
            PinDef(name="ENA", grid_x=0, grid_y=0, description="Channel A PWM Enable", pin_type="io"),
            PinDef(name="IN1", grid_x=1, grid_y=0, description="Channel A In 1", pin_type="io"),
            PinDef(name="IN2", grid_x=2, grid_y=0, description="Channel A In 2", pin_type="io"),
            PinDef(name="IN3", grid_x=3, grid_y=0, description="Channel B In 3", pin_type="io"),
            PinDef(name="IN4", grid_x=4, grid_y=0, description="Channel B In 4", pin_type="io"),
            PinDef(name="ENB", grid_x=5, grid_y=0, description="Channel B PWM Enable", pin_type="io"),
            PinDef(name="12V", grid_x=-4, grid_y=-2, description="Motor Supply + (5–35V)", pin_type="power"),
            PinDef(name="GND", grid_x=-2, grid_y=-2, description="Common Ground", pin_type="ground"),
            PinDef(name="5V", grid_x=0, grid_y=-2, description="5V Logic Power", pin_type="power"),
            PinDef(name="OUT1", grid_x=-6, grid_y=-11, description="Motor A Out 1", pin_type="io"),
            PinDef(name="OUT2", grid_x=-6, grid_y=-9, description="Motor A Out 2", pin_type="io"),
            PinDef(name="OUT3", grid_x=8, grid_y=-11, description="Motor B Out 3", pin_type="io"),
            PinDef(name="OUT4", grid_x=8, grid_y=-9, description="Motor B Out 4", pin_type="io"),
        ]
        super().__init__(
            type_id="l298n",
            name="L298N Motor Driver Module",
            category="Power & Motor Drivers",
            default_label="L298N",
            description="Dual 2A H-bridge L298N module (43x43mm) with heatsink, 5V regulator, and screw terminals.",
            pins=pins,
            properties=[PropertyDef(id="label", label="Label", type="str", default="L298N")],
            anchor_pin_index=0,
            tags=["l298n", "motor", "driver", "hbridge", "dual", "dc", "stepper", "heatsink"]
        )

    def _rect(self, p: float) -> QRectF:
        return QRectF(-7.2 * p, -15.2 * p, 16.4 * p, 16.4 * p)

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(self._rect(pitch_px), 4.0, 4.0)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        rect = self._rect(p)
        _draw_pcb_base(painter, rect, QColor(175, 25, 30), QColor(120, 15, 20), QColor(210, 50, 55), 4.0)

        # 4 corner mounting holes
        for hx, hy in ((rect.left() + 0.9 * p, rect.top() + 0.9 * p),
                       (rect.right() - 0.9 * p, rect.top() + 0.9 * p),
                       (rect.left() + 0.9 * p, rect.bottom() - 0.9 * p),
                       (rect.right() - 0.9 * p, rect.bottom() - 0.9 * p)):
            _draw_mounting_hole(painter, hx, hy, 0.45 * p)

        # Large black finned aluminum heatsink at top-center
        hs_x, hs_y, hs_w, hs_h = -2.8 * p, -14.5 * p, 7.6 * p, 5.8 * p
        painter.setBrush(QColor(22, 24, 28))
        painter.setPen(QPen(QColor(60, 64, 72), 1.0))
        painter.drawRoundedRect(QRectF(hs_x, hs_y, hs_w, hs_h), 1.5, 1.5)
        painter.setPen(QPen(QColor(52, 56, 62), max(1.2, p * 0.08)))
        for fx in range(7):
            x_fin = hs_x + (0.6 + fx * 1.05) * p
            painter.drawLine(QPointF(x_fin, hs_y + 2), QPointF(x_fin, hs_y + hs_h - 2))

        # Filter caps + 78M05 + diodes area
        for cx in (-2.5 * p, 2.8 * p):
            painter.setBrush(QColor(28, 30, 35))
            painter.setPen(QPen(QColor(175, 180, 190), 0.9))
            painter.drawEllipse(QPointF(cx, -5.8 * p), 1.15 * p, 1.15 * p)

        # Blue screw terminal blocks: Left OUT1/2, Bottom 12V/GND/5V, Right OUT3/4
        def _blue_block(rx: float, ry: float, rw: float, rh: float):
            painter.setBrush(QColor(28, 105, 195))
            painter.setPen(QPen(QColor(15, 65, 130), 1.0))
            painter.drawRoundedRect(QRectF(rx, ry, rw, rh), 1.5, 1.5)

        _blue_block(-6.9 * p, -12.1 * p, 2.3 * p, 4.2 * p)
        _blue_block(6.6 * p, -12.1 * p, 2.3 * p, 4.2 * p)
        _blue_block(-5.0 * p, -3.2 * p, 6.0 * p, 2.3 * p)

        # Control header shroud
        painter.setBrush(QColor(22, 22, 26))
        painter.setPen(QPen(QColor(55, 55, 62), 0.8))
        painter.drawRect(QRectF(-0.45 * p, -0.45 * p, 5.9 * p, 0.9 * p))

        # Silkscreen title
        label = instance.label if instance.label else "L298N"
        painter.setFont(QFont("Arial", int(max(5, p * 0.34)), QFont.Weight.Bold))
        painter.setPen(QColor(245, 245, 250))
        painter.drawText(QRectF(-2.0 * p, -8.2 * p, 6.0 * p, 1.4 * p), Qt.AlignmentFlag.AlignCenter, label)

        painter.setFont(QFont("Arial", int(max(4, p * 0.17)), QFont.Weight.Bold))
        painter.setPen(QColor(240, 240, 245, 225))
        for i, nm in enumerate(("ENA", "IN1", "IN2", "IN3", "IN4", "ENB")):
            painter.drawText(QRectF(i * p - 0.48 * p, -1.1 * p, 0.96 * p, 0.55 * p), Qt.AlignmentFlag.AlignCenter, nm)

        for pin in self.pins:
            draw_top_pin(painter, pin.grid_x * p, pin.grid_y * p, 2.3)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        rect = self._rect(p)
        painter.setPen(QPen(QColor(210, 80, 80, 70), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(150, 30, 35, 20))
        painter.drawRoundedRect(rect, 4.0, 4.0)
        label = instance.label if instance.label else "L298N"
        painter.setFont(QFont("Arial", int(max(6, p * 0.4)), QFont.Weight.Bold))
        painter.setPen(QColor(220, 180, 180, 90))
        draw_unmirrored_text(painter, rect, Qt.AlignmentFlag.AlignCenter, f"[{label}]")
        for pin in self.pins:
            draw_solder_joint(painter, pin.grid_x * p, pin.grid_y * p, p)


class Mini360Def(ComponentDef):
    def __init__(self):
        pins = [
            PinDef(name="IN+", grid_x=0, grid_y=0, description="Input + (4.75–23V)", pin_type="power"),
            PinDef(name="IN-", grid_x=0, grid_y=3, description="Input Ground", pin_type="ground"),
            PinDef(name="OUT+", grid_x=5, grid_y=0, description="Regulated Output +", pin_type="power"),
            PinDef(name="OUT-", grid_x=5, grid_y=3, description="Output Ground", pin_type="ground"),
        ]
        super().__init__(
            type_id="mini360",
            name="Mini-360 Buck Converter",
            category="Power & Motor Drivers",
            default_label="Mini-360",
            description="Ultra-compact DC-DC step-down buck converter (~17x11mm, 4 corner pins).",
            pins=pins,
            properties=[PropertyDef(id="label", label="Output / Label", type="str", default="Mini-360")],
            anchor_pin_index=0,
            tags=["mini360", "mini-360", "buck", "stepdown", "converter", "dcdc", "power", "5v", "3.3v"]
        )

    def _rect(self, p: float) -> QRectF:
        return QRectF(-0.8 * p, -0.65 * p, 6.6 * p, 4.3 * p)

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(self._rect(pitch_px), 2.0, 2.0)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        rect = self._rect(p)
        _draw_pcb_base(painter, rect, QColor(28, 125, 62), QColor(18, 88, 42), QColor(50, 165, 90), 2.0)

        # 4R7 SMD Inductor
        painter.setBrush(QColor(52, 54, 60))
        painter.setPen(QPen(QColor(95, 98, 108), 0.8))
        painter.drawRoundedRect(QRectF(1.1 * p, 0.4 * p, 1.85 * p, 1.85 * p), 1.5, 1.5)
        painter.setFont(QFont("Arial", int(max(4, p * 0.2)), QFont.Weight.Bold))
        painter.setPen(QColor(215, 220, 228))
        painter.drawText(QRectF(1.1 * p, 0.4 * p, 1.85 * p, 1.85 * p), Qt.AlignmentFlag.AlignCenter, "4R7")

        # Tiny silver/brass trimmer potentiometer
        painter.setBrush(QColor(210, 215, 222))
        painter.setPen(QPen(QColor(115, 120, 130), 0.7))
        painter.drawRect(QRectF(3.3 * p, 0.5 * p, 1.1 * p, 1.1 * p))
        painter.setBrush(QColor(215, 175, 70))
        painter.drawEllipse(QPointF(3.85 * p, 1.05 * p), 0.35 * p, 0.35 * p)

        label = instance.label if instance.label else "Mini-360"
        painter.setFont(QFont("Arial", int(max(4, p * 0.2)), QFont.Weight.Bold))
        painter.setPen(QColor(240, 245, 240))
        painter.drawText(QRectF(rect.left(), 2.55 * p, rect.width(), 0.9 * p), Qt.AlignmentFlag.AlignCenter, label)

        painter.setFont(QFont("Arial", int(max(4, p * 0.15)), QFont.Weight.Bold))
        for pin in self.pins:
            tx = pin.grid_x * p + (0.3 * p if pin.grid_x == 0 else -1.1 * p)
            painter.drawText(QRectF(tx, pin.grid_y * p - 0.22 * p, 0.8 * p, 0.44 * p),
                             Qt.AlignmentFlag.AlignCenter, pin.name)
            draw_top_pin(painter, pin.grid_x * p, pin.grid_y * p, 2.2)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        rect = self._rect(p)
        painter.setPen(QPen(QColor(120, 210, 150, 70), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(30, 120, 60, 20))
        painter.drawRoundedRect(rect, 2.0, 2.0)
        label = instance.label if instance.label else "Mini-360"
        painter.setFont(QFont("Arial", int(max(4, p * 0.22)), QFont.Weight.Bold))
        painter.setPen(QColor(190, 225, 200, 90))
        draw_unmirrored_text(painter, rect, Qt.AlignmentFlag.AlignCenter, f"[{label}]")
        for pin in self.pins:
            draw_solder_joint(painter, pin.grid_x * p, pin.grid_y * p, p)


class LM2596Def(ComponentDef):
    def __init__(self):
        pins = [
            PinDef(name="IN+", grid_x=0, grid_y=0, description="Input + (4–40V)", pin_type="power"),
            PinDef(name="IN-", grid_x=0, grid_y=6, description="Input Ground", pin_type="ground"),
            PinDef(name="OUT+", grid_x=14, grid_y=0, description="Regulated Output +", pin_type="power"),
            PinDef(name="OUT-", grid_x=14, grid_y=6, description="Output Ground", pin_type="ground"),
        ]
        super().__init__(
            type_id="lm2596",
            name="LM2596 Buck Converter Module",
            category="Power & Motor Drivers",
            default_label="LM2596",
            description="3A DC-DC step-down buck converter module (43x21mm) with multiturn voltage trimmer.",
            pins=pins,
            properties=[PropertyDef(id="label", label="Output / Label", type="str", default="LM2596")],
            anchor_pin_index=0,
            tags=["lm2596", "buck", "stepdown", "converter", "dcdc", "power", "3a", "regulator"]
        )

    def _rect(self, p: float) -> QRectF:
        return QRectF(-1.4 * p, -1.1 * p, 16.8 * p, 8.2 * p)

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(self._rect(pitch_px), 3.0, 3.0)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        rect = self._rect(p)
        _draw_pcb_base(painter, rect, QColor(18, 82, 165), QColor(12, 55, 120), QColor(45, 125, 220), 3.0)

        # Diagonal mounting holes
        _draw_mounting_hole(painter, -0.5 * p, 6.1 * p, 0.48 * p)
        _draw_mounting_hole(painter, 14.5 * p, -0.1 * p, 0.48 * p)

        # Input & Output silver electrolytic caps
        for cx in (2.3 * p, 11.7 * p):
            painter.setBrush(QColor(200, 205, 215))
            painter.setPen(QPen(QColor(95, 100, 110), 1.0))
            painter.drawEllipse(QPointF(cx, 1.3 * p), 1.35 * p, 1.35 * p)
            painter.setBrush(QColor(40, 42, 48))
            painter.drawChord(QRectF(cx - 1.35 * p, 1.3 * p - 1.35 * p, 2.7 * p, 2.7 * p), 220 * 16, 100 * 16)

        # Shielded toroidal/block inductor (330/470)
        painter.setBrush(QColor(45, 48, 54))
        painter.setPen(QPen(QColor(95, 100, 110), 1.0))
        painter.drawRoundedRect(QRectF(7.1 * p, 0.2 * p, 3.1 * p, 3.1 * p), 2.5, 2.5)
        painter.setFont(QFont("Arial", int(max(5, p * 0.28)), QFont.Weight.Bold))
        painter.setPen(QColor(225, 230, 235))
        painter.drawText(QRectF(7.1 * p, 0.2 * p, 3.1 * p, 3.1 * p), Qt.AlignmentFlag.AlignCenter, "330")

        # LM2596 TO-263 IC
        painter.setBrush(QColor(22, 22, 26))
        painter.setPen(QPen(QColor(180, 185, 195), 0.9))
        painter.drawRect(QRectF(4.4 * p, 1.2 * p, 2.1 * p, 2.3 * p))

        # Blue multiturn trimmer pot (3296W)
        painter.setBrush(QColor(25, 110, 205))
        painter.setPen(QPen(QColor(15, 70, 145), 0.9))
        painter.drawRect(QRectF(5.0 * p, 4.5 * p, 2.5 * p, 1.45 * p))
        painter.setBrush(QColor(220, 185, 70))
        painter.drawEllipse(QPointF(5.35 * p, 4.9 * p), 0.28 * p, 0.28 * p)

        label = instance.label if instance.label else "LM2596"
        painter.setFont(QFont("Arial", int(max(5, p * 0.26)), QFont.Weight.Bold))
        painter.setPen(QColor(240, 245, 255))
        painter.drawText(QRectF(8.0 * p, 4.6 * p, 5.0 * p, 1.3 * p), Qt.AlignmentFlag.AlignCenter, label)

        painter.setFont(QFont("Arial", int(max(4, p * 0.18)), QFont.Weight.Bold))
        for pin in self.pins:
            tx = 0.55 * p if pin.grid_x == 0 else 12.1 * p
            painter.drawText(QRectF(tx, pin.grid_y * p - 0.3 * p, 1.3 * p, 0.6 * p),
                             Qt.AlignmentFlag.AlignCenter, pin.name)
            draw_top_pin(painter, pin.grid_x * p, pin.grid_y * p, 2.5)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        rect = self._rect(p)
        painter.setPen(QPen(QColor(110, 175, 240, 70), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(25, 95, 185, 20))
        painter.drawRoundedRect(rect, 3.0, 3.0)
        label = instance.label if instance.label else "LM2596"
        painter.setFont(QFont("Arial", int(max(5, p * 0.32)), QFont.Weight.Bold))
        painter.setPen(QColor(185, 215, 245, 90))
        draw_unmirrored_text(painter, rect, Qt.AlignmentFlag.AlignCenter, f"[{label}]")
        for pin in self.pins:
            draw_solder_joint(painter, pin.grid_x * p, pin.grid_y * p, p, pad_r=6.8)


class RelayModule5VDef(ComponentDef):
    def __init__(self, channels: int = 1):
        self.channels = channels
        if channels == 2:
            pins = [
                PinDef(name="GND", grid_x=0, grid_y=0, description="Ground", pin_type="ground"),
                PinDef(name="IN1", grid_x=0, grid_y=1, description="Relay 1 Trigger", pin_type="io"),
                PinDef(name="IN2", grid_x=0, grid_y=2, description="Relay 2 Trigger", pin_type="io"),
                PinDef(name="VCC", grid_x=0, grid_y=3, description="5V Supply", pin_type="power"),
                PinDef(name="NO1", grid_x=14, grid_y=-4, description="Ch1 Normally Open", pin_type="io"),
                PinDef(name="COM1", grid_x=14, grid_y=-2, description="Ch1 Common", pin_type="io"),
                PinDef(name="NC1", grid_x=14, grid_y=0, description="Ch1 Normally Closed", pin_type="io"),
                PinDef(name="NO2", grid_x=14, grid_y=3, description="Ch2 Normally Open", pin_type="io"),
                PinDef(name="COM2", grid_x=14, grid_y=5, description="Ch2 Common", pin_type="io"),
                PinDef(name="NC2", grid_x=14, grid_y=7, description="Ch2 Normally Closed", pin_type="io"),
            ]
            name = "5V Relay Module (2-Channel)"
            type_id = "relay_module_5v_2ch"
            desc = "2-channel opto-isolated 5V relay module (~50x39mm) with screw terminals."
        else:
            pins = [
                PinDef(name="VCC", grid_x=0, grid_y=0, description="5V Supply", pin_type="power"),
                PinDef(name="GND", grid_x=0, grid_y=1, description="Ground", pin_type="ground"),
                PinDef(name="IN", grid_x=0, grid_y=2, description="Relay Trigger Input", pin_type="io"),
                PinDef(name="NO", grid_x=12, grid_y=-1, description="Normally Open", pin_type="io"),
                PinDef(name="COM", grid_x=12, grid_y=1, description="Common", pin_type="io"),
                PinDef(name="NC", grid_x=12, grid_y=3, description="Normally Closed", pin_type="io"),
            ]
            name = "5V Relay Module (1-Channel)"
            type_id = "relay_module_5v_1ch"
            desc = "1-channel opto-isolated 5V relay module (~43x18mm) with Songle relay & screw terminals."

        super().__init__(
            type_id=type_id,
            name=name,
            category="Power & Motor Drivers",
            default_label=f"RLY{channels}",
            description=desc,
            pins=pins,
            properties=[PropertyDef(id="label", label="Label", type="str", default=f"RLY{channels}")],
            anchor_pin_index=0,
            tags=["relay", "5v", "module", "songle", f"{channels}ch", "switch", "ac", "opto"]
        )

    def _rect(self, p: float) -> QRectF:
        if self.channels == 2:
            return QRectF(-1.5 * p, -6.2 * p, 17.5 * p, 15.2 * p)
        return QRectF(-1.4 * p, -2.6 * p, 15.4 * p, 7.2 * p)

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(self._rect(pitch_px), 3.0, 3.0)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        rect = self._rect(p)
        _draw_pcb_base(painter, rect, QColor(18, 80, 155), QColor(12, 52, 110), QColor(45, 120, 210), 3.0)

        # Mounting holes
        for hx, hy in ((rect.left() + 0.7 * p, rect.top() + 0.7 * p),
                       (rect.right() - 0.7 * p, rect.top() + 0.7 * p),
                       (rect.left() + 0.7 * p, rect.bottom() - 0.7 * p),
                       (rect.right() - 0.7 * p, rect.bottom() - 0.7 * p)):
            _draw_mounting_hole(painter, hx, hy, 0.42 * p)

        # Songle blue relay cube(s)
        relay_ys = [-4.6 * p, 2.2 * p] if self.channels == 2 else [-1.9 * p]
        rx = 4.6 * p
        rw, rh = 6.8 * p, 5.6 * p
        for ry in relay_ys:
            painter.setBrush(QColor(22, 130, 225))
            painter.setPen(QPen(QColor(14, 85, 160), 1.0))
            painter.drawRoundedRect(QRectF(rx, ry, rw, rh), 1.5, 1.5)
            painter.setFont(QFont("Arial", int(max(4, p * 0.19)), QFont.Weight.Bold))
            painter.setPen(QColor(240, 248, 255))
            painter.drawText(QRectF(rx, ry, rw, rh), Qt.AlignmentFlag.AlignCenter, "SRD-05VDC")

        # Green screw terminal block(s) on right
        if self.channels == 2:
            for ty in (-4.9 * p, 2.1 * p):
                painter.setBrush(QColor(40, 155, 70))
                painter.setPen(QPen(QColor(22, 100, 42), 1.0))
                painter.drawRect(QRectF(12.9 * p, ty, 2.2 * p, 5.8 * p))
        else:
            painter.setBrush(QColor(40, 155, 70))
            painter.setPen(QPen(QColor(22, 100, 42), 1.0))
            painter.drawRect(QRectF(11.1 * p, -1.9 * p, 2.2 * p, 5.8 * p))

        # Control header block on left
        ctrl_n = 4 if self.channels == 2 else 3
        painter.setBrush(QColor(22, 22, 26))
        painter.setPen(QPen(QColor(55, 55, 62), 0.8))
        painter.drawRect(QRectF(-0.45 * p, -0.45 * p, 0.9 * p, (ctrl_n - 0.1) * p))

        # Optocouplers
        for k in range(self.channels):
            oy = (-2.0 + k * 4.0) * p if self.channels == 2 else 0.2 * p
            painter.setBrush(QColor(24, 24, 28))
            painter.setPen(QPen(QColor(65, 65, 72), 0.7))
            painter.drawRect(QRectF(2.2 * p, oy, 1.2 * p, 1.6 * p))

        painter.setFont(QFont("Arial", int(max(4, p * 0.17)), QFont.Weight.Bold))
        painter.setPen(QColor(240, 245, 255))
        for pin in self.pins:
            if pin.grid_x == 0:
                painter.drawText(QRectF(0.5 * p, pin.grid_y * p - 0.3 * p, 1.5 * p, 0.6 * p),
                                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, pin.name)
            draw_top_pin(painter, pin.grid_x * p, pin.grid_y * p, 2.2)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        rect = self._rect(p)
        painter.setPen(QPen(QColor(110, 175, 240, 70), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(25, 95, 185, 20))
        painter.drawRoundedRect(rect, 3.0, 3.0)
        label = instance.label if instance.label else self.default_label
        painter.setFont(QFont("Arial", int(max(5, p * 0.3)), QFont.Weight.Bold))
        painter.setPen(QColor(185, 215, 245, 90))
        draw_unmirrored_text(painter, rect, Qt.AlignmentFlag.AlignCenter, f"[{label}]")
        for pin in self.pins:
            draw_solder_joint(painter, pin.grid_x * p, pin.grid_y * p, p)


class SRD05VDCRelayDef(ComponentDef):
    def __init__(self):
        pins = [
            PinDef(name="COIL1", grid_x=0, grid_y=0, description="Relay Coil 1 (5V)", pin_type="io"),
            PinDef(name="COIL2", grid_x=0, grid_y=5, description="Relay Coil 2", pin_type="io"),
            PinDef(name="COM", grid_x=-1, grid_y=2, description="Switch Common", pin_type="io"),
            PinDef(name="NC", grid_x=5, grid_y=0, description="Normally Closed", pin_type="io"),
            PinDef(name="NO", grid_x=5, grid_y=5, description="Normally Open", pin_type="io"),
        ]
        super().__init__(
            type_id="relay_srd_05vdc",
            name="SRD-05VDC-SL-C Relay (Bare)",
            category="Power & Motor Drivers",
            default_label="K1",
            description="Bare Songle SRD-05VDC-SL-C 5-pin SPDT sugar-cube PCB relay footprint.",
            pins=pins,
            properties=[PropertyDef(id="label", label="Designator", type="str", default="K1")],
            anchor_pin_index=0,
            tags=["relay", "srd", "05vdc", "songle", "spdt", "bare", "footprint", "5pin"]
        )

    def _rect(self, p: float) -> QRectF:
        return QRectF(-1.55 * p, -0.55 * p, 7.5 * p, 6.1 * p)

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(self._rect(pitch_px), 2.0, 2.0)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        rect = self._rect(p)
        _draw_pcb_base(painter, rect, QColor(32, 145, 240), QColor(18, 95, 175), QColor(14, 70, 135), 2.0)

        label = instance.label if instance.label else "K1"
        painter.setFont(QFont("Arial", int(max(5, p * 0.28)), QFont.Weight.Bold))
        painter.setPen(QColor(245, 250, 255))
        painter.drawText(QRectF(rect.left(), rect.top() + 1.0 * p, rect.width(), 1.3 * p),
                         Qt.AlignmentFlag.AlignCenter, f"SONGLE ({label})")

        painter.setFont(QFont("Arial", int(max(4, p * 0.22)), QFont.Weight.Normal))
        painter.setPen(QColor(225, 240, 255, 220))
        painter.drawText(QRectF(rect.left(), rect.top() + 2.3 * p, rect.width(), 1.2 * p),
                         Qt.AlignmentFlag.AlignCenter, "SRD-05VDC-SL-C")
        painter.drawText(QRectF(rect.left(), rect.top() + 3.4 * p, rect.width(), 1.0 * p),
                         Qt.AlignmentFlag.AlignCenter, "10A 250VAC")

        # Tiny SPDT schematic symbol at bottom right
        painter.setPen(QPen(QColor(235, 245, 255, 190), 1.0))
        painter.drawLine(QPointF(1.2 * p, 4.9 * p), QPointF(2.2 * p, 4.9 * p))
        painter.drawLine(QPointF(2.2 * p, 4.9 * p), QPointF(3.3 * p, 4.4 * p))

        for pin in self.pins:
            draw_top_pin(painter, pin.grid_x * p, pin.grid_y * p, 2.2)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        rect = self._rect(p)
        painter.setPen(QPen(QColor(110, 190, 245, 70), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(30, 135, 225, 22))
        painter.drawRoundedRect(rect, 2.0, 2.0)

        # Coil/switch pin hints
        painter.setFont(QFont("Arial", int(max(4, p * 0.16)), QFont.Weight.Bold))
        painter.setPen(QColor(210, 235, 255, 140))
        for pin in self.pins:
            draw_unmirrored_text(
                painter,
                QRectF(pin.grid_x * p - 0.55 * p, pin.grid_y * p - 0.7 * p, 1.1 * p, 0.45 * p),
                Qt.AlignmentFlag.AlignCenter,
                pin.name,
            )
            draw_solder_joint(painter, pin.grid_x * p, pin.grid_y * p, p, pad_r=6.4)


class OLED096I2CDef(ComponentDef):
    def __init__(self):
        pins = [
            PinDef(name="GND", grid_x=0, grid_y=0, description="Ground", pin_type="ground"),
            PinDef(name="VCC", grid_x=1, grid_y=0, description="3.3V / 5V Supply", pin_type="power"),
            PinDef(name="SCL", grid_x=2, grid_y=0, description="I2C Clock", pin_type="io"),
            PinDef(name="SDA", grid_x=3, grid_y=0, description="I2C Data", pin_type="io"),
        ]
        super().__init__(
            type_id="oled_096_i2c",
            name="OLED Display 0.96\" (I2C)",
            category="Power & Motor Drivers",
            default_label="OLED",
            description="0.96-inch 128x64 SSD1306 I2C OLED display module (4-pin 2.54mm header).",
            pins=pins,
            properties=[PropertyDef(id="label", label="Label", type="str", default="OLED")],
            anchor_pin_index=0,
            tags=["oled", "ssd1306", "display", "screen", "i2c", "0.96"]
        )

    def _rect(self, p: float) -> QRectF:
        return QRectF(-3.8 * p, -0.7 * p, 10.6 * p, 10.8 * p)

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(self._rect(pitch_px), 3.0, 3.0)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        rect = self._rect(p)
        _draw_pcb_base(painter, rect, QColor(20, 75, 155), QColor(14, 52, 115), QColor(45, 115, 205), 3.0)

        for hx, hy in ((rect.left() + 0.7 * p, rect.top() + 0.7 * p),
                       (rect.right() - 0.7 * p, rect.top() + 0.7 * p),
                       (rect.left() + 0.7 * p, rect.bottom() - 0.7 * p),
                       (rect.right() - 0.7 * p, rect.bottom() - 0.7 * p)):
            _draw_mounting_hole(painter, hx, hy, 0.42 * p)

        # Active glass panel + dark bezel
        glass = QRectF(rect.left() + 0.6 * p, 1.3 * p, rect.width() - 1.2 * p, 7.2 * p)
        painter.setBrush(QColor(15, 16, 20))
        painter.setPen(QPen(QColor(55, 60, 70), 1.0))
        painter.drawRoundedRect(glass, 2.0, 2.0)

        active = glass.adjusted(0.45 * p, 0.7 * p, -0.45 * p, -1.0 * p)
        painter.setBrush(QColor(8, 12, 18))
        painter.setPen(QPen(QColor(35, 50, 75), 0.7))
        painter.drawRect(active)

        label = instance.label if instance.label else "OLED"
        painter.setFont(QFont("Arial", int(max(5, p * 0.34)), QFont.Weight.Bold))
        painter.setPen(QColor(95, 210, 255))
        painter.drawText(active, Qt.AlignmentFlag.AlignCenter, label)

        painter.setFont(QFont("Arial", int(max(4, p * 0.16)), QFont.Weight.Bold))
        painter.setPen(QColor(235, 240, 248))
        for pin in self.pins:
            painter.drawText(QRectF(pin.grid_x * p - 0.45 * p, 0.35 * p, 0.9 * p, 0.55 * p),
                             Qt.AlignmentFlag.AlignCenter, pin.name)
            draw_top_pin(painter, pin.grid_x * p, pin.grid_y * p, 2.2)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        rect = self._rect(p)
        painter.setPen(QPen(QColor(110, 175, 240, 70), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(20, 75, 155, 20))
        painter.drawRoundedRect(rect, 3.0, 3.0)
        label = instance.label if instance.label else "OLED"
        painter.setFont(QFont("Arial", int(max(5, p * 0.3)), QFont.Weight.Bold))
        painter.setPen(QColor(185, 215, 245, 90))
        draw_unmirrored_text(painter, rect, Qt.AlignmentFlag.AlignCenter, f"[{label}]")
        for pin in self.pins:
            draw_solder_joint(painter, pin.grid_x * p, pin.grid_y * p, p)
