"""
Passive and optoelectronic axial/radial components:
- 1/4W Axial Resistor (with dynamic EIA 4-band color decoding & configurable hole span)
- Ceramic Capacitor (2.54mm / 5.08mm pitch)
- Axial Diode (1N4007 / 1N4148 / 1N5819)
- LED (3mm / 5mm with selectable colors)
- HC-49S Crystal Oscillator & 12mm Piezo Buzzer
"""
import re
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QLinearGradient, QRadialGradient, QPainterPath
)
from PyQt6.QtCore import Qt, QRectF, QPointF
from app.models.component_def import ComponentDef, PinDef, PropertyDef
from app.components.draw_utils import draw_solder_joint, draw_top_pin, draw_unmirrored_text

_EIA_COLORS = {
    0: QColor(20, 20, 22),       # Black
    1: QColor(125, 65, 25),      # Brown
    2: QColor(210, 35, 35),      # Red
    3: QColor(235, 120, 20),     # Orange
    4: QColor(235, 210, 35),     # Yellow
    5: QColor(45, 155, 60),      # Green
    6: QColor(35, 100, 205),     # Blue
    7: QColor(140, 55, 175),     # Violet
    8: QColor(135, 140, 145),    # Grey
    9: QColor(240, 240, 240),    # White
    -1: QColor(205, 165, 50),    # Gold
    -2: QColor(190, 195, 205),   # Silver
}


def _decode_resistor_bands(label: str) -> tuple[QColor, QColor, QColor, QColor]:
    """Parses resistance text like '10k', '4k7', '220', '1M' into 4 EIA band colors."""
    default = (_EIA_COLORS[1], _EIA_COLORS[0], _EIA_COLORS[3], _EIA_COLORS[-1])  # 10k 5%
    if not label:
        return default
    s = label.strip().upper().replace("OHM", "").replace("Ω", "").replace(" ", "")
    m = re.fullmatch(r"(\d+)(?:\.(\d+))?([RKMG])?", s)
    if not m:
        # Handle 4K7, 2R2, 1M5 shorthand
        m2 = re.fullmatch(r"(\d+)([RKMG])(\d+)", s)
        if not m2:
            return default
        whole, unit, frac = m2.groups()
        num_str = f"{whole}.{frac}"
    else:
        whole, frac, unit = m.groups()
        num_str = f"{whole}.{frac}" if frac else whole

    try:
        val = float(num_str)
    except ValueError:
        return default

    mult_map = {None: 1.0, "R": 1.0, "K": 1e3, "M": 1e6, "G": 1e9}
    val *= mult_map.get(unit, 1.0)
    if val <= 0:
        return (_EIA_COLORS[0], _EIA_COLORS[0], _EIA_COLORS[0], _EIA_COLORS[-1])

    exp = 0
    while val >= 100.0 and exp < 9:
        val /= 10.0
        exp += 1
    while val < 10.0 and exp > -2:
        val *= 10.0
        exp -= 1

    sig = max(10, min(99, int(round(val))))
    d1, d2 = sig // 10, sig % 10
    return (
        _EIA_COLORS.get(d1, _EIA_COLORS[1]),
        _EIA_COLORS.get(d2, _EIA_COLORS[0]),
        _EIA_COLORS.get(exp, _EIA_COLORS[0]),
        _EIA_COLORS[-1],
    )


def _clamp_int(val, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(val)))
    except (TypeError, ValueError):
        return default


class ResistorDef(ComponentDef):
    def __init__(self):
        super().__init__(
            type_id="resistor_1_4w",
            name="Resistor (Axial 1/4W)",
            category="Passives & Switches",
            default_label="10k",
            description="Standard 1/4W axial carbon/metal-film resistor with automatic color bands.",
            pins=[
                PinDef(name="1", grid_x=0, grid_y=0, description="Lead 1", pin_type="passive"),
                PinDef(name="2", grid_x=4, grid_y=0, description="Lead 2", pin_type="passive"),
            ],
            properties=[
                PropertyDef(id="label", label="Resistance", type="str", default="10k"),
                PropertyDef(id="span", label="Hole Span", type="int", default=4, choices=[3, 8]),
                PropertyDef(id="body_type", label="Package", type="choice", default="Tan (Carbon Film)",
                            choices=["Tan (Carbon Film)", "Blue (Metal Film)"]),
            ],
            anchor_pin_index=0,
            tags=["resistor", "axial", "1/4w", "passive", "ohm"]
        )

    def get_pins_for_instance(self, instance) -> list[PinDef]:
        span = _clamp_int(instance.custom_props.get("span", 4), 3, 8, 4)
        return [
            PinDef(name="1", grid_x=0, grid_y=0, description="Lead 1", pin_type="passive"),
            PinDef(name="2", grid_x=span, grid_y=0, description="Lead 2", pin_type="passive"),
        ]

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        p = pitch_px
        span = _clamp_int(instance.custom_props.get("span", 4), 3, 8, 4)
        bw = 2.4 * p
        bh = 0.9 * p
        cx = (span * p) / 2.0
        path = QPainterPath()
        path.addRoundedRect(QRectF(cx - bw / 2.0, -bh / 2.0, bw, bh), bh * 0.35, bh * 0.35)
        pad_r = 0.45 * p
        path.addEllipse(QPointF(0, 0), pad_r, pad_r)
        path.addEllipse(QPointF(span * p, 0), pad_r, pad_r)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        span = _clamp_int(instance.custom_props.get("span", 4), 3, 8, 4)
        cx = (span * p) / 2.0
        bw = 2.3 * p
        bh = 0.85 * p
        bx = cx - bw / 2.0
        by = -bh / 2.0

        # Axial wire leads
        painter.setPen(QPen(QColor(190, 195, 205), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(0, 0), QPointF(span * p, 0))

        # Shadow
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 40))
        painter.drawRoundedRect(QRectF(bx + 1.5, by + 2.0, bw, bh), bh * 0.35, bh * 0.35)

        is_blue = instance.custom_props.get("body_type", "Tan (Carbon Film)") == "Blue (Metal Film)"
        c_top = QColor(110, 185, 240) if is_blue else QColor(235, 205, 145)
        c_mid = QColor(55, 130, 200) if is_blue else QColor(210, 175, 110)
        c_bot = QColor(30, 85, 145) if is_blue else QColor(160, 125, 70)

        grad = QLinearGradient(bx, by, bx, by + bh)
        grad.setColorAt(0.0, c_top)
        grad.setColorAt(0.45, c_mid)
        grad.setColorAt(1.0, c_bot)

        body_path = QPainterPath()
        body_path.addRoundedRect(QRectF(bx, by, bw, bh), bh * 0.35, bh * 0.35)
        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(c_bot.darker(140), 0.9))
        painter.drawPath(body_path)

        # Color bands clipped inside body
        label = instance.label if instance.label else self.default_label
        bands = _decode_resistor_bands(label)
        painter.save()
        painter.setClipPath(body_path)
        band_w = bw * 0.085
        positions = [0.22, 0.38, 0.54, 0.78]
        for pos, col in zip(positions, bands):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(col)
            painter.drawRect(QRectF(bx + bw * pos - band_w / 2.0, by, band_w, bh))
        painter.restore()

        # Value silkscreen subtle label above
        font = QFont("Arial", int(max(5, p * 0.22)), QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(245, 245, 245, 220))
        painter.drawText(QRectF(bx - 6, by - p * 0.55, bw + 12, p * 0.5),
                         Qt.AlignmentFlag.AlignCenter, label)

        draw_top_pin(painter, 0, 0, 2.3)
        draw_top_pin(painter, span * p, 0, 2.3)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        span = _clamp_int(instance.custom_props.get("span", 4), 3, 8, 4)
        cx = (span * p) / 2.0
        bw = 2.3 * p
        bh = 0.85 * p
        painter.setPen(QPen(QColor(180, 180, 190, 65), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(210, 175, 110, 20))
        painter.drawRoundedRect(QRectF(cx - bw / 2.0, -bh / 2.0, bw, bh), bh * 0.35, bh * 0.35)

        label = instance.label if instance.label else self.default_label
        painter.setFont(QFont("Arial", int(max(5, p * 0.2)), QFont.Weight.Bold))
        painter.setPen(QColor(200, 200, 210, 90))
        draw_unmirrored_text(painter, QRectF(cx - bw / 2.0, -bh / 2.0, bw, bh), Qt.AlignmentFlag.AlignCenter, label)

        draw_solder_joint(painter, 0, 0, p)
        draw_solder_joint(painter, span * p, 0, p)


class CeramicCapacitorDef(ComponentDef):
    def __init__(self):
        super().__init__(
            type_id="ceramic_cap",
            name="Ceramic Capacitor (2.54mm)",
            category="Passives & Switches",
            default_label="100nF",
            description="Multilayer/disc ceramic capacitor (non-polarized, 2.54mm or 5.08mm pitch).",
            pins=[
                PinDef(name="1", grid_x=0, grid_y=0, description="Lead 1", pin_type="passive"),
                PinDef(name="2", grid_x=1, grid_y=0, description="Lead 2", pin_type="passive"),
            ],
            properties=[
                PropertyDef(id="label", label="Value", type="str", default="100nF"),
                PropertyDef(id="pitch_holes", label="Lead Pitch", type="choice", default="2.54mm (1 hole)",
                            choices=["2.54mm (1 hole)", "5.08mm (2 holes)"]),
                PropertyDef(id="color", label="Body Color", type="choice", default="Yellow (MLCC)",
                            choices=["Yellow (MLCC)", "Tan (Disc)", "Blue (High-V)"]),
            ],
            anchor_pin_index=0,
            tags=["capacitor", "ceramic", "104", "100nf", "22pf", "decoupling"]
        )

    def _pitch_h(self, instance) -> int:
        return 2 if "5.08" in str(instance.custom_props.get("pitch_holes", "")) else 1

    def get_pins_for_instance(self, instance) -> list[PinDef]:
        ph = self._pitch_h(instance)
        return [
            PinDef(name="1", grid_x=0, grid_y=0, description="Lead 1", pin_type="passive"),
            PinDef(name="2", grid_x=ph, grid_y=0, description="Lead 2", pin_type="passive"),
        ]

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        p = pitch_px
        ph = self._pitch_h(instance)
        cx = (ph * p) / 2.0
        bw = (1.35 if ph == 1 else 2.2) * p
        bh = 0.72 * p
        path = QPainterPath()
        path.addRoundedRect(QRectF(cx - bw / 2.0, -bh / 2.0, bw, bh), bh * 0.45, bh * 0.45)
        pad_r = 0.45 * p
        path.addEllipse(QPointF(0, 0), pad_r, pad_r)
        path.addEllipse(QPointF(ph * p, 0), pad_r, pad_r)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        ph = self._pitch_h(instance)
        cx = (ph * p) / 2.0
        bw = (1.3 if ph == 1 else 2.15) * p
        bh = 0.68 * p
        bx = cx - bw / 2.0
        by = -bh / 2.0

        painter.setPen(QPen(QColor(185, 190, 200), 2.0))
        painter.drawLine(QPointF(0, 0), QPointF(ph * p, 0))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 40))
        painter.drawRoundedRect(QRectF(bx + 1.5, by + 2.0, bw, bh), bh * 0.45, bh * 0.45)

        col_name = instance.custom_props.get("color", "Yellow (MLCC)")
        if "Blue" in col_name:
            c1, c2 = QColor(65, 145, 235), QColor(30, 85, 165)
            txt_col = QColor(245, 245, 255)
        elif "Tan" in col_name:
            c1, c2 = QColor(225, 160, 85), QColor(175, 110, 45)
            txt_col = QColor(35, 25, 15)
        else:
            c1, c2 = QColor(245, 205, 65), QColor(195, 150, 25)
            txt_col = QColor(45, 35, 10)

        grad = QLinearGradient(bx, by, bx, by + bh)
        grad.setColorAt(0.0, c1)
        grad.setColorAt(1.0, c2)
        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(c2.darker(140), 0.9))
        painter.drawRoundedRect(QRectF(bx, by, bw, bh), bh * 0.45, bh * 0.45)

        label = instance.label if instance.label else self.default_label
        painter.setFont(QFont("Arial", int(max(4, p * 0.19)), QFont.Weight.Bold))
        painter.setPen(txt_col)
        painter.drawText(QRectF(bx, by, bw, bh), Qt.AlignmentFlag.AlignCenter, label)

        draw_top_pin(painter, 0, 0, 2.2)
        draw_top_pin(painter, ph * p, 0, 2.2)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        ph = self._pitch_h(instance)
        cx = (ph * p) / 2.0
        bw = (1.3 if ph == 1 else 2.15) * p
        bh = 0.68 * p
        painter.setPen(QPen(QColor(180, 180, 190, 60), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(235, 200, 60, 20))
        painter.drawRoundedRect(QRectF(cx - bw / 2.0, -bh / 2.0, bw, bh), bh * 0.45, bh * 0.45)

        draw_solder_joint(painter, 0, 0, p)
        draw_solder_joint(painter, ph * p, 0, p)


class DiodeAxialDef(ComponentDef):
    def __init__(self):
        super().__init__(
            type_id="diode_axial",
            name="Diode (Axial)",
            category="Passives & Switches",
            default_label="1N4007",
            description="Polarized axial silicon/Schottky diode (Pin 1: Anode, Pin 2: Cathode band).",
            pins=[
                PinDef(name="A", grid_x=0, grid_y=0, description="Anode (+)", pin_type="passive"),
                PinDef(name="K", grid_x=4, grid_y=0, description="Cathode (-)", pin_type="passive"),
            ],
            properties=[
                PropertyDef(id="label", label="Part Number", type="str", default="1N4007"),
                PropertyDef(id="style", label="Package", type="choice", default="1N4007 (Epoxy Black)",
                            choices=["1N4007 (Epoxy Black)", "1N4148 (Glass Orange)", "1N5819 (Schottky)"]),
                PropertyDef(id="span", label="Hole Span", type="int", default=4, choices=[3, 8]),
            ],
            anchor_pin_index=0,
            tags=["diode", "1n4007", "1n4148", "1n5819", "rectifier", "schottky", "axial"]
        )

    def get_pins_for_instance(self, instance) -> list[PinDef]:
        span = _clamp_int(instance.custom_props.get("span", 4), 3, 8, 4)
        return [
            PinDef(name="A", grid_x=0, grid_y=0, description="Anode (+)", pin_type="passive"),
            PinDef(name="K", grid_x=span, grid_y=0, description="Cathode (-)", pin_type="passive"),
        ]

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        p = pitch_px
        span = _clamp_int(instance.custom_props.get("span", 4), 3, 8, 4)
        cx = (span * p) / 2.0
        bw = 2.3 * p
        bh = 1.0 * p
        path = QPainterPath()
        path.addRoundedRect(QRectF(cx - bw / 2.0, -bh / 2.0, bw, bh), 2.5, 2.5)
        pad_r = 0.45 * p
        path.addEllipse(QPointF(0, 0), pad_r, pad_r)
        path.addEllipse(QPointF(span * p, 0), pad_r, pad_r)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        span = _clamp_int(instance.custom_props.get("span", 4), 3, 8, 4)
        cx = (span * p) / 2.0
        style = instance.custom_props.get("style", "1N4007 (Epoxy Black)")
        is_glass = "1N4148" in style
        bw = (1.8 if is_glass else 2.2) * p
        bh = (0.72 if is_glass else 0.95) * p
        bx = cx - bw / 2.0
        by = -bh / 2.0

        painter.setPen(QPen(QColor(195, 200, 210), 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(0, 0), QPointF(span * p, 0))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 42))
        painter.drawRoundedRect(QRectF(bx + 1.5, by + 2.0, bw, bh), 2.5, 2.5)

        if is_glass:
            grad = QLinearGradient(bx, by, bx, by + bh)
            grad.setColorAt(0.0, QColor(255, 150, 75))
            grad.setColorAt(0.5, QColor(230, 100, 30))
            grad.setColorAt(1.0, QColor(170, 55, 15))
            band_col = QColor(20, 20, 22)
            txt_col = QColor(255, 240, 225)
        else:
            grad = QLinearGradient(bx, by, bx, by + bh)
            grad.setColorAt(0.0, QColor(65, 65, 72))
            grad.setColorAt(0.45, QColor(35, 35, 40))
            grad.setColorAt(1.0, QColor(18, 18, 22))
            band_col = QColor(215, 220, 228)
            txt_col = QColor(235, 235, 240)

        body_path = QPainterPath()
        body_path.addRoundedRect(QRectF(bx, by, bw, bh), 2.5, 2.5)
        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(QColor(70, 70, 75), 0.9))
        painter.drawPath(body_path)

        # Cathode band on right side (towards Pin K)
        painter.save()
        painter.setClipPath(body_path)
        band_w = bw * 0.16
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(band_col)
        painter.drawRect(QRectF(bx + bw * 0.72, by, band_w, bh))
        painter.restore()

        label = instance.label if instance.label else self.default_label
        painter.setFont(QFont("Arial", int(max(4, p * 0.2)), QFont.Weight.Bold))
        painter.setPen(txt_col)
        painter.drawText(QRectF(bx + 2, by, bw * 0.7, bh), Qt.AlignmentFlag.AlignCenter, label)

        draw_top_pin(painter, 0, 0, 2.3)
        draw_top_pin(painter, span * p, 0, 2.3)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        span = _clamp_int(instance.custom_props.get("span", 4), 3, 8, 4)
        cx = (span * p) / 2.0
        bw, bh = 2.2 * p, 0.9 * p
        painter.setPen(QPen(QColor(180, 180, 190, 65), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(80, 80, 90, 20))
        painter.drawRoundedRect(QRectF(cx - bw / 2.0, -bh / 2.0, bw, bh), 2.5, 2.5)
        # Cathode K bar hint
        painter.setPen(QPen(QColor(220, 220, 230, 120), 2.0))
        painter.drawLine(QPointF(cx + bw * 0.3, -bh * 0.4), QPointF(cx + bw * 0.3, bh * 0.4))

        draw_solder_joint(painter, 0, 0, p)
        draw_solder_joint(painter, span * p, 0, p)


class LEDDef(ComponentDef):
    def __init__(self, initial_size: str = "5mm"):
        self.initial_size = initial_size
        super().__init__(
            type_id=f"led_{initial_size}",
            name=f"LED ({initial_size})",
            category="Passives & Switches",
            default_label="LED1",
            description=f"{initial_size} round through-hole LED (Pin +: Anode, Pin -: Cathode with flat edge).",
            pins=[
                PinDef(name="+", grid_x=0, grid_y=0, description="Anode (+) - Long Lead", pin_type="passive"),
                PinDef(name="-", grid_x=1, grid_y=0, description="Cathode (-) - Flat Side", pin_type="passive"),
            ],
            properties=[
                PropertyDef(id="label", label="Label", type="str", default="LED1"),
                PropertyDef(id="color", label="Color", type="choice", default="Red",
                            choices=["Red", "Green", "Yellow", "Blue", "White"]),
            ],
            anchor_pin_index=0,
            tags=["led", initial_size, "diode", "light", "indicator"]
        )

    def _radius(self, pitch_px: float) -> float:
        return (0.72 if self.initial_size == "3mm" else 1.08) * pitch_px

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        p = pitch_px
        r = self._radius(p)
        cx = 0.5 * p
        path = QPainterPath()
        path.addEllipse(QPointF(cx, 0.0), r, r)
        pad_r = 0.45 * p
        path.addEllipse(QPointF(0, 0), pad_r, pad_r)
        path.addEllipse(QPointF(p, 0), pad_r, pad_r)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        r = self._radius(p)
        cx = 0.5 * p
        col_name = instance.custom_props.get("color", "Red")
        palette = {
            "Red": (QColor(255, 110, 100), QColor(220, 35, 30), QColor(140, 15, 15)),
            "Green": (QColor(115, 255, 130), QColor(35, 195, 55), QColor(15, 115, 30)),
            "Yellow": (QColor(255, 240, 110), QColor(235, 195, 25), QColor(155, 120, 10)),
            "Blue": (QColor(115, 185, 255), QColor(35, 115, 240), QColor(15, 65, 165)),
            "White": (QColor(255, 255, 255), QColor(225, 235, 245), QColor(165, 175, 190)),
        }
        c_hi, c_mid, c_rim = palette.get(col_name, palette["Red"])

        # Shadow
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 45))
        painter.drawEllipse(QPointF(cx + 1.5, 2.0), r, r)

        # Outer flange rim with flat cathode edge on right side
        clip = QPainterPath()
        clip.addEllipse(QPointF(cx, 0), r, r)
        flat_cut = QPainterPath()
        flat_cut.addRect(QRectF(cx + r * 0.78, -r - 2, r, r * 2 + 4))
        flange = clip.subtracted(flat_cut)

        painter.setBrush(c_rim)
        painter.setPen(QPen(c_rim.darker(150), 1.0))
        painter.drawPath(flange)

        # Glowing dome center
        dome_r = r * 0.78
        grad = QRadialGradient(cx - dome_r * 0.3, -dome_r * 0.3, dome_r * 1.2)
        grad.setColorAt(0.0, c_hi)
        grad.setColorAt(0.6, c_mid)
        grad.setColorAt(1.0, c_rim)
        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(c_rim.darker(130), 0.8))
        painter.drawEllipse(QPointF(cx, 0), dome_r, dome_r)

        # Specular highlight dot
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 140))
        painter.drawEllipse(QPointF(cx - dome_r * 0.35, -dome_r * 0.35), dome_r * 0.22, dome_r * 0.22)

        # Silkscreen label above
        label = instance.label if instance.label else "LED"
        painter.setFont(QFont("Arial", int(max(4, p * 0.2)), QFont.Weight.Bold))
        painter.setPen(QColor(245, 245, 245, 220))
        painter.drawText(QRectF(cx - r * 1.3, -r - p * 0.52, r * 2.6, p * 0.5),
                         Qt.AlignmentFlag.AlignCenter, label)

        draw_top_pin(painter, 0, 0, 2.1)
        draw_top_pin(painter, p, 0, 2.1)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        r = self._radius(p)
        cx = 0.5 * p
        painter.setPen(QPen(QColor(180, 180, 190, 65), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(200, 120, 120, 20))
        painter.drawEllipse(QPointF(cx, 0), r, r)
        # '+' indicator at anode
        painter.setFont(QFont("Arial", int(max(5, p * 0.22)), QFont.Weight.Bold))
        painter.setPen(QColor(255, 110, 110, 180))
        draw_unmirrored_text(painter, QRectF(-0.4 * p, -0.9 * p, 0.8 * p, 0.5 * p), Qt.AlignmentFlag.AlignCenter, "+")

        draw_solder_joint(painter, 0, 0, p)
        draw_solder_joint(painter, p, 0, p)


class CrystalDef(ComponentDef):
    def __init__(self):
        super().__init__(
            type_id="crystal_hc49s",
            name="Crystal Oscillator (HC-49S)",
            category="Passives & Switches",
            default_label="16MHz",
            description="2-pin HC-49S low-profile quartz crystal (5.08mm pitch).",
            pins=[
                PinDef(name="1", grid_x=0, grid_y=0, description="XTAL Pin 1", pin_type="passive"),
                PinDef(name="2", grid_x=2, grid_y=0, description="XTAL Pin 2", pin_type="passive"),
            ],
            properties=[
                PropertyDef(id="label", label="Frequency", type="str", default="16MHz"),
            ],
            anchor_pin_index=0,
            tags=["crystal", "oscillator", "hc49s", "16mhz", "8mhz", "32khz"]
        )

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        p = pitch_px
        path = QPainterPath()
        path.addRoundedRect(QRectF(-0.9 * p, -0.85 * p, 3.8 * p, 1.7 * p), 0.85 * p, 0.85 * p)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        bx, by, bw, bh = -0.85 * p, -0.8 * p, 3.7 * p, 1.6 * p
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 40))
        painter.drawRoundedRect(QRectF(bx + 1.5, by + 2.0, bw, bh), bh / 2.0, bh / 2.0)

        grad = QLinearGradient(bx, by, bx, by + bh)
        grad.setColorAt(0.0, QColor(235, 240, 245))
        grad.setColorAt(0.5, QColor(195, 200, 208))
        grad.setColorAt(1.0, QColor(145, 150, 160))
        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(QColor(100, 105, 115), 1.0))
        painter.drawRoundedRect(QRectF(bx, by, bw, bh), bh / 2.0, bh / 2.0)

        painter.setPen(QPen(QColor(135, 140, 150), 0.8))
        painter.drawRoundedRect(QRectF(bx + 3, by + 2.5, bw - 6, bh - 5), (bh - 5) / 2.0, (bh - 5) / 2.0)

        label = instance.label if instance.label else "16MHz"
        painter.setFont(QFont("Arial", int(max(4, p * 0.24)), QFont.Weight.Bold))
        painter.setPen(QColor(45, 50, 55))
        painter.drawText(QRectF(bx, by, bw, bh), Qt.AlignmentFlag.AlignCenter, label)

        draw_top_pin(painter, 0, 0, 2.2)
        draw_top_pin(painter, 2 * p, 0, 2.2)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        bx, by, bw, bh = -0.85 * p, -0.8 * p, 3.7 * p, 1.6 * p
        painter.setPen(QPen(QColor(180, 180, 190, 65), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(180, 185, 195, 20))
        painter.drawRoundedRect(QRectF(bx, by, bw, bh), bh / 2.0, bh / 2.0)
        draw_solder_joint(painter, 0, 0, p)
        draw_solder_joint(painter, 2 * p, 0, p)


class BuzzerDef(ComponentDef):
    def __init__(self):
        super().__init__(
            type_id="buzzer_12mm",
            name="Piezo Buzzer (12mm)",
            category="Passives & Switches",
            default_label="BZ1",
            description="12mm cylindrical active/passive buzzer (7.62mm lead pitch, polarized).",
            pins=[
                PinDef(name="+", grid_x=0, grid_y=0, description="Positive (+)", pin_type="passive"),
                PinDef(name="-", grid_x=3, grid_y=0, description="Negative (-)", pin_type="passive"),
            ],
            properties=[
                PropertyDef(id="label", label="Label", type="str", default="BZ1"),
            ],
            anchor_pin_index=0,
            tags=["buzzer", "piezo", "speaker", "sound", "alarm"]
        )

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        p = pitch_px
        r = 2.36 * p
        cx = 1.5 * p
        path = QPainterPath()
        path.addEllipse(QPointF(cx, 0), r, r)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        r = 2.36 * p
        cx = 1.5 * p

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 45))
        painter.drawEllipse(QPointF(cx + 2, 2.5), r, r)

        grad = QRadialGradient(cx - r * 0.3, -r * 0.3, r * 1.25)
        grad.setColorAt(0.0, QColor(58, 58, 64))
        grad.setColorAt(0.8, QColor(32, 32, 36))
        grad.setColorAt(1.0, QColor(18, 18, 22))
        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(QColor(75, 75, 85), 1.0))
        painter.drawEllipse(QPointF(cx, 0), r, r)

        # Acoustic sound hole in center
        painter.setBrush(QColor(12, 12, 14))
        painter.setPen(QPen(QColor(80, 80, 90), 0.9))
        painter.drawEllipse(QPointF(cx, 0), r * 0.25, r * 0.25)

        # '+' indicator on left (+ pin)
        painter.setFont(QFont("Arial", int(max(5, p * 0.28)), QFont.Weight.Bold))
        painter.setPen(QColor(235, 235, 240))
        painter.drawText(QRectF(cx - r * 0.72, -0.4 * p, 0.7 * p, 0.8 * p), Qt.AlignmentFlag.AlignCenter, "+")

        label = instance.label if instance.label else "BZ1"
        painter.setFont(QFont("Arial", int(max(5, p * 0.22)), QFont.Weight.Bold))
        painter.setPen(QColor(210, 210, 220))
        painter.drawText(QRectF(cx - r * 0.8, r * 0.35, r * 1.6, 0.65 * p), Qt.AlignmentFlag.AlignCenter, label)

        draw_top_pin(painter, 0, 0, 2.4)
        draw_top_pin(painter, 3 * p, 0, 2.4)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        r = 2.36 * p
        cx = 1.5 * p
        painter.setPen(QPen(QColor(180, 180, 190, 60), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(50, 50, 60, 20))
        painter.drawEllipse(QPointF(cx, 0), r, r)
        draw_solder_joint(painter, 0, 0, p)
        draw_solder_joint(painter, 3 * p, 0, p)
