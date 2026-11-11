"""
QGraphicsItem rendering procedural solder bridges and traces on the perfboard.
Supports realistic solder, net highlighting on hover (selection mode on back view), and ghost rendering.
"""
from PyQt6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem, QWidget
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QRadialGradient, QPainterPath
)
from PyQt6.QtCore import Qt, QRectF, QPointF
from app.models.board import BoardConfig
from app.models.solder import SolderManager, SolderTrace

class SolderItem(QGraphicsItem):
    def __init__(self, solder_mgr: SolderManager, config: BoardConfig):
        super().__init__()
        self.solder_mgr = solder_mgr
        self.config = config
        self.is_solder_mode = False
        self.highlighted_traces: list[SolderTrace] = []
        self.selected_traces: list[SolderTrace] = []
        self.current_drawing_segment: tuple[tuple[int, int], tuple[int, int]] | None = None

        self.setZValue(4)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self.config.width_px, self.config.height_px)

    def set_solder_mode(self, active: bool):
        if self.is_solder_mode != active:
            self.is_solder_mode = active
            self.update()

    def set_highlighted_trace(self, trace: SolderTrace | None):
        self.set_highlighted_traces([trace] if trace else [])

    def set_highlighted_traces(self, traces: list[SolderTrace]):
        if self.highlighted_traces != traces:
            self.highlighted_traces = list(traces)
            self.update()

    def set_selected_trace(self, trace: SolderTrace | None):
        self.set_selected_traces([trace] if trace else [])

    def set_selected_traces(self, traces: list[SolderTrace]):
        if self.selected_traces != traces:
            self.selected_traces = list(traces)
            self.update()

    def _draw_trace_halo(
        self,
        painter: QPainter,
        traces: list[SolderTrace],
        outer_color: QColor,
        outer_w: float,
        outer_pad_r: float,
        inner_color: QColor,
        inner_w: float,
    ):
        """Draws multi-layer glowing halo under solder traces and pads."""
        cfg = self.config
        outer_pen = QPen(outer_color, outer_w, Qt.PenStyle.SolidLine,
                         Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(outer_pen)
        for trace in traces:
            for h1, h2 in trace.segments:
                p1 = QPointF(*cfg.grid_to_board_pos(*h1))
                p2 = QPointF(*cfg.grid_to_board_pos(*h2))
                painter.drawLine(p1, p2)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(outer_color)
        for trace in traces:
            for col, row in trace.holes:
                px, py = cfg.grid_to_board_pos(col, row)
                painter.drawEllipse(QPointF(px, py), outer_pad_r, outer_pad_r)

        inner_pen = QPen(inner_color, inner_w, Qt.PenStyle.SolidLine,
                         Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(inner_pen)
        for trace in traces:
            for h1, h2 in trace.segments:
                p1 = QPointF(*cfg.grid_to_board_pos(*h1))
                p2 = QPointF(*cfg.grid_to_board_pos(*h2))
                painter.drawLine(p1, p2)

    def set_current_drawing(self, seg: tuple[tuple[int, int], tuple[int, int]] | None):
        self.current_drawing_segment = seg
        self.update()

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget = None):
        cfg = self.config
        is_bottom = (cfg.view_side == "bottom")
        is_transparent = bool(getattr(cfg, "transparent", False))

        # In top view: render if solder mode is ACTIVE (ghost) OR Transparent mode is ON (real back-side solder)
        if not is_bottom and not self.is_solder_mode and not is_transparent:
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        segments = list(self.solder_mgr.get_all_segments())
        if self.current_drawing_segment:
            segments.append(self.current_drawing_segment)

        if not segments and not self.solder_mgr.get_all_holes():
            painter.restore()
            return

        pad_r = cfg.pad_radius_px * 0.85
        solder_stroke_w = pad_r * 1.8

        if is_bottom or is_transparent:
            # --- REALISTIC SOLDER (BACK SIDE, OR THROUGH-BOARD IN TRANSPARENT FRONT VIEW) ---

            # 0a. Glowing Net Highlight (when hovering in selection mode)
            if self.highlighted_traces:
                self._draw_trace_halo(
                    painter, self.highlighted_traces,
                    QColor(255, 215, 0, 130), solder_stroke_w + 8.0, pad_r + 4.0,
                    QColor(255, 255, 140, 230), solder_stroke_w + 3.0,
                )

            # 0b. Persistent Selection Halo (when a solder path is selected)
            if self.selected_traces:
                self._draw_trace_halo(
                    painter, self.selected_traces,
                    QColor(88, 101, 242, 175), solder_stroke_w + 10.5, pad_r + 5.2,
                    QColor(56, 189, 248, 240), solder_stroke_w + 5.0,
                )

            # 1. Outer metallic solder base
            pen_base = QPen(QColor(140, 145, 155), solder_stroke_w, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen_base)
            for h1, h2 in segments:
                p1 = QPointF(*cfg.grid_to_board_pos(*h1))
                p2 = QPointF(*cfg.grid_to_board_pos(*h2))
                painter.drawLine(p1, p2)

            # Draw pads for all soldered holes
            painter.setPen(Qt.PenStyle.NoPen)
            for col, row in self.solder_mgr.get_all_holes():
                px, py = cfg.grid_to_board_pos(col, row)
                painter.setBrush(QColor(140, 145, 155))
                painter.drawEllipse(QPointF(px, py), pad_r, pad_r)

            # 2. Main tinned silver body
            pen_body = QPen(QColor(210, 215, 225), solder_stroke_w - 2.5, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen_body)
            for h1, h2 in segments:
                p1 = QPointF(*cfg.grid_to_board_pos(*h1))
                p2 = QPointF(*cfg.grid_to_board_pos(*h2))
                painter.drawLine(p1, p2)

            for col, row in self.solder_mgr.get_all_holes():
                px, py = cfg.grid_to_board_pos(col, row)
                solder_grad = QRadialGradient(px - pad_r * 0.3, py - pad_r * 0.3, pad_r)
                solder_grad.setColorAt(0.0, QColor(250, 252, 255))
                solder_grad.setColorAt(0.6, QColor(220, 225, 235))
                solder_grad.setColorAt(1.0, QColor(165, 170, 180))
                painter.setBrush(QBrush(solder_grad))
                painter.drawEllipse(QPointF(px, py), pad_r - 1.2, pad_r - 1.2)

            # 3. Specular highlight spine
            pen_hi = QPen(QColor(255, 255, 255, 220), solder_stroke_w * 0.32, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen_hi)
            for h1, h2 in segments:
                p1 = QPointF(*cfg.grid_to_board_pos(*h1))
                p2 = QPointF(*cfg.grid_to_board_pos(*h2))
                painter.drawLine(p1, p2)

            # 4. Hole centers: small depression showing soldered connection
            pin_r = cfg.hole_radius_px * 0.7
            painter.setPen(QPen(QColor(80, 85, 95), 0.8))
            for col, row in self.solder_mgr.get_all_holes():
                px, py = cfg.grid_to_board_pos(col, row)
                lead_grad = QRadialGradient(px - 0.5, py - 0.5, pin_r)
                lead_grad.setColorAt(0.0, QColor(240, 240, 250))
                lead_grad.setColorAt(0.8, QColor(130, 135, 145))
                lead_grad.setColorAt(1.0, QColor(70, 75, 85))
                painter.setBrush(QBrush(lead_grad))
                painter.drawEllipse(QPointF(px, py), pin_r, pin_r)

        else:
            # --- GHOST SOLDER (FRONT VIEW WHILE IN SOLDER MODE) ---
            ghost_pen = QPen(QColor(100, 210, 255, 140), solder_stroke_w * 0.75, Qt.PenStyle.DashLine,
                             Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(ghost_pen)
            for h1, h2 in segments:
                p1 = QPointF(*cfg.grid_to_board_pos(*h1))
                p2 = QPointF(*cfg.grid_to_board_pos(*h2))
                painter.drawLine(p1, p2)

            painter.setPen(QPen(QColor(100, 210, 255, 180), 1.2))
            painter.setBrush(QColor(80, 190, 240, 60))
            for col, row in self.solder_mgr.get_all_holes():
                px, py = cfg.grid_to_board_pos(col, row)
                painter.drawEllipse(QPointF(px, py), pad_r * 0.8, pad_r * 0.8)

        painter.restore()
