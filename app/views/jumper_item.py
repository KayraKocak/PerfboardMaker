"""
QGraphicsItem rendering a straight insulated jumper wire with interactive endpoints and bend points.
No curves: all segments are straight lines.
Supports dragging start/end handles to new holes, and shift-clicking to insert bends.
"""
import math
from PyQt6.QtWidgets import (
    QGraphicsItem, QStyleOptionGraphicsItem, QWidget, QGraphicsSceneMouseEvent
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPainterPath, QPainterPathStroker, QCursor
)
from PyQt6.QtCore import Qt, QRectF, QPointF
from app.models.board import BoardConfig
from app.models.jumper import JumperWire

class JumperItem(QGraphicsItem):
    def __init__(self, jumper: JumperWire, config: BoardConfig):
        super().__init__()
        self.jumper = jumper
        self.config = config

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(16)

        # Handle interaction state
        self._dragging_handle_idx: int | None = None
        self._hovered_handle_idx: int | None = None
        self.is_net_highlighted: bool = False

    def set_net_highlighted(self, active: bool):
        if self.is_net_highlighted != active:
            self.is_net_highlighted = active
            self.setZValue(25 if active else 16)
            self.update()

    def _get_pixel_points(self) -> list[QPointF]:
        """Returns pixel positions of start, all bends, and end."""
        pts = self.jumper.all_points()
        return [QPointF(*self.config.grid_to_board_pos(c, r)) for c, r in pts]

    def _get_wire_path(self) -> QPainterPath:
        """Constructs straight line path through start, all bends, and end."""
        pix_pts = self._get_pixel_points()
        path = QPainterPath()
        if not pix_pts:
            return path

        path.moveTo(pix_pts[0])
        for pt in pix_pts[1:]:
            path.lineTo(pt)
        return path

    def shape(self) -> QPainterPath:
        """Returns thick clickable path along the wire and handles."""
        wire_path = self._get_wire_path()
        stroker = QPainterPathStroker()
        stroker.setWidth(12.0)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        path = stroker.createStroke(wire_path)

        # Include handles in shape
        for pt in self._get_pixel_points():
            path.addEllipse(pt, 8.0, 8.0)
        return path

    def boundingRect(self) -> QRectF:
        return self.shape().boundingRect().adjusted(-8, -8, 8, 8)

    def get_handle_at(self, scene_pos: QPointF, threshold: float = 8.5) -> int | None:
        """
        Returns point index (0 = start, 1..N-2 = bends, N-1 = end) if scene_pos is close to a handle,
        or None.
        """
        pix_pts = self._get_pixel_points()
        thresh_sq = threshold ** 2
        for idx, pt in enumerate(pix_pts):
            dist_sq = (scene_pos.x() - pt.x())**2 + (scene_pos.y() - pt.y())**2
            if dist_sq <= thresh_sq:
                return idx
        return None

    def get_segment_index_at(self, scene_pos: QPointF, threshold: float = 10.0) -> int | None:
        """
        Finds which segment of the wire (0 to N-2) the point is closest to.
        Used for inserting bend points along the wire body.
        """
        pix_pts = self._get_pixel_points()
        best_seg = None
        best_dist = threshold

        for i in range(len(pix_pts) - 1):
            p1 = pix_pts[i]
            p2 = pix_pts[i + 1]

            # Distance from point to line segment
            dx = p2.x() - p1.x()
            dy = p2.y() - p1.y()
            len_sq = dx * dx + dy * dy

            if len_sq == 0:
                dist = math.hypot(scene_pos.x() - p1.x(), scene_pos.y() - p1.y())
            else:
                t = max(0.0, min(1.0, ((scene_pos.x() - p1.x()) * dx + (scene_pos.y() - p1.y()) * dy) / len_sq))
                proj_x = p1.x() + t * dx
                proj_y = p1.y() + t * dy
                dist = math.hypot(scene_pos.x() - proj_x, scene_pos.y() - proj_y)

            if dist < best_dist:
                best_dist = dist
                best_seg = i

        return best_seg

    def _paint_wire_geometry(
        self,
        painter: QPainter,
        wire_path: QPainterPath,
        pix_pts: list[QPointF],
        base_color: QColor,
        wire_w: float,
        draw_shadow: bool = True,
    ):
        # 1. Wire Drop Shadow
        if draw_shadow:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            shadow_pen = QPen(QColor(0, 0, 0, 55), wire_w + 2.0, Qt.PenStyle.SolidLine,
                              Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(shadow_pen)
            painter.save()
            painter.translate(1.5, 2.0)
            painter.drawPath(wire_path)
            painter.restore()

        # 2. Outer dark border / insulation sleeve rim
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(base_color.darker(170), wire_w + 1.2, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(wire_path)

        # 3. Main insulation core color (straight segments)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(base_color, wire_w, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(wire_path)

        # 4. Cylindrical specular highlight streak
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 120), wire_w * 0.35, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(wire_path)

        # 5. Wire terminal ends entering hole (ONLY at start and end)
        pin_r = 3.0
        if len(pix_pts) >= 2:
            for pt in (pix_pts[0], pix_pts[-1]):
                painter.setPen(QPen(QColor(70, 75, 80), 0.8))
                painter.setBrush(QColor(220, 225, 230))
                painter.drawEllipse(pt, pin_r, pin_r)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(100, 105, 115))
                painter.drawEllipse(pt, pin_r * 0.45, pin_r * 0.45)
            painter.setBrush(Qt.BrushStyle.NoBrush)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget = None):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        cfg = self.config
        is_same_side = (cfg.view_side == self.jumper.side)
        is_transparent = bool(getattr(cfg, "transparent", False))
        base_color = QColor(self.jumper.color)

        wire_path = self._get_wire_path()
        pix_pts = self._get_pixel_points()
        wire_w = 4.6

        if is_same_side:
            # 0. Glowing Net Highlight (when part of active conductive net)
            if self.is_net_highlighted:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                hi_pen_outer = QPen(QColor(255, 215, 0, 160), wire_w + 9.0, Qt.PenStyle.SolidLine,
                                    Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
                painter.setPen(hi_pen_outer)
                painter.drawPath(wire_path)

                hi_pen_inner = QPen(QColor(255, 255, 140, 240), wire_w + 4.0, Qt.PenStyle.SolidLine,
                                    Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
                painter.setPen(hi_pen_inner)
                painter.drawPath(wire_path)

                if len(pix_pts) >= 2:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(255, 215, 0, 180))
                    for pt in (pix_pts[0], pix_pts[-1]):
                        painter.drawEllipse(pt, 6.0, 6.0)
                    painter.setBrush(Qt.BrushStyle.NoBrush)

            self._paint_wire_geometry(painter, wire_path, pix_pts, base_color, wire_w, draw_shadow=True)

        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if self.is_net_highlighted:
                # --- GLOWING GHOST OF OPPOSITE-SIDE JUMPER IN SAME HIGHLIGHT COLOR ---
                # 1. Outer radiant glow halo
                ghost_glow = QPen(QColor(255, 215, 0, 140), wire_w + 8.0, Qt.PenStyle.SolidLine,
                                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
                painter.setPen(ghost_glow)
                painter.drawPath(wire_path)

                # 2. Dashed ghost wire body in vivid gold
                ghost_dash = QPen(QColor(255, 220, 60, 230), wire_w + 1.5, Qt.PenStyle.DashLine,
                                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
                painter.setPen(ghost_dash)
                painter.drawPath(wire_path)

                # 3. Bright inner spine
                ghost_inner = QPen(QColor(255, 255, 190, 240), wire_w * 0.5, Qt.PenStyle.SolidLine,
                                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
                painter.setPen(ghost_inner)
                painter.drawPath(wire_path)

                # 4. Glowing terminal hole rings at start and end
                if len(pix_pts) >= 2:
                    for pt in (pix_pts[0], pix_pts[-1]):
                        # Outer golden halo
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(QColor(255, 215, 0, 180))
                        painter.drawEllipse(pt, 6.5, 6.5)
                        # Golden ring
                        painter.setPen(QPen(QColor(255, 255, 140), 2.0))
                        painter.setBrush(QColor(25, 28, 35))
                        painter.drawEllipse(pt, 4.0, 4.0)
                    painter.setBrush(Qt.BrushStyle.NoBrush)

                # 5. Diamonds for any bend points
                for pt in pix_pts[1:-1]:
                    painter.setPen(QPen(QColor(255, 255, 200), 1.5))
                    painter.setBrush(QColor(255, 215, 0, 220))
                    painter.drawRect(QRectF(pt.x() - 3.5, pt.y() - 3.5, 7.0, 7.0))
                painter.setBrush(Qt.BrushStyle.NoBrush)

            elif is_transparent:
                # Opposite side in Transparent mode: paint real jumper wire semi-transparently through board
                painter.save()
                painter.setOpacity(0.50)
                self._paint_wire_geometry(painter, wire_path, pix_pts, base_color, wire_w, draw_shadow=False)
                painter.restore()

            else:
                # Opposite side when not highlighted: subtle translucent outline
                painter.setBrush(Qt.BrushStyle.NoBrush)
                ghost_color = QColor(base_color.red(), base_color.green(), base_color.blue(), 50)
                painter.setPen(QPen(ghost_color, wire_w * 0.8, Qt.PenStyle.DashLine,
                                    Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                painter.drawPath(wire_path)

                # Mark hole pins
                if len(pix_pts) >= 2:
                    for pt in (pix_pts[0], pix_pts[-1]):
                        painter.setPen(QPen(QColor(base_color.red(), base_color.green(), base_color.blue(), 100), 1.0))
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        painter.drawEllipse(pt, 3.5, 3.5)

        # 6. Selection / Handle Visuals
        if self.isSelected() or self._hovered_handle_idx is not None:
            # Dashed selection halo
            sel_pen = QPen(QColor(88, 101, 242, 220), wire_w + 3.0, Qt.PenStyle.DashLine,
                           Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(sel_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(wire_path)

            # Draw Endpoint Handles (Start & End)
            handle_r = 4.5
            for idx in (0, len(pix_pts) - 1):
                pt = pix_pts[idx]
                is_active = (self._hovered_handle_idx == idx or self._dragging_handle_idx == idx)
                painter.setPen(QPen(QColor(255, 255, 255), 1.5))
                painter.setBrush(QColor(88, 101, 242) if is_active else QColor(40, 42, 48))
                painter.drawEllipse(pt, handle_r, handle_r)

            # Draw Bend Handles (Diamonds/Squares along the wire)
            for idx in range(1, len(pix_pts) - 1):
                pt = pix_pts[idx]
                is_active = (self._hovered_handle_idx == idx or self._dragging_handle_idx == idx)
                painter.setPen(QPen(QColor(255, 255, 255), 1.5))
                painter.setBrush(QColor(240, 180, 40) if is_active else QColor(60, 64, 75))
                painter.drawRect(QRectF(pt.x() - 4.0, pt.y() - 4.0, 8.0, 8.0))

        painter.restore()

    def hoverMoveEvent(self, event):
        scene_pos = event.scenePos()
        handle_idx = self.get_handle_at(scene_pos)
        if self._hovered_handle_idx != handle_idx:
            self._hovered_handle_idx = handle_idx
            self.update()

        if handle_idx is not None:
            if handle_idx == 0:
                self.setToolTip("Start Pin: Drag to move to another hole")
            elif handle_idx == len(self.jumper.all_points()) - 1:
                self.setToolTip("End Pin: Drag to move to another hole")
            else:
                self.setToolTip(f"Bend Point #{handle_idx}: Drag to reposition")
        else:
            side_txt = "Top" if self.jumper.side == "top" else "Bottom"
            bends_cnt = len(self.jumper.bends)
            bends_txt = f" | Bends: {bends_cnt}" if bends_cnt > 0 else ""
            self.setToolTip(
                f"Jumper Wire ({self.jumper.color})\n"
                f"Side: {side_txt}{bends_txt}\n"
                f"From: ({self.jumper.start_col}, {self.jumper.start_row}) "
                f"To: ({self.jumper.end_col}, {self.jumper.end_row})\n"
                f"Length: {self.jumper.length_holes:.1f} holes ({self.jumper.length_mm:.1f} mm)"
            )
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        if self._hovered_handle_idx is not None:
            self._hovered_handle_idx = None
            self.update()
        super().hoverLeaveEvent(event)
