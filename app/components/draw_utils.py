"""
Drawing utility functions for component rendering.
"""
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QRadialGradient, QLinearGradient
from PyQt6.QtCore import Qt, QRectF, QPointF

def draw_solder_joint(painter: QPainter, x: float, y: float, pitch: float, pad_r: float = 6.0, pin_r: float = 2.4):
    """Draws a solder joint for bottom view."""
    # Outer copper/solder ring
    solder_grad = QRadialGradient(x, y, pad_r)
    solder_grad.setColorAt(0.0, QColor(220, 225, 230))
    solder_grad.setColorAt(0.6, QColor(190, 195, 205))
    solder_grad.setColorAt(1.0, QColor(150, 155, 165))
    painter.setPen(QPen(QColor(110, 115, 120), 0.8))
    painter.setBrush(QBrush(solder_grad))
    painter.drawEllipse(QPointF(x, y), pad_r, pad_r)

    # Pin center lead (silver square or circle with clipped lead look)
    pin_grad = QRadialGradient(x - 0.5, y - 0.5, pin_r)
    pin_grad.setColorAt(0.0, QColor(250, 250, 255))
    pin_grad.setColorAt(0.8, QColor(170, 175, 185))
    pin_grad.setColorAt(1.0, QColor(90, 95, 105))
    painter.setPen(QPen(QColor(70, 75, 80), 0.6))
    painter.setBrush(QBrush(pin_grad))
    painter.drawEllipse(QPointF(x, y), pin_r, pin_r)

def draw_top_pin(painter: QPainter, x: float, y: float, pin_r: float = 2.5):
    """Draws a pin entering a hole on the top view."""
    pin_grad = QRadialGradient(x - 0.5, y - 0.5, pin_r)
    pin_grad.setColorAt(0.0, QColor(255, 250, 220)) # Gold / tinned
    pin_grad.setColorAt(0.7, QColor(210, 190, 120))
    pin_grad.setColorAt(1.0, QColor(120, 100, 50))
    painter.setPen(QPen(QColor(60, 50, 20), 0.6))
    painter.setBrush(QBrush(pin_grad))
    painter.drawEllipse(QPointF(x, y), pin_r, pin_r)

def draw_unmirrored_text(painter: QPainter, rect: QRectF, flags: int, text: str):
    """Draws text un-mirrored when current coordinate system is horizontally inverted."""
    painter.save()
    cx = rect.center().x()
    cy = rect.center().y()
    painter.translate(cx, cy)
    painter.scale(-1.0, 1.0)
    painter.translate(-cx, -cy)
    painter.drawText(rect, flags, text)
    painter.restore()
