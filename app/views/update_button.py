"""
Animated glowing rainbow button for displaying update availability in the status bar.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, QRectF, QSize
from PyQt6.QtGui import (
    QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen
)
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QPushButton


class RainbowUpdateButton(QPushButton):
    """Pill-shaped button with an animated flowing rainbow gradient and outer glow."""

    def __init__(self, text: str = "Newer Version Found", parent=None):
        super().__init__(text, parent)
        self.setObjectName("btn_update")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)

        font = QFont(self.font())
        font.setPointSize(9)
        font.setBold(True)
        self.setFont(font)

        fm = QFontMetrics(font)
        text_w = fm.horizontalAdvance(text)
        self.setFixedSize(QSize(text_w + 30, 22))

        self._phase: float = 0.0
        self._hovered: bool = False
        self._pressed: bool = False

        self._glow = QGraphicsDropShadowEffect(self)
        self._glow.setOffset(0.0, 0.0)
        self._glow.setBlurRadius(18.0)
        self._glow.setColor(QColor.fromHsvF(0.0, 0.85, 1.0, 0.92))
        self.setGraphicsEffect(self._glow)

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(33)  # ~30 FPS
        self._anim_timer.timeout.connect(self._advance_animation)

    def _advance_animation(self):
        self._phase = (self._phase + 0.012) % 1.0
        glow_hue = (self._phase + 0.5) % 1.0
        alpha = 0.98 if self._hovered else 0.85
        self._glow.setBlurRadius(22.0 if self._hovered else 16.0)
        self._glow.setColor(QColor.fromHsvF(glow_hue, 0.90, 1.0, alpha))
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._anim_timer.isActive():
            self._anim_timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._anim_timer.isActive():
            self._anim_timer.stop()

    def enterEvent(self, event):
        self._hovered = True
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        self._hovered = False
        self._pressed = False
        super().leaveEvent(event)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        if self._pressed:
            rect = rect.adjusted(0.5, 0.5, -0.5, -0.5)

        radius = rect.height() / 2.0
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        # Animated flowing horizontal rainbow fill
        fill_grad = QLinearGradient(rect.left(), rect.center().y(), rect.right(), rect.center().y())
        val = 0.72 if self._pressed else (0.94 if self._hovered else 0.82)
        sat = 0.88
        stops = 7
        for i in range(stops):
            t = i / (stops - 1)
            hue = (self._phase + t * 0.85) % 1.0
            fill_grad.setColorAt(t, QColor.fromHsvF(hue, sat, val))

        painter.fillPath(path, fill_grad)

        # Subtle glossy upper sheen so colors pop cleanly
        painter.save()
        painter.setClipPath(path)
        sheen_rect = QRectF(rect.left(), rect.top(), rect.width(), rect.height() * 0.48)
        painter.fillRect(sheen_rect, QColor(255, 255, 255, 42 if self._hovered else 28))
        painter.restore()

        # Bright luminous rainbow outline
        border_grad = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.bottom())
        for i in range(stops):
            t = i / (stops - 1)
            hue = (self._phase + 0.15 + t * 0.85) % 1.0
            border_grad.setColorAt(t, QColor.fromHsvF(hue, 0.55, 1.0))

        painter.setPen(QPen(border_grad, 1.6))
        painter.drawPath(path)

        # Crisp text with subtle dark shadow for readability across all rainbow hues
        painter.setFont(self.font())
        text_rect = rect.adjusted(0, -0.5, 0, -0.5)
        painter.setPen(QColor(0, 0, 0, 200))
        painter.drawText(text_rect.translated(0.0, 1.0), Qt.AlignmentFlag.AlignCenter, self.text())

        painter.setPen(QColor("#ffffff"))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, self.text())
