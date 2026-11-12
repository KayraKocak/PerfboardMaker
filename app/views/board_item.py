"""
Procedural Perfboard QGraphicsItem.
Renders the PCB substrate, donut pads, drilled holes, coordinate rulers, and corner mounting holes.
"""
import math
from PyQt6.QtWidgets import QGraphicsItem
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QRadialGradient, QLinearGradient,
    QPainterPath, QTransform, QPolygonF
)
from PyQt6.QtCore import Qt, QRectF, QPointF
from app.models.board import BoardConfig, BoardCutout, col_index_to_name

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
        self.shape_mode_active = False
        self.selected_cutout_uid: str | None = None
        self.selected_vertex_idx: int | None = None
        self.selected_vertex_indices: list[int] = []
        self.drawing_custom_cutout: BoardCutout | None = None
        self.drawing_custom_cursor: QPointF | None = None
        self.custom_snap_guides: list[tuple[str, float]] = []
        self.bevel_guide_line: tuple[QPointF, QPointF] | None = None
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setZValue(0)  # Board is background

    def set_shape_mode(self, active: bool):
        if self.shape_mode_active != active:
            self.shape_mode_active = active
            self.update()

    def set_selected_cutout(self, uid: str | None):
        if self.selected_cutout_uid != uid:
            self.selected_cutout_uid = uid
            self.selected_vertex_idx = None
            self.selected_vertex_indices = []
            self.update()

    def set_selected_vertex(self, idx: int | None):
        new_list = [idx] if idx is not None else []
        if self.selected_vertex_idx != idx or self.selected_vertex_indices != new_list:
            self.selected_vertex_idx = idx
            self.selected_vertex_indices = new_list
            self.update()

    def set_selected_vertices(self, indices: list[int]):
        new_list = list(indices)
        new_primary = new_list[-1] if new_list else None
        if self.selected_vertex_indices != new_list or self.selected_vertex_idx != new_primary:
            self.selected_vertex_indices = new_list
            self.selected_vertex_idx = new_primary
            self.update()

    def _cutout_display_rect(self, cutout: BoardCutout) -> QRectF:
        if self.config.view_side == "bottom":
            bx = self.config.width_px - (cutout.x + cutout.w)
        else:
            bx = cutout.x
        return QRectF(bx, cutout.y, cutout.w, cutout.h)

    def _cutout_display_rotation(self, cutout: BoardCutout) -> float:
        return -cutout.rotation if self.config.view_side == "bottom" else cutout.rotation

    def _cutout_display_vertices(self, cutout: BoardCutout) -> list[QPointF]:
        is_bottom = (self.config.view_side == "bottom")
        w_board = self.config.width_px
        return [
            QPointF((w_board - vx) if is_bottom else vx, vy)
            for vx, vy in cutout.vertices
        ]

    def _cutout_display_transform(self, cutout: BoardCutout, rect: QRectF) -> QTransform:
        rot = self._cutout_display_rotation(cutout)
        t = QTransform()
        if abs(rot) > 1e-6:
            c = rect.center()
            t.translate(c.x(), c.y())
            t.rotate(rot)
            t.translate(-c.x(), -c.y())
        return t

    def _cutout_display_path(self, cutout: BoardCutout) -> QPainterPath:
        rect = self._cutout_display_rect(cutout)
        path = QPainterPath()
        if cutout.shape == "custom":
            pts = self._cutout_display_vertices(cutout)
            if len(pts) >= 3:
                path.addPolygon(QPolygonF(pts))
                path.closeSubpath()
        elif cutout.shape == "rect":
            path.addRect(rect)
        elif cutout.shape == "rounded_rect":
            cr = max(0.0, min(cutout.corner_radius, rect.width() * 0.5, rect.height() * 0.5))
            path.addRoundedRect(rect, cr, cr)
        elif cutout.shape in ("oval", "inverted_oval"):
            path.addEllipse(rect)
        t = self._cutout_display_transform(cutout, rect)
        return t.map(path) if not t.isIdentity() else path

    def _canvas_bg_color(self) -> QColor:
        scene = self.scene()
        if scene is not None and scene.backgroundBrush().style() != Qt.BrushStyle.NoBrush:
            return scene.backgroundBrush().color()
        return QColor("#1e1f22")

    def boundingRect(self) -> QRectF:
        # Extra 40px margin around board for shadow, edge resize highlights, rotation handles, and custom previews
        return QRectF(-40, -40, self.config.width_px + 80, self.config.height_px + 80)

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
                if cfg.is_hole_cut(c, r):
                    continue
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

        # 6b. Perfboard Cutout Shapes (rendered in canvas background color, no borders)
        if cfg.cutouts:
            bg_color = self._canvas_bg_color()
            board_clip = QRectF(-12, -12, cfg.width_px + 24, cfg.height_px + 24)
            painter.save()
            painter.setClipRect(board_clip)

            for cutout in cfg.cutouts:
                shape_path = self._cutout_display_path(cutout)
                if shape_path.isEmpty():
                    continue
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(bg_color)
                if cutout.is_inverted:
                    inv_path = QPainterPath()
                    inv_path.setFillRule(Qt.FillRule.OddEvenFill)
                    inv_path.addRect(board_clip)
                    inv_path.addPath(shape_path)
                    painter.drawPath(inv_path)
                else:
                    painter.drawPath(shape_path)

            painter.restore()

            # In Shape Perfboard mode, show interactive outlines, resize/rotation/vertex handles
            if self.shape_mode_active:
                painter.save()
                inv_zoom = 1.0 / max(0.15, abs(painter.worldTransform().m11()))
                for cutout in cfg.cutouts:
                    rect = self._cutout_display_rect(cutout)
                    shape_path = self._cutout_display_path(cutout)
                    if shape_path.isEmpty():
                        continue
                    is_sel = (cutout.uid == self.selected_cutout_uid)
                    outline_pen = QPen(
                        QColor(88, 101, 242, 235) if is_sel else QColor(148, 155, 164, 150),
                        1.8 if is_sel else 1.1,
                        Qt.PenStyle.SolidLine if is_sel else Qt.PenStyle.DashLine,
                    )
                    outline_pen.setCosmetic(True)
                    painter.setPen(outline_pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawPath(shape_path)

                    if is_sel:
                        t = self._cutout_display_transform(cutout, rect)
                        if cutout.shape in ("oval", "inverted_oval", "custom") or cutout.is_inverted:
                            box_pen = QPen(QColor(88, 101, 242, 110), 1.0, Qt.PenStyle.DashLine)
                            box_pen.setCosmetic(True)
                            painter.setPen(box_pen)
                            painter.drawPolygon(t.map(QPolygonF(rect)))

                        hs = 7.0 * inv_zoom
                        half = hs * 0.5
                        x1, y1, x2, y2 = rect.left(), rect.top(), rect.right(), rect.bottom()
                        xm, ym = (x1 + x2) * 0.5, (y1 + y2) * 0.5
                        local_handles = [
                            (x1, y1), (xm, y1), (x2, y1), (x2, ym),
                            (x2, y2), (xm, y2), (x1, y2), (x1, ym),
                        ]
                        top_mid = t.map(QPointF(xm, y1))
                        rot_pt = t.map(QPointF(xm, y1 - 22.0 * inv_zoom))
                        stem_pen = QPen(QColor(88, 101, 242, 220), 1.4)
                        stem_pen.setCosmetic(True)
                        painter.setPen(stem_pen)
                        painter.drawLine(top_mid, rot_pt)
                        handle_pen = QPen(QColor(255, 255, 255, 235), 1.0)
                        handle_pen.setCosmetic(True)
                        painter.setPen(handle_pen)
                        painter.setBrush(QColor(0, 200, 255))
                        rot_r = 4.5 * inv_zoom
                        painter.drawEllipse(rot_pt, rot_r, rot_r)

                        painter.setBrush(QColor(88, 101, 242))
                        for hx, hy in local_handles:
                            pt = t.map(QPointF(hx, hy))
                            painter.drawRect(QRectF(pt.x() - half, pt.y() - half, hs, hs))

                        if cutout.shape == "custom":
                            disp_verts = self._cutout_display_vertices(cutout)
                            v_pen = QPen(QColor(255, 255, 255, 240), 1.2)
                            v_pen.setCosmetic(True)
                            painter.setPen(v_pen)
                            for v_idx, v_pt in enumerate(disp_verts):
                                w_pt = t.map(v_pt)
                                is_v_sel = (v_idx == self.selected_vertex_idx) or (v_idx in self.selected_vertex_indices)
                                painter.setBrush(QColor(255, 196, 0) if is_v_sel else QColor(0, 220, 180))
                                r_v = (5.5 if is_v_sel else 4.0) * inv_zoom
                                painter.drawEllipse(w_pt, r_v, r_v)
                painter.restore()

        # 6c. Live Custom Shape drawing preview (open polygon)
        if self.shape_mode_active and self.drawing_custom_cutout is not None:
            pts = self._cutout_display_vertices(self.drawing_custom_cutout)
            if pts:
                painter.save()
                inv_zoom = 1.0 / max(0.15, abs(painter.worldTransform().m11()))
                # X/Y snap guides
                if self.custom_snap_guides:
                    guide_pen = QPen(QColor(0, 230, 255, 170), 1.0, Qt.PenStyle.DashLine)
                    guide_pen.setCosmetic(True)
                    painter.setPen(guide_pen)
                    for axis, val in self.custom_snap_guides:
                        if axis == "x":
                            painter.drawLine(QPointF(val, -40), QPointF(val, cfg.height_px + 40))
                        else:
                            painter.drawLine(QPointF(-40, val), QPointF(cfg.width_px + 40, val))

                edge_pen = QPen(QColor(0, 230, 255, 230), 1.8)
                edge_pen.setCosmetic(True)
                painter.setPen(edge_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                for i in range(len(pts) - 1):
                    painter.drawLine(pts[i], pts[i + 1])
                if self.drawing_custom_cursor is not None:
                    rb_pen = QPen(QColor(0, 230, 255, 170), 1.4, Qt.PenStyle.DashLine)
                    rb_pen.setCosmetic(True)
                    painter.setPen(rb_pen)
                    painter.drawLine(pts[-1], self.drawing_custom_cursor)
                    if len(pts) >= 2:
                        close_pen = QPen(QColor(0, 230, 255, 90), 1.0, Qt.PenStyle.DotLine)
                        close_pen.setCosmetic(True)
                        painter.setPen(close_pen)
                        painter.drawLine(self.drawing_custom_cursor, pts[0])

                v_pen = QPen(QColor(255, 255, 255, 240), 1.2)
                v_pen.setCosmetic(True)
                painter.setPen(v_pen)
                for i, pt in enumerate(pts):
                    painter.setBrush(QColor(255, 196, 0) if i == 0 else QColor(0, 220, 180))
                    r_v = (5.0 if i == 0 else 4.0) * inv_zoom
                    painter.drawEllipse(pt, r_v, r_v)
                painter.restore()

        # 6d. Bevel distance guide line
        if self.shape_mode_active and self.bevel_guide_line is not None:
            p_start, p_cur = self.bevel_guide_line
            painter.save()
            inv_zoom = 1.0 / max(0.15, abs(painter.worldTransform().m11()))
            guide_pen = QPen(QColor(255, 210, 80, 230), 1.5, Qt.PenStyle.DashLine)
            guide_pen.setCosmetic(True)
            painter.setPen(guide_pen)
            painter.drawLine(p_start, p_cur)

            dot_pen = QPen(QColor(255, 255, 255, 230), 1.0)
            dot_pen.setCosmetic(True)
            painter.setPen(dot_pen)
            painter.setBrush(QColor(255, 196, 0))
            r_dot = 3.5 * inv_zoom
            painter.drawEllipse(p_start, r_dot, r_dot)
            painter.drawEllipse(p_cur, r_dot, r_dot)

            dist_px = math.hypot(p_cur.x() - p_start.x(), p_cur.y() - p_start.y())
            mid = QPointF((p_start.x() + p_cur.x()) * 0.5, (p_start.y() + p_cur.y()) * 0.5)
            painter.translate(mid)
            painter.scale(inv_zoom, inv_zoom)
            font = QFont("Consolas", 9)
            font.setBold(True)
            painter.setFont(font)
            label = f"{dist_px:.1f} px"
            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(label) + 10
            th = fm.height() + 4
            box = QRectF(-tw * 0.5, -th - 6, tw, th)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(20, 22, 28, 200))
            painter.drawRoundedRect(box, 3.0, 3.0)
            painter.setPen(QColor(255, 220, 110))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, label)
            painter.restore()

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
