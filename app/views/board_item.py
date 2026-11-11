"""
Procedural Perfboard QGraphicsItem.
Renders the PCB substrate, donut pads, drilled holes, coordinate rulers, and corner mounting holes.
"""
from PyQt6.QtWidgets import QGraphicsItem
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QRadialGradient, QLinearGradient
)
from PyQt6.QtCore import Qt, QRectF, QPointF
from app.models.board import BoardConfig, col_index_to_name

BOARD_THEMES = {
    "green": {
        "substrate_top": QColor(18, 64, 34),
        "substrate_bottom": QColor(14, 52, 28),
        "border": QColor(25, 90, 48),
        "silkscreen": QColor(235, 245, 230, 210),
        "pad_outer": QColor(215, 175, 75),  # Copper/gold
        "pad_inner": QColor(185, 140, 45),
        "hole": QColor(14, 15, 17),
    },
    "brown": {
        "substrate_top": QColor(128, 80, 36),  # Phenolic bakelite
        "substrate_bottom": QColor(105, 62, 26),
        "border": QColor(160, 105, 50),
        "silkscreen": QColor(245, 235, 210, 200),
        "pad_outer": QColor(215, 175, 75),
        "pad_inner": QColor(185, 140, 45),
        "hole": QColor(14, 15, 17),
    },
    "blue": {
        "substrate_top": QColor(18, 54, 96),
        "substrate_bottom": QColor(12, 40, 74),
        "border": QColor(28, 80, 140),
        "silkscreen": QColor(240, 245, 255, 210),
        "pad_outer": QColor(215, 175, 75),
        "pad_inner": QColor(185, 140, 45),
        "hole": QColor(14, 15, 17),
    },
    "black": {
        "substrate_top": QColor(32, 34, 38),
        "substrate_bottom": QColor(22, 23, 26),
        "border": QColor(55, 58, 64),
        "silkscreen": QColor(230, 232, 238, 200),
        "pad_outer": QColor(215, 175, 75),
        "pad_inner": QColor(185, 140, 45),
        "hole": QColor(10, 10, 12),
    }
}

class BoardItem(QGraphicsItem):
    def __init__(self, config: BoardConfig):
        super().__init__()
        self.config = config
        self.hovered_col = -1
        self.hovered_row = -1
        self.active_resize_edges = ""
        self.is_resizing = False
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setZValue(0)  # Board is background

    def boundingRect(self) -> QRectF:
        # Extra 12px margin around board for shadow, edge resize highlights, and labels
        return QRectF(-12, -12, self.config.width_px + 24, self.config.height_px + 24)

    def set_hovered_hole(self, col: int, row: int):
        if self.hovered_col != col or self.hovered_row != row:
            self.hovered_col = col
            self.hovered_row = row
            self.update()

    def set_resize_edges(self, edges: str, active_drag: bool = False):
        if self.active_resize_edges != edges or self.is_resizing != active_drag:
            self.active_resize_edges = edges
            self.is_resizing = active_drag
            self.update()

    def paint(self, painter: QPainter, option, widget=None):
        cfg = self.config
        theme = BOARD_THEMES.get(cfg.style, BOARD_THEMES["green"])
        is_bottom = (cfg.view_side == "bottom")
        is_transparent = bool(getattr(cfg, "transparent", False))

        # 1. Outer Board Drop Shadow
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 35 if is_transparent else 70))
        painter.drawRoundedRect(QRectF(4, 6, cfg.width_px, cfg.height_px), 8.0, 8.0)

        # 2. PCB Substrate Rounded Rectangle
        sub_col = theme["substrate_bottom"] if is_bottom else theme["substrate_top"]
        c0 = QColor(sub_col.lighter(115))
        c1 = QColor(sub_col)
        c2 = QColor(sub_col.darker(115))
        if is_transparent:
            c0.setAlpha(115)
            c1.setAlpha(110)
            c2.setAlpha(115)

        grad = QLinearGradient(0, 0, cfg.width_px, cfg.height_px)
        grad.setColorAt(0.0, c0)
        grad.setColorAt(0.5, c1)
        grad.setColorAt(1.0, c2)

        border_col = QColor(theme["border"])
        if is_transparent:
            border_col.setAlpha(190)

        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(border_col, 1.5))
        board_rect = QRectF(0, 0, cfg.width_px, cfg.height_px)
        painter.drawRoundedRect(board_rect, 6.0, 6.0)

        # 3. Silkscreen Margin Border Line
        silk_col = QColor(theme["silkscreen"])
        if is_transparent:
            silk_col.setAlpha(165)
        painter.setPen(QPen(silk_col, 0.9, Qt.PenStyle.SolidLine))
        margin_inner = cfg.margin_px * 0.5
        painter.drawRoundedRect(
            QRectF(margin_inner, margin_inner, cfg.width_px - 2 * margin_inner, cfg.height_px - 2 * margin_inner),
            4.0, 4.0
        )

        # 4. Corner Mounting Holes (4 corners)
        mount_r = 5.2
        mount_pad_r = 9.0
        mount_offset = cfg.margin_px * 0.45
        corners = [
            (mount_offset, mount_offset),
            (cfg.width_px - mount_offset, mount_offset),
            (mount_offset, cfg.height_px - mount_offset),
            (cfg.width_px - mount_offset, cfg.height_px - mount_offset)
        ]
        hole_col = QColor(theme["hole"])
        if is_transparent:
            hole_col.setAlpha(105)

        for mx, my in corners:
            # Copper ring around mounting hole
            painter.setBrush(QColor(215, 175, 75))
            painter.setPen(QPen(QColor(160, 125, 40), 1.0))
            painter.drawEllipse(QPointF(mx, my), mount_pad_r, mount_pad_r)
            # Center hole
            painter.setBrush(hole_col)
            painter.setPen(QPen(QColor(30, 30, 30), 0.8))
            painter.drawEllipse(QPointF(mx, my), mount_r, mount_r)

        # 5. Silkscreen Coordinate Labels (Columns & Rows)
        font = QFont("Arial", 8, QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(theme["silkscreen"])

        # Top & Bottom Column Labels (A, B, C...)
        for c in range(cfg.cols):
            x, _ = cfg.grid_to_board_pos(c, 0)
            col_name = col_index_to_name(c)
            # Top label
            painter.drawText(QRectF(x - cfg.pitch_px / 2, 2, cfg.pitch_px, cfg.margin_px - 4),
                             Qt.AlignmentFlag.AlignCenter, col_name)
            # Bottom label
            painter.drawText(QRectF(x - cfg.pitch_px / 2, cfg.height_px - cfg.margin_px + 2, cfg.pitch_px, cfg.margin_px - 4),
                             Qt.AlignmentFlag.AlignCenter, col_name)

        # Left & Right Row Labels (1, 2, 3...)
        for r in range(cfg.rows):
            _, y = cfg.grid_to_board_pos(0, r)
            row_num = str(r + 1)
            # Left label
            painter.drawText(QRectF(2, y - cfg.pitch_px / 2, cfg.margin_px - 4, cfg.pitch_px),
                             Qt.AlignmentFlag.AlignCenter, row_num)
            # Right label
            painter.drawText(QRectF(cfg.width_px - cfg.margin_px + 2, y - cfg.pitch_px / 2, cfg.margin_px - 4, cfg.pitch_px),
                             Qt.AlignmentFlag.AlignCenter, row_num)

        # 6. Procedural Copper Donut Pads and Drilled Holes
        pad_r = cfg.pad_radius_px
        hole_r = cfg.hole_radius_px

        # Pad gradient for realistic metallic donut ring
        for c in range(cfg.cols):
            for r in range(cfg.rows):
                px, py = cfg.grid_to_board_pos(c, r)

                # Annular copper pad
                pad_grad = QRadialGradient(px - pad_r * 0.3, py - pad_r * 0.3, pad_r)
                if is_bottom:
                    # In bottom view: solder pads are extra shiny silver/tinned copper
                    pad_grad.setColorAt(0.0, QColor(245, 245, 250))
                    pad_grad.setColorAt(0.6, QColor(200, 205, 215))
                    pad_grad.setColorAt(1.0, QColor(160, 165, 175))
                    painter.setPen(QPen(QColor(120, 125, 135), 0.7))
                else:
                    # In top view: copper / ENIG gold annular rings
                    pad_grad.setColorAt(0.0, QColor(245, 210, 110))
                    pad_grad.setColorAt(0.7, theme["pad_outer"])
                    pad_grad.setColorAt(1.0, theme["pad_inner"])
                    painter.setPen(QPen(theme["pad_inner"].darker(120), 0.6))

                painter.setBrush(QBrush(pad_grad))
                painter.drawEllipse(QPointF(px, py), pad_r, pad_r)

                # Center through-hole
                painter.setBrush(hole_col)
                painter.setPen(QPen(QColor(25, 25, 28), 0.6))
                painter.drawEllipse(QPointF(px, py), hole_r, hole_r)

        # 7. Hover Reticle Highlight
        if cfg.is_valid_hole(self.hovered_col, self.hovered_row):
            hx, hy = cfg.grid_to_board_pos(self.hovered_col, self.hovered_row)
            painter.setPen(QPen(QColor(88, 101, 242, 220), 1.8))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(hx, hy), pad_r + 3.0, pad_r + 3.0)

            # Crosshairs
            painter.setPen(QPen(QColor(88, 101, 242, 160), 1.0, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(hx - pad_r - 6, hy), QPointF(hx + pad_r + 6, hy))
            painter.drawLine(QPointF(hx, hy - pad_r - 6), QPointF(hx, hy + pad_r + 6))

        # 8. Edge Resize Highlight
        if self.active_resize_edges:
            edge_color = QColor(129, 140, 248, 240) if self.is_resizing else QColor(88, 101, 242, 185)
            edge_pen = QPen(edge_color, 4.0 if self.is_resizing else 3.0)
            edge_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(edge_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            w, h = cfg.width_px, cfg.height_px
            if "L" in self.active_resize_edges:
                painter.drawLine(QPointF(0, 4), QPointF(0, h - 4))
            if "R" in self.active_resize_edges:
                painter.drawLine(QPointF(w, 4), QPointF(w, h - 4))
            if "T" in self.active_resize_edges:
                painter.drawLine(QPointF(4, 0), QPointF(w - 4, 0))
            if "B" in self.active_resize_edges:
                painter.drawLine(QPointF(4, h), QPointF(w - 4, h))

            if self.is_resizing:
                dim_text = f"{cfg.cols} x {cfg.rows}"
                font_dim = QFont("Consolas", 9, QFont.Weight.Bold)
                painter.setFont(font_dim)
                badge_w, badge_h = 74, 22
                bx = (w - badge_w) / 2
                by = -badge_h - 4 if "T" in self.active_resize_edges else (h + 6 if "B" in self.active_resize_edges else 8)
                if by < -10:
                    by = 8
                elif by + badge_h > h + 10:
                    by = h - badge_h - 8
                badge_rect = QRectF(bx, by, badge_w, badge_h)
                painter.setPen(QPen(QColor(129, 140, 248, 220), 1.2))
                painter.setBrush(QColor(22, 24, 30, 225))
                painter.drawRoundedRect(badge_rect, 5.0, 5.0)
                painter.setPen(QColor(235, 240, 255))
                painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, dim_text)
