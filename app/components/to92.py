"""
TO-92 Packaged IC component definition (renameable).
"""
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QRadialGradient, QLinearGradient, QPainterPath
)
from PyQt6.QtCore import Qt, QRectF, QPointF
from app.models.component_def import ComponentDef, PinDef, PropertyDef
from app.components.draw_utils import draw_solder_joint, draw_top_pin, draw_unmirrored_text

class TO92Def(ComponentDef):
    def __init__(self):
        pins = [
            PinDef(name="1", grid_x=0, grid_y=0, description="Pin 1 (e.g. Emitter)", pin_type="io"),
            PinDef(name="2", grid_x=1, grid_y=0, description="Pin 2 (e.g. Base)", pin_type="io"),
            PinDef(name="3", grid_x=2, grid_y=0, description="Pin 3 (e.g. Collector)", pin_type="io"),
        ]

        super().__init__(
            type_id="to92",
            name="TO-92 Package IC",
            category="Semiconductors & ICs",
            default_label="2N2222",
            description="3-pin small signal transistor / sensor D-shaped package (renameable).",
            pins=pins,
            properties=[
                PropertyDef(id="label", label="Part Number / Label", type="str", default="2N2222")
            ],
            anchor_pin_index=0,
            tags=["to92", "transistor", "sensor", "2n2222", "ds18b20", "lm35", "bc547"]
        )

    def get_shape(self, instance, pitch_px: float) -> QPainterPath:
        p = pitch_px
        cx = 1.0 * p
        cy = -0.15 * p
        bw = 2.5 * p
        bh = 1.9 * p
        body_rect = QRectF(cx - bw / 2.0, cy - bh / 2.0, bw, bh)
        path = QPainterPath()
        path.moveTo(body_rect.left(), body_rect.bottom() + 0.3 * p)
        path.lineTo(body_rect.right(), body_rect.bottom() + 0.3 * p)
        path.arcTo(body_rect, 0, 180)
        path.closeSubpath()
        return path

    def draw_top(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        # Center is at pin 2: (1.0*p, 0)
        cx = 1.0 * p
        cy = -0.15 * p
        bw = 2.4 * p
        bh = 1.8 * p

        # Shadow
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 40))
        shadow_path = QPainterPath()
        # D-shape: flat front bottom, semicircular top
        s_rect = QRectF(cx - bw / 2.0 + 1.5, cy - bh / 2.0 + 2.0, bw, bh)
        shadow_path.moveTo(s_rect.left(), s_rect.bottom())
        shadow_path.lineTo(s_rect.right(), s_rect.bottom())
        shadow_path.arcTo(s_rect, 0, 180)
        shadow_path.closeSubpath()
        painter.drawPath(shadow_path)

        # D-shape body path
        body_rect = QRectF(cx - bw / 2.0, cy - bh / 2.0, bw, bh)
        path = QPainterPath()
        path.moveTo(body_rect.left(), body_rect.bottom())
        path.lineTo(body_rect.right(), body_rect.bottom())
        path.arcTo(body_rect, 0, 180)
        path.closeSubpath()

        # Gradient fill for molded black plastic
        grad = QLinearGradient(body_rect.left(), body_rect.top(), body_rect.left(), body_rect.bottom())
        grad.setColorAt(0.0, QColor(50, 50, 55))
        grad.setColorAt(0.5, QColor(32, 32, 36))
        grad.setColorAt(1.0, QColor(20, 20, 24))
        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(QColor(65, 65, 70), 1.0))
        painter.drawPath(path)

        # Flat face bevel highlight
        painter.setPen(QPen(QColor(80, 80, 85), 0.8))
        painter.drawLine(QPointF(body_rect.left() + 2, body_rect.bottom() - 2),
                         QPointF(body_rect.right() - 2, body_rect.bottom() - 2))

        # Part label on flat face
        label_text = instance.label if instance.label else "2N2222"
        font = QFont("Arial", int(max(6, p * 0.23)), QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(240, 240, 245))
        painter.drawText(QRectF(body_rect.left(), cy - 0.25 * p, bw, bh * 0.75),
                         Qt.AlignmentFlag.AlignCenter, label_text)

        # Pin leads extending to holes
        painter.setPen(QPen(QColor(180, 185, 195), 2.2))
        painter.drawLine(QPointF(0, body_rect.bottom()), QPointF(0, 0))
        painter.drawLine(QPointF(1.0 * p, body_rect.bottom()), QPointF(1.0 * p, 0))
        painter.drawLine(QPointF(2.0 * p, body_rect.bottom()), QPointF(2.0 * p, 0))

        # Pins entering holes
        draw_top_pin(painter, 0, 0, 2.4)
        draw_top_pin(painter, 1.0 * p, 0, 2.4)
        draw_top_pin(painter, 2.0 * p, 0, 2.4)

    def draw_bottom(self, painter: QPainter, instance, pitch_px: float) -> None:
        p = pitch_px
        cx = 1.0 * p
        cy = -0.15 * p
        bw = 2.4 * p
        bh = 1.8 * p

        # Ghost outline
        body_rect = QRectF(cx - bw / 2.0, cy - bh / 2.0, bw, bh)
        path = QPainterPath()
        path.moveTo(body_rect.left(), body_rect.bottom())
        path.lineTo(body_rect.right(), body_rect.bottom())
        path.arcTo(body_rect, 0, 180)
        path.closeSubpath()

        painter.setPen(QPen(QColor(180, 180, 190, 60), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(100, 100, 110, 20))
        painter.drawPath(path)

        label_text = instance.label if instance.label else "2N2222"
        font = QFont("Arial", int(max(5, p * 0.22)), QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(200, 200, 210, 80))
        draw_unmirrored_text(painter, QRectF(body_rect.left(), cy - 0.25 * p, bw, bh * 0.75), Qt.AlignmentFlag.AlignCenter, label_text)

        # Solder joints for 3 pins
        draw_solder_joint(painter, 0, 0, p)
        draw_solder_joint(painter, 1.0 * p, 0, p)
        draw_solder_joint(painter, 2.0 * p, 0, p)
