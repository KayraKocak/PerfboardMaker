"""
Visual overlay for AutoConnect mode.
Renders glowing selection rings, labels, and hover feedback on selected conductors.
"""
from PyQt6.QtWidgets import QGraphicsItem
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont
from PyQt6.QtCore import Qt, QRectF, QPointF
from app.models.board import BoardConfig
from app.models.router import AutoConnectTarget, AutoConnectGroup

class AutoConnectOverlayItem(QGraphicsItem):
    def __init__(self, config: BoardConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.targets: list[AutoConnectTarget] = []
        self.groups: list[AutoConnectGroup] = []
        self.hover_hole: tuple[int, int] | None = None
        self.hover_label: str = ""
        self.is_active_mode = False

        self.setZValue(90) # Above components and traces
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setAcceptHoverEvents(False)

    def set_active(self, active: bool):
        self.is_active_mode = active
        self.update()

    def set_selected_targets(self, targets: list[AutoConnectTarget]):
        self.targets = list(targets)
        self.update()

    def set_groups(self, groups: list[AutoConnectGroup]):
        self.groups = list(groups)
        self.update()

    def set_hover(self, hole: tuple[int, int] | None, label: str = ""):
        self.hover_hole = hole
        self.hover_label = label
        self.update()

    def boundingRect(self) -> QRectF:
        m = self.config.margin_px
        w = self.config.width_px
        h = self.config.height_px
        return QRectF(-m, -m, w + 2 * m, h + 2 * m)

    def paint(self, painter: QPainter, option, widget=None):
        if not self.is_active_mode:
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        pad_r = self.config.pad_radius_px

        # 1. Paint Defined Conductor Groups (Each with its distinct group color)
        for g in self.groups:
            gc = QColor(g.color)
            glow_pen = QPen(gc, 2.5)
            glow_brush = QBrush(QColor(gc.red(), gc.green(), gc.blue(), 55))
            painter.setPen(glow_pen)
            painter.setBrush(glow_brush)

            # Draw halo on all holes in this group
            for c, r in g.all_holes():
                if self.config.is_valid_hole(c, r):
                    bx, by = self.config.grid_to_board_pos(c, r)
                    painter.drawEllipse(QPointF(bx, by), pad_r * 1.45, pad_r * 1.45)

            # Draw badge and tag for each target in this group
            for t_idx, target in enumerate(g.targets):
                if target.center_hole and self.config.is_valid_hole(*target.center_hole):
                    cx, cy = self.config.grid_to_board_pos(*target.center_hole)

                    # Center badge ring
                    painter.setPen(QPen(QColor(255, 255, 255, 255), 2.0))
                    painter.setBrush(QColor(gc.red(), gc.green(), gc.blue(), 215))
                    painter.drawEllipse(QPointF(cx, cy), pad_r * 0.95, pad_r * 0.95)

                    # Group badge text (e.g. "G1", "G2")
                    badge_text = f"G{g.id}"
                    painter.setPen(QColor(15, 15, 15))
                    painter.setFont(QFont("Arial", 7, QFont.Weight.Black))
                    painter.drawText(QRectF(cx - 10, cy - 10, 20, 20),
                                     Qt.AlignmentFlag.AlignCenter, badge_text)

                    # Tag label above
                    tag_text = f"[G{g.id}] {target.label}"
                    tag_w = max(55, len(tag_text) * 6.5 + 12)
                    tag_rect = QRectF(cx - tag_w / 2, cy - pad_r * 1.5 - 18, tag_w, 16)

                    painter.setPen(QPen(gc, 1.2))
                    painter.setBrush(QColor(20, 21, 24, 230))
                    painter.drawRoundedRect(tag_rect, 3, 3)

                    painter.setPen(gc)
                    painter.setFont(QFont("Arial", 8, QFont.Weight.Bold))
                    painter.drawText(tag_rect, Qt.AlignmentFlag.AlignCenter, tag_text)

        # 2. Paint Pending Selected Targets (Bright Cyan Glowing Aura & Badges)
        for idx, target in enumerate(self.targets):
            glow_pen = QPen(QColor(0, 230, 255, 240), 2.5)
            glow_brush = QBrush(QColor(0, 230, 255, 50))
            painter.setPen(glow_pen)
            painter.setBrush(glow_brush)

            # Draw halo on all holes belonging to this conductor
            for c, r in target.holes:
                if self.config.is_valid_hole(c, r):
                    bx, by = self.config.grid_to_board_pos(c, r)
                    painter.drawEllipse(QPointF(bx, by), pad_r * 1.4, pad_r * 1.4)

            # Draw prominent badge on the primary/center hole
            if target.center_hole and self.config.is_valid_hole(*target.center_hole):
                cx, cy = self.config.grid_to_board_pos(*target.center_hole)

                painter.setPen(QPen(QColor(255, 255, 255, 255), 2.0))
                painter.setBrush(QColor(0, 230, 255, 200))
                painter.drawEllipse(QPointF(cx, cy), pad_r * 0.9, pad_r * 0.9)

                badge_text = f"#{idx + 1}"
                painter.setPen(QColor(20, 20, 20))
                painter.setFont(QFont("Arial", 8, QFont.Weight.Black))
                painter.drawText(QRectF(cx - 10, cy - 10, 20, 20),
                                 Qt.AlignmentFlag.AlignCenter, badge_text)

                tag_text = target.label
                tag_w = max(50, len(tag_text) * 7 + 10)
                tag_rect = QRectF(cx - tag_w / 2, cy - pad_r * 1.5 - 18, tag_w, 16)

                painter.setPen(QPen(QColor(0, 230, 255, 220), 1.0))
                painter.setBrush(QColor(24, 25, 28, 220))
                painter.drawRoundedRect(tag_rect, 3, 3)

                painter.setPen(QColor(0, 230, 255))
                painter.setFont(QFont("Arial", 8, QFont.Weight.Bold))
                painter.drawText(tag_rect, Qt.AlignmentFlag.AlignCenter, tag_text)

        # 3. Paint Hover Indicator (Dashed Cyan)
        if self.hover_hole is not None and self.config.is_valid_hole(*self.hover_hole):
            c, r = self.hover_hole
            bx, by = self.config.grid_to_board_pos(c, r)

            hover_pen = QPen(QColor(0, 230, 255, 180), 2.0, Qt.PenStyle.DashLine)
            painter.setPen(hover_pen)
            painter.setBrush(QColor(0, 230, 255, 30))
            painter.drawEllipse(QPointF(bx, by), pad_r * 1.5, pad_r * 1.5)

            if self.hover_label:
                # Check if this hover hole is in an existing group
                hl = self.hover_label
                for g in self.groups:
                    if (c, r) in g.all_holes():
                        hl = f"[G{g.id}] {hl}"
                        break
                painter.setPen(QColor(255, 255, 255, 220))
                painter.setFont(QFont("Arial", 8, QFont.Weight.Bold))
                painter.drawText(QRectF(bx - 50, by - pad_r * 1.5 - 16, 100, 16),
                                 Qt.AlignmentFlag.AlignCenter, hl)

        painter.restore()
