"""
Electrolytic Capacitor component definition with multiple diameter sizes.
"""
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QRadialGradient, QLinearGradient, QPainterPath
)
from PyQt6.QtCore import Qt, QRectF, QPointF
from app.models.component_def import ComponentDef, PinDef, PropertyDef
from app.components.draw_utils import draw_solder_joint, draw_top_pin

DIAMETER_SPECS = {
    "5mm": {"dia_mm": 5.0, "pitch_holes": 1, "body_r_ratio": 0.95, "default_cap": "10µF"},
    "8mm": {"dia_mm": 8.0, "pitch_holes": 2, "body_r_ratio": 1.55, "default_cap": "220µF"},
    "10mm": {"dia_mm": 10.0, "pitch_holes": 2, "body_r_ratio": 1.95, "default_cap": "1000µF"},
    "12.5mm": {"dia_mm": 12.5, "pitch_holes": 2, "body_r_ratio": 2.45, "default_cap": "2200µF"},
}

class ElectrolyticCapacitorDef(ComponentDef):
    def __init__(self, initial_diameter: str = "8mm"):
        self.initial_diameter = initial_diameter
        spec = DIAMETER_SPECS.get(initial_diameter, DIAMETER_SPECS["8mm"])
        pitch_h = spec["pitch_holes"]

        pins = [
            PinDef(name="+", grid_x=0, grid_y=0, description="Anode (+)", pin_type="passive"),
            PinDef(name="-", grid_x=pitch_h, grid_y=0, description="Cathode (-)", pin_type="passive"),
        ]

        super().__init__(
            type_id=f"capacitor_{initial_diameter}",
            name=f"Electrolytic Capacitor ({initial_diameter})",
            category="Passives & Switches",
            default_label=spec["default_cap"],
            description=f"Radial electrolytic capacitor (Ø{initial_diameter}, {pitch_h * 2.54:.2f}mm lead pitch).",
            pins=pins,
            properties=[
                PropertyDef(id="diameter", label="Diameter", type="choice", default=initial_diameter,
                            choices=list(DIAMETER_SPECS.keys())),
                PropertyDef(id="label", label="Value", type="str", default=spec["default_cap"]),
                PropertyDef(id="voltage", label="Voltage Rating", type="str", default="25V"),
                PropertyDef(id="sleeve_color", label="Sleeve Color", type="choice", default="Black / Silver",
                            choices=["Black / Silver", "Blue / White", "Gold / Black", "Rubycon Red"])
            ],
            anchor_pin_index=0,
            tags=["capacitor", "electrolytic", "radial", "polarized"]
        )

    def get_pins_for_instance(self, instance) -> list[PinDef]:
        dia = instance.custom_props.get("diameter", self.initial_diameter)
        spec = DIAMETER_SPECS.get(dia, DIAMETER_SPECS["8mm"])
        pitch_h = spec["pitch_holes"]
        return [
            PinDef(name="+", grid_x=0, grid_y=0, description="Anode (+)", pin_type="passive"),
            PinDef(name="-", grid_x=pitch_h, grid_y=0, description="Cathode (-)", pin_type="passive"),
        ]

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        p = pitch_px
        dia = instance.custom_props.get("diameter", self.initial_diameter)
        spec = DIAMETER_SPECS.get(dia, DIAMETER_SPECS["8mm"])
        pitch_h = spec["pitch_holes"]
        r = spec["body_r_ratio"] * p
        cx = (pitch_h * p) / 2.0
        cy = 0.0

        path = QPainterPath()
        path.addEllipse(QPointF(cx, cy), r, r)
        pad_r = 0.45 * p
        path.addEllipse(QPointF(0, 0), pad_r, pad_r)
        path.addEllipse(QPointF(pitch_h * p, 0), pad_r, pad_r)
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        dia = instance.custom_props.get("diameter", self.initial_diameter)
        spec = DIAMETER_SPECS.get(dia, DIAMETER_SPECS["8mm"])
        pitch_h = spec["pitch_holes"]
        r = spec["body_r_ratio"] * p

        # Center between the two pins
        cx = (pitch_h * p) / 2.0
        cy = 0.0

        # Leads from body to holes
        painter.setPen(QPen(QColor(170, 175, 185), 2.2))
        painter.drawLine(QPointF(0, 0), QPointF(cx - r * 0.5, 0))
        painter.drawLine(QPointF(pitch_h * p, 0), QPointF(cx + r * 0.5, 0))

        # Shadow
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 45))
        painter.drawEllipse(QPointF(cx + 2.0, cy + 2.5), r, r)

        sleeve = instance.custom_props.get("sleeve_color", "Black / Silver")
        if sleeve == "Blue / White":
            base_col = QColor(25, 75, 180)
            stripe_col = QColor(240, 245, 255)
            stripe_txt_col = QColor(25, 75, 180)
        elif sleeve == "Gold / Black":
            base_col = QColor(190, 155, 30)
            stripe_col = QColor(30, 30, 30)
            stripe_txt_col = QColor(240, 220, 100)
        elif sleeve == "Rubycon Red":
            base_col = QColor(140, 20, 30)
            stripe_col = QColor(220, 220, 230)
            stripe_txt_col = QColor(140, 20, 30)
        else: # Black / Silver
            base_col = QColor(35, 35, 40)
            stripe_col = QColor(215, 220, 225)
            stripe_txt_col = QColor(40, 40, 45)

        # Outer sleeve body
        grad = QRadialGradient(cx - r * 0.35, cy - r * 0.35, r * 1.3)
        grad.setColorAt(0.0, base_col.lighter(130))
        grad.setColorAt(0.8, base_col)
        grad.setColorAt(1.0, base_col.darker(150))
        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(base_col.darker(170), 1.0))
        painter.drawEllipse(QPointF(cx, cy), r, r)

        # Negative polarity stripe on the cathode side (right side)
        painter.save()
        clip_path = QPainterPath()
        clip_path.addEllipse(QPointF(cx, cy), r - 0.5, r - 0.5)
        painter.setClipPath(clip_path)

        stripe_w = r * 0.65
        painter.setBrush(QBrush(stripe_col))
        painter.setPen(Qt.PenStyle.NoPen)
        # Stripe on right side where cathode pin is
        painter.drawRect(QRectF(cx + r - stripe_w, cy - r, stripe_w, r * 2))

        # Minus '-' signs on negative stripe
        painter.setPen(QPen(stripe_txt_col, max(1.5, p * 0.08)))
        font_stripe = QFont("Arial", int(max(6, p * 0.28)), QFont.Weight.Bold)
        painter.setFont(font_stripe)
        for offset_y in (-r * 0.45, 0, r * 0.45):
            painter.drawText(QRectF(cx + r - stripe_w, cy + offset_y - 8, stripe_w, 16),
                             Qt.AlignmentFlag.AlignCenter, "–")

        painter.restore()

        # Aluminum scored vent cross in center
        vent_r = r * 0.45
        painter.setPen(QPen(QColor(255, 255, 255, 60), 1.2))
        painter.drawLine(QPointF(cx - vent_r, cy), QPointF(cx + vent_r, cy))
        painter.drawLine(QPointF(cx, cy - vent_r), QPointF(cx, cy + vent_r))

        # Value and polarity labels
        val_text = instance.label if instance.label else spec["default_cap"]
        volt_text = instance.custom_props.get("voltage", "25V")
        font = QFont("Arial", int(max(6, p * 0.24)), QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255, 220))
        painter.drawText(QRectF(cx - r * 0.9, cy - r * 0.7, r * 1.1, r * 0.7),
                         Qt.AlignmentFlag.AlignCenter, val_text)

        v_font = QFont("Arial", int(max(5, p * 0.18)), QFont.Weight.Normal)
        painter.setFont(v_font)
        painter.setPen(QColor(220, 220, 220, 180))
        painter.drawText(QRectF(cx - r * 0.9, cy + 0.1 * r, r * 1.1, r * 0.6),
                         Qt.AlignmentFlag.AlignCenter, volt_text)

        # Draw Anode (+) indicator
        painter.setPen(QPen(QColor(255, 100, 100), 1.2))
        painter.drawText(QRectF(cx - r * 0.75, cy - r * 0.15, 12, 12), Qt.AlignmentFlag.AlignCenter, "+")

        # Pins entering holes
        draw_top_pin(painter, 0, 0, 2.4)
        draw_top_pin(painter, pitch_h * p, 0, 2.4)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        dia = instance.custom_props.get("diameter", self.initial_diameter)
        spec = DIAMETER_SPECS.get(dia, DIAMETER_SPECS["8mm"])
        pitch_h = spec["pitch_holes"]
        r = spec["body_r_ratio"] * p
        cx = (pitch_h * p) / 2.0
        cy = 0.0

        # Ghost outline
        painter.setPen(QPen(QColor(180, 180, 190, 60), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(100, 100, 120, 20))
        painter.drawEllipse(QPointF(cx, cy), r, r)

        # Solder joints for Anode (+) and Cathode (-)
        draw_solder_joint(painter, 0, 0, p)
        draw_solder_joint(painter, pitch_h * p, 0, p)
