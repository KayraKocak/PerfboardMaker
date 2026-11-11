"""
Connector and header components:
- Pin Header 1xN (Male / Female)
- Pin Header 2xN (Male / Female)
- Screw Terminals (2.54mm / 5.08mm pitch)
- DC Barrel Jack (PCB-mount)
- JST-XH Connectors (2-pin / 3-pin)
"""
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QLinearGradient, QPainterPath
)
from PyQt6.QtCore import Qt, QRectF, QPointF
from app.models.component_def import ComponentDef, PinDef, PropertyDef
from app.components.draw_utils import draw_solder_joint, draw_top_pin, draw_unmirrored_text


def _clamp_int(val, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(val)))
    except (TypeError, ValueError):
        return default


def _draw_header_cell(painter: QPainter, x: float, y: float, p: float, is_female: bool):
    """Draws a single 2.54mm square plastic header unit at (x, y)."""
    s = 0.94 * p
    painter.setBrush(QColor(28, 28, 32))
    painter.setPen(QPen(QColor(58, 58, 66), 0.7))
    painter.drawRect(QRectF(x - s / 2.0, y - s / 2.0, s, s))

    if is_female:
        # Recessed dark square socket + brass inner contact hint
        sock = 0.44 * p
        painter.setBrush(QColor(10, 10, 12))
        painter.setPen(QPen(QColor(70, 70, 78), 0.6))
        painter.drawRect(QRectF(x - sock / 2.0, y - sock / 2.0, sock, sock))
        painter.setBrush(QColor(175, 145, 55))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(QRectF(x - sock * 0.22, y - sock * 0.22, sock * 0.44, sock * 0.44))
    else:
        # Chamfered gold square male header pin
        ps = 0.34 * p
        painter.setBrush(QColor(228, 192, 72))
        painter.setPen(QPen(QColor(135, 105, 30), 0.7))
        painter.drawRect(QRectF(x - ps / 2.0, y - ps / 2.0, ps, ps))
        painter.setBrush(QColor(255, 240, 160))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(QRectF(x - ps * 0.2, y - ps * 0.2, ps * 0.4, ps * 0.4))


class PinHeader1xDef(ComponentDef):
    def __init__(self):
        super().__init__(
            type_id="pin_header_1x",
            name="Pin Header (1xN)",
            category="Connectors & Headers",
            default_label="J1",
            description="Single-row 2.54mm pin header (configurable 1–20 pins, Male or Female).",
            pins=[
                PinDef(name=str(i + 1), grid_x=i, grid_y=0, description=f"Pin {i + 1}", pin_type="io")
                for i in range(4)
            ],
            properties=[
                PropertyDef(id="label", label="Designator", type="str", default="J1"),
                PropertyDef(id="pin_count", label="Pins (N)", type="int", default=4, choices=[1, 20]),
                PropertyDef(id="gender", label="Gender", type="choice", default="Male", choices=["Male", "Female"]),
            ],
            anchor_pin_index=0,
            tags=["header", "pin", "1xn", "male", "female", "dupont", "jumper", "connector"]
        )

    def _count(self, instance) -> int:
        return _clamp_int(instance.custom_props.get("pin_count", 4), 1, 20, 4)

    def get_pins_for_instance(self, instance) -> list[PinDef]:
        n = self._count(instance)
        return [
            PinDef(name=str(i + 1), grid_x=i, grid_y=0, description=f"Pin {i + 1}", pin_type="io")
            for i in range(n)
        ]

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        p = pitch_px
        n = self._count(instance)
        path = QPainterPath()
        path.addRoundedRect(QRectF(-0.5 * p, -0.5 * p, n * p, 1.0 * p), 1.5, 1.5)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        n = self._count(instance)
        is_female = instance.custom_props.get("gender", "Male") == "Female"

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 40))
        painter.drawRoundedRect(QRectF(-0.47 * p + 1.5, -0.47 * p + 2.0, n * p - 0.06 * p, 0.94 * p), 1.5, 1.5)

        for i in range(n):
            _draw_header_cell(painter, i * p, 0.0, p, is_female)

        label = instance.label if instance.label else "J1"
        painter.setFont(QFont("Arial", int(max(4, p * 0.2)), QFont.Weight.Bold))
        painter.setPen(QColor(235, 240, 245, 220))
        painter.drawText(QRectF(-0.45 * p, -1.0 * p, max(n * p, 1.5 * p), 0.5 * p),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        n = self._count(instance)
        painter.setPen(QPen(QColor(180, 180, 190, 60), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(40, 40, 45, 25))
        painter.drawRect(QRectF(-0.47 * p, -0.47 * p, n * p - 0.06 * p, 0.94 * p))
        for i in range(n):
            draw_solder_joint(painter, i * p, 0, p)


class PinHeader2xDef(ComponentDef):
    def __init__(self):
        pins = []
        idx = 1
        for i in range(4):
            pins.append(PinDef(name=str(idx), grid_x=i, grid_y=0, description=f"Pin {idx}", pin_type="io"))
            pins.append(PinDef(name=str(idx + 1), grid_x=i, grid_y=1, description=f"Pin {idx + 1}", pin_type="io"))
            idx += 2

        super().__init__(
            type_id="pin_header_2x",
            name="Pin Header (2xN)",
            category="Connectors & Headers",
            default_label="J2",
            description="Dual-row 2.54mm pin header (configurable 2x1 to 2x12 pins, Male or Female).",
            pins=pins,
            properties=[
                PropertyDef(id="label", label="Designator", type="str", default="J2"),
                PropertyDef(id="pairs", label="Pin Pairs (N)", type="int", default=4, choices=[1, 12]),
                PropertyDef(id="gender", label="Gender", type="choice", default="Male", choices=["Male", "Female"]),
            ],
            anchor_pin_index=0,
            tags=["header", "pin", "2xn", "icsp", "spi", "male", "female", "connector"]
        )

    def _pairs(self, instance) -> int:
        return _clamp_int(instance.custom_props.get("pairs", 4), 1, 12, 4)

    def get_pins_for_instance(self, instance) -> list[PinDef]:
        n = self._pairs(instance)
        pins = []
        idx = 1
        for i in range(n):
            pins.append(PinDef(name=str(idx), grid_x=i, grid_y=0, description=f"Pin {idx}", pin_type="io"))
            pins.append(PinDef(name=str(idx + 1), grid_x=i, grid_y=1, description=f"Pin {idx + 1}", pin_type="io"))
            idx += 2
        return pins

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        p = pitch_px
        n = self._pairs(instance)
        path = QPainterPath()
        path.addRoundedRect(QRectF(-0.5 * p, -0.5 * p, n * p, 2.0 * p), 1.5, 1.5)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        n = self._pairs(instance)
        is_female = instance.custom_props.get("gender", "Male") == "Female"

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 42))
        painter.drawRoundedRect(QRectF(-0.47 * p + 1.5, -0.47 * p + 2.0, n * p - 0.06 * p, 1.94 * p), 1.5, 1.5)

        for i in range(n):
            _draw_header_cell(painter, i * p, 0.0, p, is_female)
            _draw_header_cell(painter, i * p, p, p, is_female)

        label = instance.label if instance.label else "J2"
        painter.setFont(QFont("Arial", int(max(4, p * 0.2)), QFont.Weight.Bold))
        painter.setPen(QColor(235, 240, 245, 220))
        painter.drawText(QRectF(-0.45 * p, -1.0 * p, max(n * p, 1.5 * p), 0.5 * p),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        n = self._pairs(instance)
        painter.setPen(QPen(QColor(180, 180, 190, 60), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(40, 40, 45, 25))
        painter.drawRect(QRectF(-0.47 * p, -0.47 * p, n * p - 0.06 * p, 1.94 * p))
        for pin in self.get_pins_for_instance(instance):
            draw_solder_joint(painter, pin.grid_x * p, pin.grid_y * p, p)


class ScrewTerminalDef(ComponentDef):
    def __init__(self, pitch_holes: int = 2):
        self.pitch_holes = pitch_holes
        pitch_mm = "5.08mm" if pitch_holes == 2 else "2.54mm"
        default_pins = 2 if pitch_holes == 2 else 3
        super().__init__(
            type_id=f"screw_terminal_{'508' if pitch_holes == 2 else '254'}",
            name=f"Screw Terminal ({pitch_mm})",
            category="Connectors & Headers",
            default_label="TB1",
            description=f"KF-series PCB screw terminal block ({pitch_mm} pitch, configurable 2–8 pins).",
            pins=[
                PinDef(name=str(i + 1), grid_x=i * pitch_holes, grid_y=0, description=f"Terminal {i + 1}", pin_type="io")
                for i in range(default_pins)
            ],
            properties=[
                PropertyDef(id="label", label="Designator", type="str", default="TB1"),
                PropertyDef(id="pin_count", label="Terminals", type="int", default=default_pins, choices=[2, 8]),
                PropertyDef(id="color", label="Housing Color", type="choice", default="Green",
                            choices=["Green", "Blue", "Black"]),
            ],
            anchor_pin_index=0,
            tags=["terminal", "screw", "block", "kf301", "kf128", pitch_mm, "connector", "power"]
        )

    def _count(self, instance) -> int:
        default = 2 if self.pitch_holes == 2 else 3
        return _clamp_int(instance.custom_props.get("pin_count", default), 2, 8, default)

    def get_pins_for_instance(self, instance) -> list[PinDef]:
        n = self._count(instance)
        return [
            PinDef(name=str(i + 1), grid_x=i * self.pitch_holes, grid_y=0,
                   description=f"Terminal {i + 1}", pin_type="io")
            for i in range(n)
        ]

    def _box(self, instance, pitch_px: float) -> QRectF:
        p = pitch_px
        n = self._count(instance)
        step = self.pitch_holes * p
        bw = n * step + 0.25 * p
        bh = (3.0 if self.pitch_holes == 2 else 2.4) * p
        bx = -0.5 * step - 0.125 * p
        by = -bh / 2.0
        return QRectF(bx, by, bw, bh)

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(self._box(instance, pitch_px), 2.5, 2.5)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        n = self._count(instance)
        step = self.pitch_holes * p
        rect = self._box(instance, p)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 45))
        painter.drawRoundedRect(rect.translated(1.5, 2.5), 2.5, 2.5)

        col_name = instance.custom_props.get("color", "Green")
        if col_name == "Blue":
            c1, c2 = QColor(40, 125, 215), QColor(22, 80, 155)
        elif col_name == "Black":
            c1, c2 = QColor(52, 54, 60), QColor(28, 30, 34)
        else:
            c1, c2 = QColor(45, 165, 75), QColor(25, 115, 48)

        grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        grad.setColorAt(0.0, c1)
        grad.setColorAt(1.0, c2)
        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(c2.darker(140), 1.0))
        painter.drawRoundedRect(rect, 2.5, 2.5)

        # Wire entry ports along bottom side (+y edge)
        port_h = 0.65 * p
        for i in range(n):
            cx = i * step
            port_w = step * 0.68
            painter.setBrush(QColor(18, 20, 22))
            painter.setPen(QPen(c2.darker(150), 0.7))
            painter.drawRect(QRectF(cx - port_w / 2.0, rect.bottom() - port_h - 1.5, port_w, port_h))

            # Brass screw head on top
            scr_r = (0.58 if self.pitch_holes == 2 else 0.34) * p
            scr_cy = -0.15 * p
            s_grad = QLinearGradient(cx - scr_r, scr_cy - scr_r, cx + scr_r, scr_cy + scr_r)
            s_grad.setColorAt(0.0, QColor(240, 242, 246))
            s_grad.setColorAt(1.0, QColor(155, 160, 170))
            painter.setBrush(QBrush(s_grad))
            painter.setPen(QPen(QColor(70, 75, 82), 0.8))
            painter.drawEllipse(QPointF(cx, scr_cy), scr_r, scr_r)

            # Diagonal Phillips/slotted recess
            painter.setPen(QPen(QColor(60, 62, 68), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(cx - scr_r * 0.55, scr_cy - scr_r * 0.35),
                             QPointF(cx + scr_r * 0.55, scr_cy + scr_r * 0.35))

        label = instance.label if instance.label else "TB1"
        painter.setFont(QFont("Arial", int(max(4, p * 0.2)), QFont.Weight.Bold))
        painter.setPen(QColor(245, 245, 250))
        painter.drawText(QRectF(rect.left(), rect.top() + 1, rect.width(), 0.55 * p),
                         Qt.AlignmentFlag.AlignCenter, label)

        for i in range(n):
            draw_top_pin(painter, i * step, 0, 2.2)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        rect = self._box(instance, p)
        painter.setPen(QPen(QColor(180, 180, 190, 60), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(45, 150, 75, 20))
        painter.drawRoundedRect(rect, 2.5, 2.5)
        for pin in self.get_pins_for_instance(instance):
            draw_solder_joint(painter, pin.grid_x * p, pin.grid_y * p, p)


class DCBarrelJackDef(ComponentDef):
    def __init__(self):
        # Standard DC-005 perfboard mapping: VCC center pin (0,0), GND sleeve (0,3), Shunt Switch (2,2)
        pins = [
            PinDef(name="VCC+", grid_x=0, grid_y=0, description="Center Pin (+)", pin_type="power"),
            PinDef(name="GND-", grid_x=0, grid_y=3, description="Outer Sleeve (-)", pin_type="ground"),
            PinDef(name="SW", grid_x=2, grid_y=2, description="Internal Shunt Switch", pin_type="io"),
        ]
        super().__init__(
            type_id="dc_barrel_jack",
            name="DC Barrel Jack (5.5x2.1mm)",
            category="Connectors & Headers",
            default_label="DC1",
            description="PCB-mount DC-005 barrel power jack (VCC+ rear, GND- center, SW shunt).",
            pins=pins,
            properties=[
                PropertyDef(id="label", label="Designator", type="str", default="DC1"),
            ],
            anchor_pin_index=0,
            tags=["dc", "barrel", "jack", "power", "5.5", "2.1", "dc005", "adapter"]
        )

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        p = pitch_px
        path = QPainterPath()
        path.addRoundedRect(QRectF(-1.75 * p, -0.7 * p, 4.2 * p, 5.7 * p), 2.5, 2.5)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        bx, by, bw, bh = -1.75 * p, -0.6 * p, 3.5 * p, 5.5 * p

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 48))
        painter.drawRoundedRect(QRectF(bx + 2, by + 2.5, bw, bh), 2.5, 2.5)

        # Black molded plastic housing
        grad = QLinearGradient(bx, by, bx + bw, by)
        grad.setColorAt(0.0, QColor(42, 42, 48))
        grad.setColorAt(0.5, QColor(28, 28, 32))
        grad.setColorAt(1.0, QColor(18, 18, 22))
        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(QColor(65, 65, 72), 1.0))
        painter.drawRoundedRect(QRectF(bx, by, bw, bh), 2.0, 2.0)

        # Front cylindrical barrel collar extending to bottom (+y)
        cyl_w = 3.1 * p
        cyl_h = 1.6 * p
        cyl_x = -cyl_w / 2.0
        cyl_y = by + bh - cyl_h * 0.7
        painter.setBrush(QColor(34, 34, 38))
        painter.setPen(QPen(QColor(60, 60, 66), 0.9))
        painter.drawRect(QRectF(cyl_x, cyl_y, cyl_w, cyl_h))

        # Silver contact tabs protruding to holes
        painter.setBrush(QColor(195, 200, 208))
        painter.setPen(QPen(QColor(110, 115, 125), 0.7))
        painter.drawRect(QRectF(-0.35 * p, -0.2 * p, 0.7 * p, 0.4 * p))
        painter.drawRect(QRectF(1.7 * p, 1.8 * p, 0.55 * p, 0.45 * p))

        # Label & polarity silkscreen
        label = instance.label if instance.label else "DC1"
        painter.setFont(QFont("Arial", int(max(5, p * 0.25)), QFont.Weight.Bold))
        painter.setPen(QColor(235, 235, 242))
        painter.drawText(QRectF(bx, by + 0.9 * p, bw, 1.2 * p), Qt.AlignmentFlag.AlignCenter, label)

        painter.setFont(QFont("Arial", int(max(4, p * 0.18)), QFont.Weight.Bold))
        painter.setPen(QColor(255, 120, 110))
        painter.drawText(QRectF(-1.4 * p, -0.4 * p, 0.8 * p, 0.8 * p), Qt.AlignmentFlag.AlignCenter, "+")

        draw_top_pin(painter, 0, 0, 2.5)
        draw_top_pin(painter, 0, 3 * p, 2.5)
        draw_top_pin(painter, 2 * p, 2 * p, 2.5)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        bx, by, bw, bh = -1.75 * p, -0.6 * p, 3.5 * p, 5.5 * p
        painter.setPen(QPen(QColor(180, 180, 190, 60), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(40, 40, 45, 25))
        painter.drawRoundedRect(QRectF(bx, by, bw, bh), 2.0, 2.0)

        label = instance.label if instance.label else "DC1"
        painter.setFont(QFont("Arial", int(max(5, p * 0.22)), QFont.Weight.Bold))
        painter.setPen(QColor(200, 200, 215, 90))
        draw_unmirrored_text(painter, QRectF(bx, by + 1.0 * p, bw, 1.2 * p), Qt.AlignmentFlag.AlignCenter, label)

        draw_solder_joint(painter, 0, 0, p, pad_r=6.8)
        draw_solder_joint(painter, 0, 3 * p, p, pad_r=6.8)
        draw_solder_joint(painter, 2 * p, 2 * p, p, pad_r=6.8)


class JSTXHDef(ComponentDef):
    def __init__(self, initial_pins: int = 2):
        self.initial_pins = initial_pins
        super().__init__(
            type_id=f"jst_xh_{initial_pins}p",
            name=f"JST-XH Connector ({initial_pins}-pin)",
            category="Connectors & Headers",
            default_label="JST1",
            description=f"{initial_pins}-pin shrouded JST-XH white PCB connector (2.54mm perfboard compatible).",
            pins=[
                PinDef(name=str(i + 1), grid_x=i, grid_y=0, description=f"Pin {i + 1}", pin_type="io")
                for i in range(initial_pins)
            ],
            properties=[
                PropertyDef(id="label", label="Designator", type="str", default="JST1"),
                PropertyDef(id="pin_count", label="Pins", type="int", default=initial_pins, choices=[2, 6]),
            ],
            anchor_pin_index=0,
            tags=["jst", "xh", "connector", "wire", "battery", f"{initial_pins}pin"]
        )

    def _count(self, instance) -> int:
        return _clamp_int(instance.custom_props.get("pin_count", self.initial_pins), 2, 6, self.initial_pins)

    def get_pins_for_instance(self, instance) -> list[PinDef]:
        n = self._count(instance)
        return [
            PinDef(name=str(i + 1), grid_x=i, grid_y=0, description=f"Pin {i + 1}", pin_type="io")
            for i in range(n)
        ]

    def _box(self, instance, pitch_px: float) -> QRectF:
        p = pitch_px
        n = self._count(instance)
        bw = (n + 0.95) * p
        bh = 2.25 * p
        return QRectF(-0.975 * p, -1.125 * p, bw, bh)

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(self._box(instance, pitch_px), 2.0, 2.0)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        n = self._count(instance)
        rect = self._box(instance, p)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 40))
        painter.drawRoundedRect(rect.translated(1.5, 2.0), 2.0, 2.0)

        # Cream-white nylon shrouded housing
        grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        grad.setColorAt(0.0, QColor(248, 245, 236))
        grad.setColorAt(1.0, QColor(220, 215, 202))
        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(QColor(160, 155, 145), 1.0))
        painter.drawRoundedRect(rect, 2.0, 2.0)

        # Inner recessed cavity
        inner = rect.adjusted(0.28 * p, 0.28 * p, -0.28 * p, -0.28 * p)
        painter.setBrush(QColor(195, 190, 178))
        painter.setPen(QPen(QColor(150, 145, 135), 0.7))
        painter.drawRoundedRect(inner, 1.2, 1.2)

        # Polarization keying notches along top wall
        painter.setBrush(QColor(245, 242, 232))
        painter.drawRect(QRectF(inner.left() + 0.2 * p, rect.top(), 0.45 * p, 0.38 * p))
        painter.drawRect(QRectF(inner.right() - 0.65 * p, rect.top(), 0.45 * p, 0.38 * p))

        # Silver/tin square contact pins inside cavity
        ps = 0.26 * p
        for i in range(n):
            cx = i * p
            painter.setBrush(QColor(225, 230, 238))
            painter.setPen(QPen(QColor(115, 120, 128), 0.6))
            painter.drawRect(QRectF(cx - ps / 2.0, -ps / 2.0, ps, ps))

        label = instance.label if instance.label else "JST1"
        painter.setFont(QFont("Arial", int(max(4, p * 0.19)), QFont.Weight.Bold))
        painter.setPen(QColor(70, 68, 62))
        painter.drawText(QRectF(rect.left(), rect.bottom() - 0.55 * p, rect.width(), 0.48 * p),
                         Qt.AlignmentFlag.AlignCenter, label)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        rect = self._box(instance, p)
        painter.setPen(QPen(QColor(220, 215, 202, 70), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(220, 215, 202, 20))
        painter.drawRoundedRect(rect, 2.0, 2.0)
        for pin in self.get_pins_for_instance(instance):
            draw_solder_joint(painter, pin.grid_x * p, pin.grid_y * p, p)
