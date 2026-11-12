"""
Interactive QGraphicsView canvas for perfboard CAD layout.
Supports smooth zoom, pan, drag-and-drop, ghost placement, and shortcuts.
Includes Select (1), Solder (2), Jumper (3) modes with:
- Solder erase with LCtrl
- Solder conductive net hover highlight (bottom view)
- Straight jumpers with draggable endpoints
- Shift+Click bend points insertion and dragging
"""
import copy
import math
import uuid
from typing import Any
from collections import deque
from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsItem
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QWheelEvent, QMouseEvent, QKeyEvent, QTransform, QKeySequence, QCursor
)
from PyQt6.QtCore import Qt, QPointF, pyqtSignal, QRectF
from app.models.board import BoardConfig, BoardCutout, col_index_to_name
from app.models.placed_component import PlacedComponent
from app.models.solder import SolderManager, SolderTrace, ConnectedPinInfo, SelectedSolderPath
from app.models.jumper import JumperWire, DEFAULT_JUMPER_COLOR
from app.components.registry import REGISTRY
from app.views.board_item import BoardItem
from app.views.component_item import ComponentItem
from app.views.solder_item import SolderItem
from app.views.jumper_item import JumperItem
from app.utils.logger import log_keypress, log_action
from app.models.history import HistoryManager
from app.models.project import (
    serialize_state, save_project_file, load_project_file,
    PROJECT_FILE_EXTENSION, PROJECT_FILE_FILTER
)
from app.models.router import (
    AutoConnectSettings, AutoConnectTarget, AutoConnectGroup,
    get_group_color, connect_targets, connect_multiple_groups,
    extract_connected_pin_groups, partition_offgrid_jumpers
)
from app.views.autoconnect_overlay import AutoConnectOverlayItem

def bresenham_line(c1: int, r1: int, c2: int, r2: int) -> list[tuple[int, int]]:
    """Returns grid hole coordinates along a straight line using Bresenham's algorithm."""
    holes = []
    dx = abs(c2 - c1)
    dy = abs(r2 - r1)
    sx = 1 if c1 < c2 else -1
    sy = 1 if r1 < r2 else -1
    err = dx - dy
    cx, cy = c1, r1

    while True:
        holes.append((cx, cy))
        if cx == c2 and cy == r2:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            cx += sx
        if e2 < dx:
            err += dx
            cy += sy

    return holes

def dist_to_segment(p: QPointF, p1: QPointF, p2: QPointF) -> float:
    dx = p2.x() - p1.x()
    dy = p2.y() - p1.y()
    len_sq = dx * dx + dy * dy
    if len_sq == 0:
        return math.hypot(p.x() - p1.x(), p.y() - p1.y())
    t = max(0.0, min(1.0, ((p.x() - p1.x()) * dx + (p.y() - p1.y()) * dy) / len_sq))
    return math.hypot(p.x() - (p1.x() + t * dx), p.y() - (p1.y() + t * dy))


class CanvasView(QGraphicsView):
    # Signals
    hover_hole_changed = pyqtSignal(int, int, str)  # col, row, col_name
    selection_changed = pyqtSignal(object)          # ComponentItem or JumperItem or None
    view_side_changed = pyqtSignal(str)             # "top" or "bottom"
    component_placed = pyqtSignal(object)           # PlacedComponent
    mode_changed = pyqtSignal(str)                  # "select", "solder", "jumper", "autoconnect"
    autoconnect_selection_changed = pyqtSignal(list) # list of AutoConnectTarget
    autoconnect_groups_changed = pyqtSignal(list)    # list of AutoConnectGroup
    autoconnect_completed = pyqtSignal(dict)        # result dictionary
    board_resized = pyqtSignal(int, int)            # cols, rows
    cutout_selection_changed = pyqtSignal(object)   # str uid or None
    cutout_tool_synced = pyqtSignal(str)            # active cutout shape synced back to inspector
    objects_unhidden = pyqtSignal()                 # emitted when all hidden objects are unhidden
    _clipboard_payload: dict | None = None

    def __init__(self, config: BoardConfig, parent=None, primary_view: "CanvasView | None" = None):
        super().__init__(parent)
        self.config = config
        self._primary_view: CanvasView | None = primary_view
        self._partner_view: CanvasView | None = None
        self._double_view_active: bool = False
        self._double_view_badge: str = ""
        self._syncing_camera: bool = False
        self._syncing_partner: bool = False
        self._syncing_selection: bool = False
        self._mirrored_cursor_scene_pos: QPointF | None = None

        self.scene = QGraphicsScene(self)
        self.scene.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex)
        self.scene.setBackgroundBrush(QBrush(QColor("#1e1f22")))
        self.setScene(self.scene)

        # Mode
        self.current_mode = "select"  # "select", "solder", "jumper", "autoconnect", "shape"
        self.active_jumper_color = DEFAULT_JUMPER_COLOR

        # Shape Perfboard state
        self.active_cutout_shape: str = "rect"
        self.active_cutout_corner_radius: float = 12.0
        self.active_cutout_inverted: bool = False
        self.selected_cutout_uid: str | None = None
        self.selected_vertex_idx: int | None = None
        self.selected_vertex_indices: list[int] = []
        self._cutout_drag_mode: str | None = None
        self._cutout_resize_handle: str = ""
        self._cutout_drag_start_board: QPointF = QPointF()
        self._cutout_orig_rect: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
        self._cutout_orig_vertices: list[tuple[float, float]] = []
        self._cutout_rot_start_angle: float = 0.0
        self._cutout_rot_orig: float = 0.0
        self._cutout_drag_changed: bool = False
        self._cutout_click_hits: list[BoardCutout] = []
        self._cutout_click_was_selected: bool = False
        self._drawing_custom_cutout: BoardCutout | None = None
        self._bevel_active: bool = False
        self._bevel_cutout_uid: str | None = None
        self._bevel_vertex_idx: int = -1
        self._bevel_vertex_indices: list[int] = []
        self._bevel_orig_vertices: list[tuple[float, float]] = []
        self._bevel_segments: int = 4
        self._bevel_last_dist: float = 20.0
        self._bevel_start_pos: QPointF | None = None

        # AutoConnect mode state & overlay (shared when secondary view)
        if primary_view is not None:
            self.autoconnect_settings = primary_view.autoconnect_settings
            self.autoconnect_selected_targets = primary_view.autoconnect_selected_targets
            self.autoconnect_groups = primary_view.autoconnect_groups
            self.solder_mgr = primary_view.solder_mgr
            self.jumpers = primary_view.jumpers
            self.placed_components = primary_view.placed_components
            self.history = primary_view.history
        else:
            self.autoconnect_settings = AutoConnectSettings()
            self.autoconnect_selected_targets: list[AutoConnectTarget] = []
            self.autoconnect_groups: list[AutoConnectGroup] = []
            self.solder_mgr = SolderManager()
            self.jumpers: list[JumperWire] = []
            self.placed_components: list[PlacedComponent] = []

        self._last_autoconnect_targets: list[AutoConnectTarget] | None = None
        self._last_autoconnect_groups: list[AutoConnectGroup] | None = None
        self._is_last_action_autoconnect: bool = False
        self._suppress_invalidation: bool = False

        # Rendering hints
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

        # Interaction state
        self._is_panning = False
        self._pan_start_pos = QPointF()
        self._space_pressed = False
        self._shift_pressed = False
        self._ctrl_pressed = False
        self._zoom_factor = 1.0

        # Perfboard edge resize state
        self._hovered_resize_edges: str = ""
        self._board_resize_active: bool = False
        self._board_resize_edges: str = ""
        self._board_resize_changed: bool = False
        self._board_resize_last_vp_pos = QPointF()
        self._board_resize_accum_x: float = 0.0
        self._board_resize_accum_y: float = 0.0
        self._board_resize_scroll_rem_x: float = 0.0
        self._board_resize_scroll_rem_y: float = 0.0

        # Placement mode state (toolbox)
        self.placement_type_id: str | None = None
        self.placement_rotation: int = 0
        self.placement_ghost: PlacedComponent | None = None
        self.placement_ghost_item: ComponentItem | None = None

        # Solder interactive drawing / erase state
        self._solder_drag_active = False
        self._solder_erase_active = False
        self._solder_start_hole: tuple[int, int] | None = None
        self._solder_last_hole: tuple[int, int] | None = None

        # Jumper interactive drawing state
        self.jumper_items: list[JumperItem] = []
        self._jumper_drag_active = False
        self._jumper_start_hole: tuple[int | float, int | float] | None = None
        self._jumper_start_pin: tuple[str, int, str] | None = None
        self._jumper_preview_item: JumperItem | None = None

        # Jumper handle dragging state (moving endpoints or bend points)
        self._jumper_handle_drag_item: JumperItem | None = None
        self._jumper_handle_drag_idx: int | None = None

        # Scene item wrappers
        self.component_items: list[ComponentItem] = []

        # Board item & Solder item
        self.board_item = BoardItem(self.config)
        self.scene.addItem(self.board_item)

        self._selected_solder_trace: SolderTrace | None = None
        self.solder_item = SolderItem(self.solder_mgr, self.config)
        self._update_solder_z()
        self.scene.addItem(self.solder_item)

        # AutoConnect Overlay Item
        self.autoconnect_overlay = AutoConnectOverlayItem(self.config)
        self.scene.addItem(self.autoconnect_overlay)

        self.scene.selectionChanged.connect(self._on_scene_selection_changed)
        self.horizontalScrollBar().valueChanged.connect(self._on_view_scrolled)
        self.verticalScrollBar().valueChanged.connect(self._on_view_scrolled)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.reset_scene_rect()

        # 200-step Undo/Redo history (created only on primary view)
        if primary_view is None:
            self.history = HistoryManager(max_depth=200)
            self.history.reset(self.serialize_state())

    def link_partner(self, partner: "CanvasView"):
        """Links this CanvasView symmetrically with its Double-View partner."""
        self._partner_view = partner
        partner._partner_view = self
        self._sync_config_to(partner)
        partner._sync_from_partner()

    def _update_solder_z(self):
        board_hidden = not self.board_item.isVisible()
        if self.config.view_side != "bottom" and bool(getattr(self.config, "transparent", False)) and not board_hidden:
            self.solder_item.setZValue(-1)
        else:
            self.solder_item.setZValue(4)

    def _sync_config_to(self, target: "CanvasView"):
        target.config.cols = self.config.cols
        target.config.rows = self.config.rows
        target.config.pitch_px = self.config.pitch_px
        target.config.margin_px = self.config.margin_px
        target.config.hole_radius_px = self.config.hole_radius_px
        target.config.pad_radius_px = self.config.pad_radius_px
        target.config.style = self.config.style
        target.config.transparent = bool(getattr(self.config, "transparent", False))
        target.config.transparent_components = bool(getattr(self.config, "transparent_components", False))
        target.config.cutouts = [
            BoardCutout(
                shape=c.shape,
                x=c.x,
                y=c.y,
                w=c.w,
                h=c.h,
                corner_radius=c.corner_radius,
                rotation=c.rotation,
                inverted=c.inverted,
                vertices=list(c.vertices),
                uid=c.uid,
            )
            for c in getattr(self.config, "cutouts", [])
        ]

    def _notify_partner_sync(self, full: bool = True):
        partner = self._partner_view
        if partner is None or self._syncing_partner or partner._syncing_partner:
            return
        self._syncing_partner = True
        partner._syncing_partner = True
        try:
            self._sync_config_to(partner)
            if full:
                partner._sync_from_partner()
            else:
                partner._update_solder_z()
                partner.board_item.update()
                partner.solder_item.update()
                for item in partner.component_items:
                    item.update()
                if partner.placement_ghost_item is not None:
                    partner.placement_ghost_item.update()
                for j_item in partner.jumper_items:
                    j_item.update()
        finally:
            self._syncing_partner = False
            partner._syncing_partner = False

    def _sync_from_partner(self):
        partner = self._partner_view
        if partner is None:
            return
        partner._sync_config_to(self)

        # Rebuild component wrappers around shared PlacedComponent objects
        self._syncing_selection = True
        try:
            self.scene.clearSelection()
            for it in list(self.component_items):
                if it.scene() == self.scene:
                    self.scene.removeItem(it)
            self.component_items.clear()

            for instance in self.placed_components:
                comp_def = REGISTRY.get(instance.type_id)
                if not comp_def:
                    continue
                item = ComponentItem(instance, comp_def, self.config)
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, self.current_mode == "select")
                self.component_items.append(item)
                self.scene.addItem(item)

            # Rebuild jumper wrappers around shared JumperWire objects
            for j_it in list(self.jumper_items):
                if j_it.scene() == self.scene:
                    self.scene.removeItem(j_it)
            self.jumper_items.clear()

            for wire in self.jumpers:
                j_item = JumperItem(wire, self.config)
                self.jumper_items.append(j_item)
                self.scene.addItem(j_item)

            # Mirror active selection without triggering feedback
            sel_comp = partner.get_selected_component_item()
            if sel_comp:
                for it in self.component_items:
                    if it.instance is sel_comp.instance:
                        it.setSelected(True)
                        break
            else:
                sel_j = partner.get_selected_jumper_item()
                if sel_j:
                    for j_it in self.jumper_items:
                        if j_it.jumper is sel_j.jumper:
                            j_it.setSelected(True)
                            break
        finally:
            self._syncing_selection = False

        p_trace = getattr(partner, "_selected_solder_trace", None)
        if p_trace is not None and p_trace in self.solder_mgr.traces:
            self._selected_solder_trace = p_trace
            self.solder_item.set_selected_trace(p_trace)
        else:
            self._selected_solder_trace = None
            self.solder_item.set_selected_trace(None)

        self.solder_item.set_current_drawing(partner.solder_item.current_drawing_segment)
        self.autoconnect_overlay.set_active(self.current_mode == "autoconnect")
        self.autoconnect_overlay.set_selected_targets(self.autoconnect_selected_targets)
        self.autoconnect_overlay.set_groups(self.autoconnect_groups)
        self.board_item.setVisible(partner.board_item.isVisible())
        self.solder_item.set_board_visible(partner.board_item.isVisible())
        self._update_solder_z()
        self.reinit_board()

    def _on_component_moved_live(self, instance: PlacedComponent):
        """Syncs attached off-grid jumpers and partner view position in real time while moving/rotating."""
        self._sync_attached_jumpers_for_component(instance)
        partner = self._partner_view
        if partner is None or self._syncing_partner or partner._syncing_partner:
            return
        self._syncing_partner = True
        partner._syncing_partner = True
        try:
            for item in partner.component_items:
                if item.instance is instance:
                    item.update_position_from_grid()
                    item.refresh_geometry()
                    break
        finally:
            self._syncing_partner = False
            partner._syncing_partner = False

    def _sync_partner_solder(self):
        partner = self._partner_view
        if partner is not None and not self._syncing_partner:
            partner.solder_item.set_current_drawing(self.solder_item.current_drawing_segment)
            partner.solder_item.update()

    def _sync_partner_jumper(self, jumper: JumperWire):
        partner = self._partner_view
        if partner is not None and not self._syncing_partner:
            for j_item in partner.jumper_items:
                if j_item.jumper is jumper:
                    j_item.prepareGeometryChange()
                    j_item.update()
                    break

    def _sync_partner_autoconnect_overlay(self):
        partner = self._partner_view
        if partner is not None:
            partner.autoconnect_overlay.set_selected_targets(self.autoconnect_selected_targets)
            partner.autoconnect_overlay.set_groups(self.autoconnect_groups)

    def set_transparent(self, enabled: bool):
        """Toggles semi-transparent PCB substrate and see-through opposite-side layers."""
        val = bool(enabled)
        self.config.transparent = val
        self._update_solder_z()
        if not val and self.config.view_side != "bottom":
            self._clear_net_highlight()
        self.board_item.update()
        self.solder_item.update()
        for item in self.component_items:
            item.update()
        for j_item in self.jumper_items:
            j_item.update()
        self._notify_partner_sync(full=False)

    def set_components_transparent(self, enabled: bool):
        """Toggles semi-transparent component artwork independently of PCB and routing layers."""
        self.config.transparent_components = bool(enabled)
        for item in self.component_items:
            item.update()
        if self.placement_ghost_item is not None:
            self.placement_ghost_item.update()
        self._notify_partner_sync(full=False)

    def set_double_view_active(self, active: bool, badge: str = ""):
        """Enables/disables Double-View coordination and optional corner label badge."""
        self._double_view_active = bool(active)
        self._double_view_badge = badge if active else ""
        if active and self._primary_view is None and self.config.view_side != "top":
            self.set_view_side("top")
        if not active:
            self.set_mirrored_cursor_pos(None)
        self.viewport().update()

    def set_mirrored_cursor_pos(self, scene_pos: QPointF | None):
        """Updates the partner '+' cursor overlay scene position."""
        if self._mirrored_cursor_scene_pos != scene_pos:
            self._mirrored_cursor_scene_pos = scene_pos
            self.viewport().update()

    def _on_view_scrolled(self, _val: int):
        if self._double_view_active and not self._syncing_camera:
            self.mirror_camera_to_partner()

    def mirror_camera_to_partner(self):
        """Mirrors zoom factor and horizontally flipped camera center to partner viewport."""
        partner = self._partner_view
        if self._syncing_camera or partner is None or not self._double_view_active:
            return
        vp_rect = self.viewport().rect()
        if vp_rect.width() <= 0 or vp_rect.height() <= 0:
            return

        trans = self.transform()
        scale = abs(trans.m11()) or 1.0
        inv_t, ok = self.viewportTransform().inverted()
        if ok:
            vp_center = QPointF(vp_rect.width() / 2.0, vp_rect.height() / 2.0)
            sc = inv_t.map(vp_center)
        else:
            sc = QPointF(self.mapToScene(vp_rect.center()))

        mirror_center = QPointF(self.config.width_px - sc.x(), sc.y())

        self._syncing_camera = True
        partner._syncing_camera = True
        try:
            partner.setTransform(QTransform.fromScale(scale, scale))
            partner._zoom_factor = scale
            partner.centerOn(mirror_center)
        finally:
            self._syncing_camera = False
            partner._syncing_camera = False

    def drawForeground(self, painter: QPainter, rect: QRectF):
        super().drawForeground(painter, rect)
        if not self._double_view_active:
            return

        painter.save()
        if self._mirrored_cursor_scene_pos is not None:
            scale = abs(self.transform().m11()) or 1.0
            arm = 11.0 / scale
            px = self._mirrored_cursor_scene_pos.x()
            py = self._mirrored_cursor_scene_pos.y()

            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            # Dark halo for contrast on any PCB theme
            painter.setPen(QPen(QColor(15, 18, 24, 220), 3.6 / scale, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(px - arm, py), QPointF(px + arm, py))
            painter.drawLine(QPointF(px, py - arm), QPointF(px, py + arm))

            # Bright cyan crosshair "+"
            painter.setPen(QPen(QColor(56, 189, 248, 245), 1.8 / scale, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(px - arm, py), QPointF(px + arm, py))
            painter.drawLine(QPointF(px, py - arm), QPointF(px, py + arm))

            # Crisp white center dot
            dot_r = 1.6 / scale
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 245))
            painter.drawEllipse(QPointF(px, py), dot_r, dot_r)

        if self._double_view_badge:
            painter.resetTransform()
            vp_w = self.viewport().width()
            badge_w = 108
            badge_h = 22
            badge_rect = QRectF(max(8, vp_w - badge_w - 10), 10, badge_w, badge_h)
            is_back = ("BACK" in self._double_view_badge.upper())
            bg = QColor(43, 45, 49, 215)
            border = QColor(240, 178, 50, 210) if is_back else QColor(88, 101, 242, 210)
            painter.setPen(QPen(border, 1.2))
            painter.setBrush(bg)
            painter.drawRoundedRect(badge_rect, 5.0, 5.0)
            painter.setPen(border.lighter(125))
            font = painter.font()
            font.setPointSize(8)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, self._double_view_badge)
        painter.restore()

    def set_mode(self, mode: str):
        if mode not in ("select", "solder", "jumper", "autoconnect", "shape"):
            return
        if self.current_mode == mode:
            return

        self.current_mode = mode
        self.cancel_placement_mode()

        # Update solder item ghost mode
        self.solder_item.set_solder_mode(mode == "solder")
        self._clear_net_highlight()

        # Update board item shape mode
        is_shape = (mode == "shape")
        self.board_item.set_shape_mode(is_shape)
        if not is_shape:
            self._cutout_drag_mode = None
            self._cutout_resize_handle = ""

        # Update AutoConnect overlay
        is_ac = (mode == "autoconnect")
        self.autoconnect_overlay.set_active(is_ac)
        if not is_ac:
            self.autoconnect_selected_targets.clear()
            self.autoconnect_overlay.set_selected_targets([])
            self.autoconnect_selection_changed.emit([])

        # Update component interactability
        is_select = (mode == "select")
        for item in self.component_items:
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, is_select)

        if not is_select:
            self.scene.clearSelection()
            if self._selected_solder_trace is not None:
                self.select_solder_trace(None)

        # Update cursor
        self._update_cursor()
        self.mode_changed.emit(mode)

    def _update_cursor(self):
        if self._is_panning:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif self._space_pressed:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            edges = self._board_resize_edges if self._board_resize_active else self._hovered_resize_edges
            if edges:
                if edges in ("TL", "BR"):
                    self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                elif edges in ("TR", "BL"):
                    self.setCursor(Qt.CursorShape.SizeBDiagCursor)
                elif edges in ("L", "R"):
                    self.setCursor(Qt.CursorShape.SizeHorCursor)
                elif edges in ("T", "B"):
                    self.setCursor(Qt.CursorShape.SizeVerCursor)
                return

            if self.current_mode == "solder":
                if self._ctrl_pressed:
                    self.setCursor(Qt.CursorShape.ForbiddenCursor)
                else:
                    self.setCursor(Qt.CursorShape.CrossCursor)
            elif self.current_mode == "jumper":
                self.setCursor(Qt.CursorShape.CrossCursor)
            elif self.current_mode == "autoconnect":
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            elif self.current_mode == "shape":
                self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_cutout_tool(self, shape: str, corner_radius: float, inverted: bool = False):
        self.active_cutout_shape = shape
        self.active_cutout_corner_radius = float(corner_radius)
        self.active_cutout_inverted = bool(inverted)
        if shape != "custom" and self._drawing_custom_cutout is not None:
            self._cancel_custom_drawing()
        if shape != "select" and (self.selected_cutout_uid is not None or self.selected_vertex_indices):
            self._select_cutout(None)
            self._select_vertex(None)

    def _switch_cutout_tool_to_select(self):
        if self.active_cutout_shape != "select":
            self.active_cutout_shape = "select"
            self.cutout_tool_synced.emit("select")

    def _get_selected_cutout(self) -> BoardCutout | None:
        if not self.selected_cutout_uid:
            return None
        return next((c for c in self.config.cutouts if c.uid == self.selected_cutout_uid), None)

    def _select_cutout(self, uid: str | None):
        if self.selected_cutout_uid != uid:
            self.selected_cutout_uid = uid
            self.selected_vertex_idx = None
            self.selected_vertex_indices = []
            self.board_item.set_selected_cutout(uid)
            self.cutout_selection_changed.emit(uid)
        else:
            self.board_item.update()

    def _select_vertex(self, idx: int | None, toggle: bool = False):
        if idx is None:
            self.selected_vertex_indices = []
            self.selected_vertex_idx = None
        elif toggle:
            if idx in self.selected_vertex_indices:
                self.selected_vertex_indices.remove(idx)
            else:
                self.selected_vertex_indices.append(idx)
            self.selected_vertex_idx = self.selected_vertex_indices[-1] if self.selected_vertex_indices else None
        else:
            self.selected_vertex_indices = [idx]
            self.selected_vertex_idx = idx
        self.board_item.set_selected_vertices(self.selected_vertex_indices)

    def _cutout_display_rect(self, cutout: BoardCutout) -> QRectF:
        if self.config.view_side == "bottom":
            bx = self.config.width_px - (cutout.x + cutout.w)
        else:
            bx = cutout.x
        return QRectF(bx, cutout.y, cutout.w, cutout.h)

    def _set_cutout_from_display_rect(self, cutout: BoardCutout, rect: QRectF):
        norm = rect.normalized()
        w = max(4.0, norm.width())
        h = max(4.0, norm.height())
        if self.config.view_side == "bottom":
            cutout.x = self.config.width_px - (norm.left() + w)
        else:
            cutout.x = norm.left()
        cutout.y = norm.top()
        cutout.w = w
        cutout.h = h

    def _board_to_cutout_local_display(self, board_pos: QPointF, cutout: BoardCutout) -> QPointF:
        rect = self._cutout_display_rect(cutout)
        rot = -cutout.rotation if self.config.view_side == "bottom" else cutout.rotation
        if abs(rot) <= 1e-6:
            return board_pos
        c = rect.center()
        t = QTransform()
        t.translate(c.x(), c.y())
        t.rotate(-rot)
        t.translate(-c.x(), -c.y())
        return t.map(board_pos)

    def _cutout_local_display_to_board(self, local_pos: QPointF, cutout: BoardCutout) -> QPointF:
        rect = self._cutout_display_rect(cutout)
        rot = -cutout.rotation if self.config.view_side == "bottom" else cutout.rotation
        if abs(rot) <= 1e-6:
            return local_pos
        c = rect.center()
        t = QTransform()
        t.translate(c.x(), c.y())
        t.rotate(rot)
        t.translate(-c.x(), -c.y())
        return t.map(local_pos)

    def _hit_test_cutout_rot_handle(self, board_pos: QPointF, cutout: BoardCutout) -> bool:
        rect = self._cutout_display_rect(cutout)
        local_pos = self._board_to_cutout_local_display(board_pos, cutout)
        inv_zoom = 1.0 / max(0.15, self._zoom_factor)
        tol = 8.0 * inv_zoom
        hx = (rect.left() + rect.right()) * 0.5
        hy = rect.top() - 22.0 * inv_zoom
        return math.hypot(local_pos.x() - hx, local_pos.y() - hy) <= tol

    def _hit_test_cutout_vertex(self, board_pos: QPointF, cutout: BoardCutout) -> int | None:
        if cutout.shape != "custom" or not cutout.vertices:
            return None
        local_pos = self._board_to_cutout_local_display(board_pos, cutout)
        tol = 8.0 / max(0.15, self._zoom_factor)
        is_bottom = (self.config.view_side == "bottom")
        w_board = self.config.width_px
        for idx, (vx, vy) in enumerate(cutout.vertices):
            dx = (w_board - vx) if is_bottom else vx
            if math.hypot(local_pos.x() - dx, local_pos.y() - vy) <= tol:
                return idx
        return None

    def _hit_test_cutout_handle(self, board_pos: QPointF, cutout: BoardCutout) -> str:
        rect = self._cutout_display_rect(cutout)
        local_pos = self._board_to_cutout_local_display(board_pos, cutout)
        tol = 8.0 / max(0.15, self._zoom_factor)
        x1, y1, x2, y2 = rect.left(), rect.top(), rect.right(), rect.bottom()
        xm, ym = (x1 + x2) * 0.5, (y1 + y2) * 0.5
        handles = (
            ("TL", x1, y1), ("T", xm, y1), ("TR", x2, y1), ("R", x2, ym),
            ("BR", x2, y2), ("B", xm, y2), ("BL", x1, y2), ("L", x1, ym),
        )
        for name, hx, hy in handles:
            if abs(local_pos.x() - hx) <= tol and abs(local_pos.y() - hy) <= tol:
                return name
        return ""

    def _hit_test_cutouts(self, board_pos: QPointF) -> list[BoardCutout]:
        """Returns all cutouts hit at board_pos ordered from topmost to bottommost."""
        cx = (self.config.width_px - board_pos.x()) if self.config.view_side == "bottom" else board_pos.x()
        cy = board_pos.y()
        hits: list[BoardCutout] = []
        for cutout in reversed(self.config.cutouts):
            if cutout.is_inverted:
                lx, ly = cutout._to_local(cx, cy)
                if (
                    cutout.x - 6.0 <= lx <= cutout.x + cutout.w + 6.0
                    and cutout.y - 6.0 <= ly <= cutout.y + cutout.h + 6.0
                ) or cutout.contains_point(cx, cy):
                    hits.append(cutout)
            elif cutout.contains_point(cx, cy):
                hits.append(cutout)
        return hits

    def _hit_test_cutout(self, board_pos: QPointF) -> BoardCutout | None:
        hits = self._hit_test_cutouts(board_pos)
        return hits[0] if hits else None

    def _snap_custom_vertex(
        self,
        canon_x: float,
        canon_y: float,
        other_verts: list[tuple[float, float]],
    ) -> tuple[float, float, list[tuple[str, float]]]:
        """Auto-aligns X/Y to within 5 actual viewport pixels of other vertices."""
        thresh = 5.0 / max(0.05, self._zoom_factor)
        best_x = canon_x
        best_dx = thresh
        snapped_x = False
        best_y = canon_y
        best_dy = thresh
        snapped_y = False
        for ox, oy in other_verts:
            dx = abs(canon_x - ox)
            if dx <= best_dx:
                best_dx = dx
                best_x = ox
                snapped_x = True
            dy = abs(canon_y - oy)
            if dy <= best_dy:
                best_dy = dy
                best_y = oy
                snapped_y = True

        guides: list[tuple[str, float]] = []
        is_bottom = (self.config.view_side == "bottom")
        if snapped_x:
            gx = (self.config.width_px - best_x) if is_bottom else best_x
            guides.append(("x", gx))
        if snapped_y:
            guides.append(("y", best_y))
        return best_x, best_y, guides

    def _finish_custom_drawing(self):
        c = self._drawing_custom_cutout
        self._drawing_custom_cutout = None
        self.board_item.drawing_custom_cutout = None
        self.board_item.drawing_custom_cursor = None
        self.board_item.custom_snap_guides = []
        if c is not None and len(c.vertices) >= 3:
            c.recompute_custom_bounds()
            self.config.cutouts.append(c)
            self._select_cutout(c.uid)
            self._switch_cutout_tool_to_select()
            self.record_undo_snapshot()
        self.board_item.update()
        self._notify_partner_sync(full=False)

    def _cancel_custom_drawing(self):
        self._drawing_custom_cutout = None
        self.board_item.drawing_custom_cutout = None
        self.board_item.drawing_custom_cursor = None
        self.board_item.custom_snap_guides = []
        self.board_item.update()

    @staticmethod
    def _compute_multi_bevel_vertices(
        orig_verts: list[tuple[float, float]],
        v_indices: list[int] | set[int],
        radius: float,
        segments: int,
    ) -> list[tuple[float, float]]:
        n = len(orig_verts)
        selected = {idx for idx in v_indices if 0 <= idx < n}
        if n < 3 or not selected:
            return list(orig_verts)

        r = max(1.0, radius)
        segs = max(0, min(20, int(segments)))
        result: list[tuple[float, float]] = []

        for i in range(n):
            if i not in selected:
                result.append(orig_verts[i])
                continue
            prev_idx = (i - 1) % n
            next_idx = (i + 1) % n
            px, py = orig_verts[i]
            ax, ay = orig_verts[prev_idx]
            bx, by = orig_verts[next_idx]
            la = math.hypot(ax - px, ay - py)
            lb = math.hypot(bx - px, by - py)
            if la <= 1e-6 or lb <= 1e-6:
                result.append(orig_verts[i])
                continue

            # If neighbor is also being beveled simultaneously, each end stops at 49% (2% gap between ends);
            # if neighbor is stationary, this end can advance up to 98% (2% gap before stationary vertex).
            limit_a = la * (0.49 if prev_idx in selected else 0.98)
            limit_b = lb * (0.49 if next_idx in selected else 0.98)
            da = min(r, limit_a)
            db = min(r, limit_b)

            ux, uy = (ax - px) / la, (ay - py) / la
            vx, vy = (bx - px) / lb, (by - py) / lb
            sx, sy = px + ux * da, py + uy * da
            ex, ey = px + vx * db, py + vy * db

            if segs == 0:
                result.extend([(sx, sy), (ex, ey)])
            else:
                ox = sx + ex - px
                oy = sy + ey - py
                sox, soy = sx - ox, sy - oy
                eox, eoy = ex - ox, ey - oy
                result.append((sx, sy))
                for k in range(1, segs + 1):
                    theta = (math.pi * 0.5) * (k / (segs + 1))
                    c_t = math.cos(theta)
                    s_t = math.sin(theta)
                    result.append((ox + sox * c_t + eox * s_t, oy + soy * c_t + eoy * s_t))
                result.append((ex, ey))

        return result

    @staticmethod
    def _compute_bevel_vertices(
        orig_verts: list[tuple[float, float]],
        v_idx: int,
        radius: float,
        segments: int,
    ) -> list[tuple[float, float]]:
        return CanvasView._compute_multi_bevel_vertices(orig_verts, [v_idx], radius, segments)

    def _start_bevel(self) -> bool:
        sel = self._get_selected_cutout()
        if sel is None or sel.shape != "custom" or len(sel.vertices) < 3:
            return False
        valid_indices = [idx for idx in self.selected_vertex_indices if 0 <= idx < len(sel.vertices)]
        if not valid_indices and self.selected_vertex_idx is not None and 0 <= self.selected_vertex_idx < len(sel.vertices):
            valid_indices = [self.selected_vertex_idx]
        if not valid_indices:
            return False
        self._bevel_active = True
        self._bevel_cutout_uid = sel.uid
        self._bevel_vertex_indices = valid_indices
        self._bevel_vertex_idx = valid_indices[0]
        self._bevel_orig_vertices = list(sel.vertices)
        vp_pos = self.viewport().mapFromGlobal(QCursor.pos())
        start_board = self.board_item.mapFromScene(self.mapToScene(vp_pos))
        self._bevel_start_pos = start_board
        self.board_item.bevel_guide_line = (start_board, start_board)
        self._bevel_last_dist = 1.0
        self._update_bevel_preview(self._bevel_last_dist)
        return True

    def _update_bevel_preview(self, dist: float):
        if not self._bevel_active:
            return
        sel = next((c for c in self.config.cutouts if c.uid == self._bevel_cutout_uid), None)
        if sel is None:
            self._cancel_bevel()
            return
        self._bevel_last_dist = max(1.0, dist)
        sel.vertices = self._compute_multi_bevel_vertices(
            self._bevel_orig_vertices, self._bevel_vertex_indices, self._bevel_last_dist, self._bevel_segments
        )
        sel.recompute_custom_bounds()
        self.board_item.update()
        self._notify_partner_sync(full=False)

    def _commit_bevel(self):
        if not self._bevel_active:
            return
        self._bevel_active = False
        self._bevel_cutout_uid = None
        self._bevel_vertex_idx = -1
        self._bevel_vertex_indices = []
        self._bevel_orig_vertices = []
        self._bevel_start_pos = None
        self.board_item.bevel_guide_line = None
        self._select_vertex(None)
        self.board_item.update()
        self._notify_partner_sync(full=False)
        self.record_undo_snapshot()

    def _cancel_bevel(self):
        if not self._bevel_active:
            return
        sel = next((c for c in self.config.cutouts if c.uid == self._bevel_cutout_uid), None)
        if sel is not None and self._bevel_orig_vertices:
            sel.vertices = list(self._bevel_orig_vertices)
            sel.recompute_custom_bounds()
        self._bevel_active = False
        self._bevel_cutout_uid = None
        self._bevel_vertex_idx = -1
        self._bevel_vertex_indices = []
        self._bevel_orig_vertices = []
        self._bevel_start_pos = None
        self.board_item.bevel_guide_line = None
        self.board_item.update()
        self._notify_partner_sync(full=False)

    def remove_cutout_by_uid(self, uid: str):
        idx = next((i for i, c in enumerate(self.config.cutouts) if c.uid == uid), -1)
        if idx < 0:
            return
        self.config.cutouts.pop(idx)
        if self.selected_cutout_uid == uid:
            self.selected_cutout_uid = None
            self.selected_vertex_idx = None
            self.selected_vertex_indices = []
            self.board_item.set_selected_cutout(None)
        self.board_item.update()
        self._notify_partner_sync(full=False)
        self.record_undo_snapshot()
        self.cutout_selection_changed.emit(self.selected_cutout_uid)

    def clear_all_cutouts(self):
        if not self.config.cutouts:
            return
        self.config.cutouts.clear()
        self.selected_cutout_uid = None
        self.selected_vertex_idx = None
        self.selected_vertex_indices = []
        self.board_item.set_selected_cutout(None)
        self.board_item.update()
        self._notify_partner_sync(full=False)
        self.record_undo_snapshot()
        self.cutout_selection_changed.emit(None)

    def copy_selection(self) -> bool:
        if self.current_mode == "shape":
            sel_cutout = self._get_selected_cutout()
            if sel_cutout is not None:
                CanvasView._clipboard_payload = {
                    "kind": "cutout",
                    "data": copy.deepcopy(sel_cutout),
                    "paste_count": 0,
                }
                return True
            return False

        if self.current_mode == "select":
            sel_comp = self.get_selected_component_item()
            if sel_comp is not None:
                inst = sel_comp.instance
                CanvasView._clipboard_payload = {
                    "kind": "component",
                    "data": {
                        "type_id": inst.type_id,
                        "grid_x": inst.grid_x,
                        "grid_y": inst.grid_y,
                        "label": inst.label,
                        "rotation": inst.rotation,
                        "custom_props": copy.deepcopy(inst.custom_props),
                    },
                    "paste_count": 0,
                }
                return True
            sel_jumper = self.get_selected_jumper_item()
            if sel_jumper is not None:
                w = sel_jumper.jumper
                CanvasView._clipboard_payload = {
                    "kind": "jumper",
                    "data": {
                        "start_col": w.start_col,
                        "start_row": w.start_row,
                        "end_col": w.end_col,
                        "end_row": w.end_row,
                        "bends": [tuple(b) for b in w.bends],
                        "color": w.color,
                        "side": w.side,
                    },
                    "paste_count": 0,
                }
                return True
        return False

    def paste_selection(self) -> bool:
        payload = CanvasView._clipboard_payload
        if not payload:
            return False
        kind = payload.get("kind")

        if self.current_mode == "shape" and kind == "cutout":
            payload["paste_count"] = int(payload.get("paste_count", 0)) + 1
            offset = 20.0 * payload["paste_count"]
            new_cutout = copy.deepcopy(payload["data"])
            new_cutout.uid = uuid.uuid4().hex[:8]
            new_cutout.x += offset
            new_cutout.y += offset
            if new_cutout.shape == "custom" and new_cutout.vertices:
                new_cutout.vertices = [(vx + offset, vy + offset) for vx, vy in new_cutout.vertices]
                new_cutout.recompute_custom_bounds()
            self.config.cutouts.append(new_cutout)
            self._switch_cutout_tool_to_select()
            self._select_cutout(new_cutout.uid)
            self._select_vertex(None)
            self.board_item.update()
            self._notify_partner_sync(full=False)
            self.record_undo_snapshot()
            return True

        if self.current_mode == "select" and kind == "component":
            d = payload["data"]
            comp_def = REGISTRY.get(d["type_id"])
            if not comp_def:
                return False
            payload["paste_count"] = int(payload.get("paste_count", 0)) + 1
            step = payload["paste_count"]
            instance = PlacedComponent(
                type_id=d["type_id"],
                grid_x=d["grid_x"] + step,
                grid_y=d["grid_y"] + step,
                label=d["label"],
                rotation=d["rotation"],
                custom_props=copy.deepcopy(d["custom_props"]),
            )
            self.placed_components.append(instance)
            item = ComponentItem(instance, comp_def, self.config)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            self.component_items.append(item)
            self.scene.addItem(item)
            self.scene.clearSelection()
            item.setSelected(True)
            self.selection_changed.emit(item)
            self._notify_partner_sync(full=True)
            self.record_undo_snapshot()
            return True

        if self.current_mode == "select" and kind == "jumper":
            d = payload["data"]
            payload["paste_count"] = int(payload.get("paste_count", 0)) + 1
            step = payload["paste_count"]
            wire = JumperWire(
                start_col=d["start_col"] + step,
                start_row=d["start_row"] + step,
                end_col=d["end_col"] + step,
                end_row=d["end_row"] + step,
                bends=[(bc + step, br + step) for bc, br in d["bends"]],
                color=d["color"],
                side=d["side"],
            )
            self.jumpers.append(wire)
            j_item = JumperItem(wire, self.config)
            self.jumper_items.append(j_item)
            self.scene.addItem(j_item)
            self.scene.clearSelection()
            j_item.setSelected(True)
            self.selection_changed.emit(j_item)
            self._notify_partner_sync(full=True)
            self.record_undo_snapshot()
            return True

        return False

    def set_active_jumper_color(self, hex_color: str):
        self.active_jumper_color = hex_color
        selected_jumper = self.get_selected_jumper_item()
        if selected_jumper:
            selected_jumper.jumper.color = hex_color
            selected_jumper.update()
            self.selection_changed.emit(selected_jumper)
            self.record_undo_snapshot()

    def reset_scene_rect(self):
        margin = 1200
        w = self.config.width_px
        h = self.config.height_px
        self.scene.setSceneRect(-margin, -margin, w + 2 * margin, h + 2 * margin)

    def reinit_board(self):
        self.board_item.prepareGeometryChange()
        self.board_item.update()
        self.solder_item.prepareGeometryChange()
        self.solder_item.update()
        self.autoconnect_overlay.prepareGeometryChange()
        self.autoconnect_overlay.update()
        self.reset_scene_rect()
        for item in self.component_items:
            item.update_position_from_grid()
            item.refresh_geometry()
        for j_item in self.jumper_items:
            j_item.prepareGeometryChange()
            j_item.update()

    # Perfboard Edge Resizing (Preserves all component / solder / jumper locations)
    MIN_BOARD_COLS = 10
    MAX_BOARD_COLS = 120
    MIN_BOARD_ROWS = 8
    MAX_BOARD_ROWS = 100

    def _detect_board_resize_edges(self, scene_pos: QPointF) -> str:
        """Returns combination of 'T'/'B' and 'L'/'R' if scene_pos is on a board resize border."""
        scale = abs(self.transform().m11()) or 1.0
        # Keep inner threshold well clear of outer hole pads (margin_px=28, pad_r=7.6 -> 20.4px clear)
        outer = min(30.0, max(12.0, 14.0 / scale))
        inner = min(14.0, max(8.0, 10.0 / scale))

        w = self.config.width_px
        h = self.config.height_px
        x = scene_pos.x()
        y = scene_pos.y()

        if x < -outer or x > w + outer or y < -outer or y > h + outer:
            return ""

        horiz = ""
        if -outer <= x <= inner:
            horiz = "L"
        elif w - inner <= x <= w + outer:
            horiz = "R"

        vert = ""
        if -outer <= y <= inner:
            vert = "T"
        elif h - inner <= y <= h + outer:
            vert = "B"

        return vert + horiz

    def _get_occupied_grid_bounds(self) -> tuple[int, int, int, int] | None:
        """Returns (min_c, max_c, min_r, max_r) across all components, solders, and jumpers on board."""
        cols_occ: list[int] = []
        rows_occ: list[int] = []

        for item in self.component_items:
            for _, pc, pr, _ in item.instance.get_pin_positions(item.comp_def):
                if 0 <= pc < self.config.cols and 0 <= pr < self.config.rows:
                    cols_occ.append(pc)
                    rows_occ.append(pr)

        for trace in self.solder_mgr.traces:
            for hc, hr in trace.holes:
                if 0 <= hc < self.config.cols and 0 <= hr < self.config.rows:
                    cols_occ.append(hc)
                    rows_occ.append(hr)

        for j in self.jumpers:
            for jc, jr in j.all_points():
                if 0 <= jc < self.config.cols and 0 <= jr < self.config.rows:
                    cols_occ.append(jc)
                    rows_occ.append(jr)

        if not cols_occ or not rows_occ:
            return None
        return (min(cols_occ), max(cols_occ), min(rows_occ), max(rows_occ))

    def resize_board_from_edges(
        self,
        add_vis_left: int = 0,
        add_vis_right: int = 0,
        add_top: int = 0,
        add_bottom: int = 0,
        shift_view: bool = True,
    ) -> tuple[int, int, int, int]:
        """
        Resizes the perfboard dynamically from any visual edge without displacing
        existing components, solder traces, jumpers, or autoconnect targets relative
        to the physical perfboard holes.
        Returns applied visual deltas (applied_vis_left, applied_vis_right, applied_top, applied_bottom).
        """
        cols = self.config.cols
        rows = self.config.rows
        is_bottom = (self.config.view_side == "bottom")

        # Map visual horizontal edge deltas into logical col deltas
        if is_bottom:
            add_log_left = add_vis_right
            add_log_right = add_vis_left
        else:
            add_log_left = add_vis_left
            add_log_right = add_vis_right

        occ = self._get_occupied_grid_bounds()

        # Clamp logical left/right deltas within [MIN_BOARD_COLS, MAX_BOARD_COLS] and occupied bounds
        min_dl = -occ[0] if occ else (self.MIN_BOARD_COLS - cols)
        if add_log_right == 0:
            min_dl = max(min_dl, self.MIN_BOARD_COLS - cols)
        add_log_left = max(min_dl, min(self.MAX_BOARD_COLS - cols, add_log_left))

        cols_after_l = cols + add_log_left
        min_dr = (max(self.MIN_BOARD_COLS, (occ[1] + add_log_left + 1)) - cols_after_l) if occ else (self.MIN_BOARD_COLS - cols_after_l)
        max_dr = self.MAX_BOARD_COLS - cols_after_l
        add_log_right = max(min_dr, min(max_dr, add_log_right))

        # Clamp top/bottom deltas within [MIN_BOARD_ROWS, MAX_BOARD_ROWS] and occupied bounds
        min_dt = -occ[2] if occ else (self.MIN_BOARD_ROWS - rows)
        if add_bottom == 0:
            min_dt = max(min_dt, self.MIN_BOARD_ROWS - rows)
        add_top = max(min_dt, min(self.MAX_BOARD_ROWS - rows, add_top))

        rows_after_t = rows + add_top
        min_db = (max(self.MIN_BOARD_ROWS, (occ[3] + add_top + 1)) - rows_after_t) if occ else (self.MIN_BOARD_ROWS - rows_after_t)
        max_db = self.MAX_BOARD_ROWS - rows_after_t
        add_bottom = max(min_db, min(max_db, add_bottom))

        # Map back to applied visual deltas
        if is_bottom:
            app_vis_left = add_log_right
            app_vis_right = add_log_left
        else:
            app_vis_left = add_log_left
            app_vis_right = add_log_right
        app_top = add_top
        app_bottom = add_bottom

        new_cols = cols + add_log_left + add_log_right
        new_rows = rows + app_top + app_bottom

        if new_cols == cols and new_rows == rows and add_log_left == 0 and app_top == 0:
            return (0, 0, 0, 0)

        shift_c = add_log_left
        shift_r = app_top

        if shift_c != 0 or shift_r != 0:
            # 1. Shift placed components
            for comp in self.placed_components:
                comp.grid_x += shift_c
                comp.grid_y += shift_r

            # 2. Shift solder traces & segments (preserve canonical segment endpoint order)
            for trace in self.solder_mgr.traces:
                trace.holes = [(c + shift_c, r + shift_r) for c, r in trace.holes]
                shifted_segs = []
                for (c1, r1), (c2, r2) in trace.segments:
                    p1 = (c1 + shift_c, r1 + shift_r)
                    p2 = (c2 + shift_c, r2 + shift_r)
                    shifted_segs.append((p1, p2) if p1 <= p2 else (p2, p1))
                trace.segments = shifted_segs

            # 3. Shift jumpers & bends
            for j in self.jumpers:
                j.start_col += shift_c
                j.start_row += shift_r
                j.end_col += shift_c
                j.end_row += shift_r
                j.bends = [(c + shift_c, r + shift_r) for c, r in j.bends]

            # 4. Shift AutoConnect selections/groups (avoid double-shifting shared instances)
            seen_targets: set[int] = set()
            def _shift_target(t):
                tid = id(t)
                if tid in seen_targets:
                    return
                seen_targets.add(tid)
                t.holes = {(c + shift_c, r + shift_r) for c, r in t.holes}
                t.center_hole = (t.center_hole[0] + shift_c, t.center_hole[1] + shift_r)

            for t in self.autoconnect_selected_targets:
                _shift_target(t)
            for g in self.autoconnect_groups:
                for t in g.targets:
                    _shift_target(t)
            if self._last_autoconnect_targets:
                for t in self._last_autoconnect_targets:
                    _shift_target(t)
            if self._last_autoconnect_groups:
                for g in self._last_autoconnect_groups:
                    for t in g.targets:
                        _shift_target(t)

            if hasattr(self, "autoconnect_overlay"):
                self.autoconnect_overlay.set_selected_targets(self.autoconnect_selected_targets)
                self.autoconnect_overlay.set_groups(self.autoconnect_groups)

        # Invalidate pre-autoconnect snapshot if topology shifted
        self._autoconnect_base_state = None
        self._is_last_action_autoconnect = False

        self.config.cols = new_cols
        self.config.rows = new_rows
        self.reinit_board()

        # Compensate scrollbars so stationary edges stay anchored on screen
        if shift_view and (app_vis_left != 0 or app_top != 0):
            trans = self.transform()
            dx_vp = app_vis_left * self.config.pitch_px * abs(trans.m11())
            dy_vp = app_top * self.config.pitch_px * abs(trans.m22())
            self._board_resize_scroll_rem_x += dx_vp
            self._board_resize_scroll_rem_y += dy_vp
            sx = int(round(self._board_resize_scroll_rem_x))
            sy = int(round(self._board_resize_scroll_rem_y))
            self._board_resize_scroll_rem_x -= sx
            self._board_resize_scroll_rem_y -= sy
            if sx:
                hbar = self.horizontalScrollBar()
                hbar.setValue(hbar.value() + sx)
            if sy:
                vbar = self.verticalScrollBar()
                vbar.setValue(vbar.value() + sy)

        if self._partner_view is not None and not self._syncing_partner:
            partner = self._partner_view
            self._syncing_partner = True
            partner._syncing_partner = True
            try:
                self._sync_config_to(partner)
                partner.autoconnect_overlay.set_selected_targets(self.autoconnect_selected_targets)
                partner.autoconnect_overlay.set_groups(self.autoconnect_groups)
                partner.reinit_board()
            finally:
                self._syncing_partner = False
                partner._syncing_partner = False
            if self._double_view_active:
                self.mirror_camera_to_partner()

        if self._selected_solder_trace is not None:
            if self._selected_solder_trace in self.solder_mgr.traces:
                self.selection_changed.emit(self.build_solder_selection(self._selected_solder_trace))
            else:
                self.select_solder_trace(None)

        self.board_resized.emit(new_cols, new_rows)
        return (app_vis_left, app_vis_right, app_top, app_bottom)

    # Project & Undo State Management
    def serialize_state(self) -> dict:
        """Serializes current board, components, solders, and jumpers to state dict."""
        if self._primary_view is not None:
            return self._primary_view.serialize_state()
        return serialize_state(self.config, self.placed_components, self.solder_mgr, self.jumpers)

    def record_undo_snapshot(self):
        """Records current state into the undo stack (up to 200 steps)."""
        if self._primary_view is not None:
            self._primary_view.record_undo_snapshot()
            return
        if not getattr(self, "_suppress_invalidation", False):
            self._is_last_action_autoconnect = False
            self._autoconnect_base_state = None
            self._last_autoconnect_groups = None
            self._last_autoconnect_targets = None
        if hasattr(self, "history") and not self.history._is_active:
            self.history.push_state(self.serialize_state())
        self._notify_partner_sync(full=True)

    def undo(self) -> bool:
        """Restores the previous canvas state from the undo stack."""
        if self._primary_view is not None:
            return self._primary_view.undo()
        if not getattr(self, "_suppress_invalidation", False):
            self._is_last_action_autoconnect = False
            self._autoconnect_base_state = None
            self._last_autoconnect_groups = None
            self._last_autoconnect_targets = None
        if not hasattr(self, "history"):
            return False
        prev = self.history.undo()
        if prev is not None:
            self.load_state(prev, record_undo=False)
            self.history._notify()
            log_action("Undo executed", f"remaining_undo_steps={len(self.history.undo_stack) - 1}")
            return True
        return False

    def redo(self) -> bool:
        """Restores the next canvas state from the redo stack."""
        if self._primary_view is not None:
            return self._primary_view.redo()
        if not getattr(self, "_suppress_invalidation", False):
            self._is_last_action_autoconnect = False
            self._autoconnect_base_state = None
            self._last_autoconnect_groups = None
            self._last_autoconnect_targets = None
        if not hasattr(self, "history"):
            return False
        nxt = self.history.redo()
        if nxt is not None:
            self.load_state(nxt, record_undo=False)
            self.history._notify()
            log_action("Redo executed", f"remaining_redo_steps={len(self.history.redo_stack)}")
            return True
        return False

    def load_state(self, data: dict, record_undo: bool = False):
        """Restores the complete perfboard canvas state from a serialized state dictionary."""
        if self._primary_view is not None:
            self._primary_view.load_state(data, record_undo=record_undo)
            return

        # 1. Clear selection & net highlight
        self.scene.clearSelection()
        if self._selected_solder_trace is not None:
            self.select_solder_trace(None)
        self._clear_net_highlight()

        # 2. Board config
        b_data = data.get("board", {})
        self.config.cols = b_data.get("cols", self.config.cols)
        self.config.rows = b_data.get("rows", self.config.rows)
        self.config.style = b_data.get("style", self.config.style)
        self.config.pitch_px = b_data.get("pitch_px", self.config.pitch_px)
        if self._double_view_active:
            self.config.view_side = "top"
        else:
            self.config.view_side = b_data.get("view_side", self.config.view_side)

        self.config.cutouts = [
            BoardCutout(
                shape=c_data.get("shape", "rect"),
                x=float(c_data.get("x", 0.0)),
                y=float(c_data.get("y", 0.0)),
                w=float(c_data.get("w", 60.0)),
                h=float(c_data.get("h", 60.0)),
                corner_radius=float(c_data.get("corner_radius", 12.0)),
                rotation=float(c_data.get("rotation", 0.0)),
                inverted=bool(c_data.get("inverted", False)),
                vertices=[
                    (float(v[0]), float(v[1]))
                    for v in c_data.get("vertices", [])
                    if isinstance(v, (list, tuple)) and len(v) >= 2
                ],
                uid=c_data.get("uid") or BoardCutout().uid,
            )
            for c_data in b_data.get("cutouts", [])
            if isinstance(c_data, dict)
        ]
        if self.selected_cutout_uid and not any(c.uid == self.selected_cutout_uid for c in self.config.cutouts):
            self.selected_cutout_uid = None
            self.board_item.set_selected_cutout(None)
            self.cutout_selection_changed.emit(None)

        # 3. Clear existing components
        for it in list(self.component_items):
            it.setSelected(False)
            if it.scene() == self.scene:
                self.scene.removeItem(it)
        self.component_items.clear()
        self.placed_components.clear()

        # 4. Clear existing jumpers
        for j_it in list(self.jumper_items):
            j_it.setSelected(False)
            if j_it.scene() == self.scene:
                self.scene.removeItem(j_it)
        self.jumper_items.clear()
        self.jumpers.clear()

        # 5. Clear solder traces
        self.solder_mgr.clear()

        # 6. Reconstruct components
        for c_data in data.get("components", []):
            type_id = c_data["type_id"]
            comp_def = REGISTRY.get(type_id)
            if not comp_def:
                continue
            instance = PlacedComponent(
                type_id=type_id,
                grid_x=c_data.get("grid_x", 0),
                grid_y=c_data.get("grid_y", 0),
                label=c_data.get("label", comp_def.default_label),
                rotation=c_data.get("rotation", 0),
                custom_props=dict(c_data.get("custom_props", {})),
                uid=c_data.get("uid", "")
            )
            self.placed_components.append(instance)
            item = ComponentItem(instance, comp_def, self.config)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, self.current_mode == "select")
            self.component_items.append(item)
            self.scene.addItem(item)

        # 7. Reconstruct solder traces
        for t_data in data.get("solder_traces", []):
            trace = self.solder_mgr.create_trace()
            trace.id = t_data.get("id", trace.id)
            trace.holes = [tuple(h) for h in t_data.get("holes", [])]
            trace.segments = [(tuple(s[0]), tuple(s[1])) for s in t_data.get("segments", [])]
        if self.solder_mgr.traces:
            self.solder_mgr._next_id = max(t.id for t in self.solder_mgr.traces) + 1
        else:
            self.solder_mgr._next_id = 1

        # 8. Reconstruct jumpers
        for j_data in data.get("jumpers", []):
            raw_sp = j_data.get("start_pin")
            raw_ep = j_data.get("end_pin")
            start_pin = (str(raw_sp[0]), int(raw_sp[1]), str(raw_sp[2])) if raw_sp else None
            end_pin = (str(raw_ep[0]), int(raw_ep[1]), str(raw_ep[2])) if raw_ep else None
            wire = JumperWire(
                start_col=j_data["start_col"],
                start_row=j_data["start_row"],
                end_col=j_data["end_col"],
                end_row=j_data["end_row"],
                bends=[tuple(b) for b in j_data.get("bends", [])],
                color=j_data.get("color", DEFAULT_JUMPER_COLOR),
                side=j_data.get("side", "top"),
                uid=j_data.get("uid", ""),
                start_pin=start_pin,
                end_pin=end_pin,
            )
            self.jumpers.append(wire)
            j_item = JumperItem(wire, self.config)
            self.jumper_items.append(j_item)
            self.scene.addItem(j_item)

        # 9. Refresh visual scene & views
        self._update_solder_z()
        self.reinit_board()
        self.selection_changed.emit(None)
        self.view_side_changed.emit(self.config.view_side)
        self._notify_partner_sync(full=True)

        if record_undo:
            self.record_undo_snapshot()

    def save_project(self, filepath: str):
        """Saves project to a .pbrd file."""
        state = self.serialize_state()
        save_project_file(filepath, state)
        log_action("Project saved", f"filepath={filepath}")

    def load_project(self, filepath: str):
        """Loads project from a .pbrd file and resets undo history with loaded state."""
        if self._primary_view is not None:
            self._primary_view.load_project(filepath)
            return
        state = load_project_file(filepath)
        self.load_state(state, record_undo=False)
        self.history.reset(state)
        log_action("Project loaded", f"filepath={filepath}")

    def toggle_view_side(self):
        if self._double_view_active:
            return
        new_side = "bottom" if self.config.view_side == "top" else "top"
        self.set_view_side(new_side)

    def set_view_side(self, side: str):
        if side not in ("top", "bottom"):
            return
        if self._primary_view is not None and side != "bottom":
            return
        if self._double_view_active and self._primary_view is None and side != "top":
            return
        self.config.view_side = side
        self._update_solder_z()
        self._clear_net_highlight()
        self.board_item.update()
        self.solder_item.update()
        for item in self.component_items:
            item.update_position_from_grid()
            item.refresh_geometry()
        for j_item in self.jumper_items:
            j_item.update()
        self.view_side_changed.emit(side)

    def add_component(self, type_id: str, col: int, row: int, rotation: int = 0, label: str = "") -> PlacedComponent:
        REGISTRY.persist_if_remote(type_id)
        comp_def = REGISTRY.get(type_id)
        if not comp_def:
            raise ValueError(f"Unknown component type: {type_id}")

        default_label = label if label else comp_def.default_label
        instance = PlacedComponent(
            type_id=type_id,
            grid_x=col,
            grid_y=row,
            label=default_label,
            rotation=rotation
        )
        self.placed_components.append(instance)

        item = ComponentItem(instance, comp_def, self.config)
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, self.current_mode == "select")
        self.component_items.append(item)
        self.scene.addItem(item)
        self.component_placed.emit(instance)
        self.record_undo_snapshot()
        return instance

    def _find_off_grid_pin_at(
        self, scene_pos: QPointF
    ) -> tuple[PlacedComponent, int, str, float, float] | None:
        """Returns closest jumper-only off-grid pin hit (instance, pin_idx, name, col_f, row_f) or None."""
        thresh = self.config.pitch_px * 0.55
        best_hit = None
        best_dist = thresh
        for c_item in self.component_items:
            inst = c_item.instance
            off_pins = inst.get_off_grid_pin_positions(c_item.comp_def)
            for idx, (pname, cf, rf, _ptype) in enumerate(off_pins):
                px, py = self.config.grid_to_board_pos(cf, rf)
                d = math.hypot(scene_pos.x() - px, scene_pos.y() - py)
                if d <= best_dist:
                    best_dist = d
                    best_hit = (inst, idx, pname, cf, rf)
        return best_hit

    def _find_offboard_aligned_pin_at(
        self, scene_pos: QPointF
    ) -> tuple[PlacedComponent, int, int, str] | None:
        """Returns closest grid-aligned pin outside perfboard bounds (instance, col, row, name) or None."""
        thresh = self.config.pitch_px * 0.55
        best_hit = None
        best_dist = thresh
        for c_item in self.component_items:
            inst = c_item.instance
            for pname, pc, pr, _ptype in inst.get_pin_positions(c_item.comp_def):
                if self.config.is_valid_hole(pc, pr):
                    continue
                px, py = self.config.grid_to_board_pos(pc, pr)
                d = math.hypot(scene_pos.x() - px, scene_pos.y() - py)
                if d <= best_dist:
                    best_dist = d
                    best_hit = (inst, pc, pr, pname)
        return best_hit

    def _snap_jumper_endpoint(
        self,
        scene_pos: QPointF,
        col: int,
        row: int,
        anchor_pt: tuple[int | float, int | float] | None = None,
        is_shift: bool = False,
    ) -> tuple[int | float, int | float, tuple[str, int, str] | None]:
        """Snaps a jumper endpoint to an off-grid pin, off-board aligned pin, or clamped board hole."""
        if not is_shift:
            pin_hit = self._find_off_grid_pin_at(scene_pos)
            if pin_hit is not None:
                comp_inst, pin_idx, pin_name, cf, rf = pin_hit
                return (cf, rf, (comp_inst.uid, pin_idx, pin_name))
            offboard_hit = self._find_offboard_aligned_pin_at(scene_pos)
            if offboard_hit is not None:
                _, pc, pr, _ = offboard_hit
                return (pc, pr, None)

        c_target, r_target = col, row
        if is_shift and anchor_pt is not None:
            sc = int(round(anchor_pt[0]))
            sr = int(round(anchor_pt[1]))
            if abs(c_target - sc) >= abs(r_target - sr):
                r_target = sr
            else:
                c_target = sc

        c_target = max(0, min(self.config.cols - 1, c_target))
        r_target = max(0, min(self.config.rows - 1, r_target))
        return (c_target, r_target, None)

    def _sync_attached_jumpers_for_component(self, instance: PlacedComponent):
        """Updates jumper endpoints anchored to off-grid pins when a component moves or rotates."""
        comp_item = next((ci for ci in self.component_items if ci.instance is instance), None)
        if comp_item is None:
            return
        off_pins = instance.get_off_grid_pin_positions(comp_item.comp_def)
        for j_item in self.jumper_items:
            j = j_item.jumper
            moved = False
            if j.start_pin is not None and j.start_pin[0] == instance.uid:
                p_idx = j.start_pin[1]
                if 0 <= p_idx < len(off_pins):
                    j.start_col = off_pins[p_idx][1]
                    j.start_row = off_pins[p_idx][2]
                    moved = True
            if j.end_pin is not None and j.end_pin[0] == instance.uid:
                p_idx = j.end_pin[1]
                if 0 <= p_idx < len(off_pins):
                    j.end_col = off_pins[p_idx][1]
                    j.end_row = off_pins[p_idx][2]
                    moved = True
            if moved:
                j_item.prepareGeometryChange()
                j_item.update()
                self._sync_partner_jumper(j)

    def add_jumper(
        self,
        c1: int | float,
        r1: int | float,
        c2: int | float,
        r2: int | float,
        color: str | None = None,
        side: str | None = None,
        bends: list[tuple[int, int]] | None = None,
        record_undo: bool = True,
        start_pin: tuple[str, int, str] | None = None,
        end_pin: tuple[str, int, str] | None = None,
    ) -> JumperItem:
        clr = color if color else self.active_jumper_color
        s = side if side else self.config.view_side
        wire = JumperWire(
            start_col=c1,
            start_row=r1,
            end_col=c2,
            end_row=r2,
            color=clr,
            side=s,
            bends=list(bends or []),
            start_pin=start_pin,
            end_pin=end_pin,
        )
        self.jumpers.append(wire)

        j_item = JumperItem(wire, self.config)
        self.jumper_items.append(j_item)
        self.scene.addItem(j_item)
        if record_undo:
            self.record_undo_snapshot()
        return j_item

    def _clear_net_highlight(self, propagate_partner: bool = True):
        """Clears all conductive net highlights on solder traces and jumpers."""
        self.solder_item.set_highlighted_traces([])
        for j_item in self.jumper_items:
            j_item.set_net_highlighted(False)
        if propagate_partner and self._partner_view is not None and not self._syncing_partner:
            self._partner_view._clear_net_highlight(propagate_partner=False)

    def _apply_net_highlight(
        self,
        net_traces: list[SolderTrace],
        net_jumpers: list[JumperWire],
        propagate_partner: bool = True,
    ):
        """Highlights conductive net traces and jumpers on this canvas (and partner in Double-View)."""
        self.solder_item.set_highlighted_traces(net_traces)
        net_j_set = set(net_jumpers)
        for j_item in self.jumper_items:
            j_item.set_net_highlighted(j_item.jumper in net_j_set)
        if propagate_partner and self._partner_view is not None and not self._syncing_partner:
            self._partner_view._apply_net_highlight(net_traces, net_jumpers, propagate_partner=False)

    def _find_solder_trace_at(self, col: int, row: int, scene_pos: QPointF) -> SolderTrace | None:
        """Finds a clickable SolderTrace at scene_pos when solder is visible/highlighted."""
        is_bottom = (self.config.view_side == "bottom")
        is_transparent = bool(getattr(self.config, "transparent", False))
        board_hidden = not self.board_item.isVisible()
        if not is_bottom and not is_transparent and not board_hidden:
            return None

        # On Front View (Transparent mode or Board hidden), keep front-side components & top jumpers clickable first
        if not is_bottom:
            for item in self.scene.items(scene_pos):
                if (isinstance(item, ComponentItem) and item.isVisible()) or (isinstance(item, JumperItem) and item.isVisible() and item.jumper.side == "top"):
                    return None

        pad_thresh = self.config.pad_radius_px * 1.3
        if self.config.is_valid_hole(col, row):
            hx, hy = self.config.grid_to_board_pos(col, row)
            if math.hypot(scene_pos.x() - hx, scene_pos.y() - hy) <= pad_thresh:
                trace = self.solder_mgr.find_trace_with_hole(col, row)
                if trace is not None:
                    return trace

        for trace in self.solder_mgr.traces:
            for h1, h2 in trace.segments:
                p1 = QPointF(*self.config.grid_to_board_pos(*h1))
                p2 = QPointF(*self.config.grid_to_board_pos(*h2))
                if dist_to_segment(scene_pos, p1, p2) <= pad_thresh:
                    return trace
        return None

    def build_solder_selection(self, trace: SolderTrace) -> SelectedSolderPath:
        """Builds a SelectedSolderPath containing every pin connected directly or across jumpers."""
        direct_holes = set(trace.holes)
        if trace.holes:
            seed_c, seed_r = trace.holes[0]
            seed_pt = QPointF(*self.config.grid_to_board_pos(seed_c, seed_r))
            net_traces, net_jumpers = self.get_conductive_net_at(seed_c, seed_r, seed_pt)
        else:
            net_traces, net_jumpers = [trace], []

        if trace not in net_traces:
            net_traces = [trace, *net_traces]

        net_holes = set(direct_holes)
        net_pin_refs: set[tuple[str, int]] = set()
        for t in net_traces:
            net_holes.update(t.holes)
        for j in net_jumpers:
            for h in (j.start_hole(), j.end_hole()):
                if h is not None:
                    net_holes.add(h)
            if j.start_pin is not None:
                net_pin_refs.add((j.start_pin[0], j.start_pin[1]))
            if j.end_pin is not None:
                net_pin_refs.add((j.end_pin[0], j.end_pin[1]))

        direct_pins: list[ConnectedPinInfo] = []
        net_only_pins: list[ConnectedPinInfo] = []
        for c_item in self.component_items:
            inst = c_item.instance
            comp_def = c_item.comp_def
            comp_label = inst.label or comp_def.default_label or comp_def.name
            for pname, pc, pr, ptype in inst.get_pin_positions(comp_def):
                if (pc, pr) in direct_holes:
                    direct_pins.append(ConnectedPinInfo(
                        component_label=comp_label,
                        component_name=comp_def.name,
                        pin_name=pname,
                        col=pc,
                        row=pr,
                        pin_type=ptype,
                        via_jumper=False,
                    ))
                elif (pc, pr) in net_holes:
                    net_only_pins.append(ConnectedPinInfo(
                        component_label=comp_label,
                        component_name=comp_def.name,
                        pin_name=pname,
                        col=pc,
                        row=pr,
                        pin_type=ptype,
                        via_jumper=True,
                    ))
            for op_idx, (pname, pcf, prf, ptype) in enumerate(inst.get_off_grid_pin_positions(comp_def)):
                if (inst.uid, op_idx) in net_pin_refs:
                    net_only_pins.append(ConnectedPinInfo(
                        component_label=comp_label,
                        component_name=comp_def.name,
                        pin_name=f"{pname} (Jumper)",
                        col=int(round(pcf)),
                        row=int(round(prf)),
                        pin_type=ptype,
                        via_jumper=True,
                    ))

        sort_key = lambda p: (p.component_label, p.row, p.col, p.pin_name)
        direct_pins.sort(key=sort_key)
        net_only_pins.sort(key=sort_key)
        return SelectedSolderPath(
            trace=trace,
            direct_pins=direct_pins,
            net_only_pins=net_only_pins,
            net_traces=list(net_traces),
            net_jumpers=list(net_jumpers),
            net_holes=net_holes,
        )

    def select_solder_trace(self, trace: SolderTrace | None, propagate_partner: bool = True):
        """Selects or clears a SolderTrace and syncs selection & inspector state."""
        if trace is not None and self.scene.selectedItems():
            self._syncing_selection = True
            try:
                self.scene.clearSelection()
            finally:
                self._syncing_selection = False

        self._selected_solder_trace = trace
        self.solder_item.set_selected_trace(trace)

        if propagate_partner and self._partner_view is not None and not self._syncing_partner:
            self._partner_view.select_solder_trace(trace, propagate_partner=False)

        if propagate_partner:
            payload = self.build_solder_selection(trace) if trace is not None else None
            self.selection_changed.emit(payload)

    def get_conductive_net_at(self, col: int, row: int, scene_pos: QPointF) -> tuple[list[SolderTrace], list[JumperWire]]:
        """
        Computes the complete conductive net connected through solder traces and jumpers.
        Jumpers on both the front side and back side conduct electricity between their endpoints
        (whether perfboard holes or off-grid jumper pins).
        """
        seed_trace: SolderTrace | None = None
        seed_jumper: JumperWire | None = None
        seed_nodes: set[tuple] = set()

        # 1a. Check direct off-grid pin match first
        pin_hit = self._find_off_grid_pin_at(scene_pos)
        if pin_hit is not None:
            p_node = ("pin", pin_hit[0].uid, pin_hit[1])
            for j in self.jumpers:
                if p_node in (j.start_node(), j.end_node()):
                    seed_jumper = j
                    seed_nodes.add(p_node)
                    break

        # 1b. Check direct hole or off-board aligned component pin match
        if not seed_trace and not seed_jumper:
            target_hole = None
            if self.config.is_valid_hole(col, row):
                target_hole = (col, row)
            else:
                offboard_hit = self._find_offboard_aligned_pin_at(scene_pos)
                if offboard_hit is not None:
                    target_hole = (offboard_hit[1], offboard_hit[2])
            if target_hole is not None:
                tc, tr = target_hole
                t = self.solder_mgr.find_trace_with_hole(tc, tr) if self.config.is_valid_hole(tc, tr) else None
                if t:
                    seed_trace = t
                    seed_nodes.add(("hole", tc, tr))
                else:
                    for j in self.jumpers:
                        if (tc, tr) in (j.start_hole(), j.end_hole()):
                            seed_jumper = j
                            seed_nodes.add(("hole", tc, tr))
                            break

        # 2. Check proximity to solder segments
        if not seed_trace and not seed_jumper:
            pad_thresh = self.config.pad_radius_px * 1.3
            for t in self.solder_mgr.traces:
                for h1, h2 in t.segments:
                    p1 = QPointF(*self.config.grid_to_board_pos(*h1))
                    p2 = QPointF(*self.config.grid_to_board_pos(*h2))
                    if dist_to_segment(scene_pos, p1, p2) <= pad_thresh:
                        seed_trace = t
                        seed_nodes.add(("hole", *h1))
                        seed_nodes.add(("hole", *h2))
                        break
                if seed_trace:
                    break

        # 3. Check proximity to jumpers visible/interactive on this side
        if not seed_trace and not seed_jumper:
            is_transparent = bool(getattr(self.config, "transparent", False))
            for j_item in self.jumper_items:
                if j_item.jumper.side == self.config.view_side or is_transparent:
                    if j_item.shape().contains(scene_pos) or j_item.get_segment_index_at(scene_pos) is not None:
                        seed_jumper = j_item.jumper
                        seed_nodes.add(seed_jumper.start_node())
                        seed_nodes.add(seed_jumper.end_node())
                        break

        if not seed_trace and not seed_jumper and not seed_nodes:
            return [], []

        # 4. BFS graph traversal across hole and off-grid pin nodes
        visited_nodes: set[tuple] = set(seed_nodes)
        if seed_trace:
            for h in seed_trace.holes:
                visited_nodes.add(("hole", *h))
        if seed_jumper:
            visited_nodes.add(seed_jumper.start_node())
            visited_nodes.add(seed_jumper.end_node())

        queue = deque(list(visited_nodes))
        net_traces: set[SolderTrace] = set([seed_trace] if seed_trace else [])
        net_jumpers: set[JumperWire] = set([seed_jumper] if seed_jumper else [])

        while queue:
            curr_node = queue.popleft()

            # Find all solder traces containing curr_node (holes only)
            if curr_node[0] == "hole":
                hc, hr = curr_node[1], curr_node[2]
                for t in self.solder_mgr.traces:
                    if t not in net_traces and t.contains_hole(hc, hr):
                        net_traces.add(t)
                        for h in t.holes:
                            h_node = ("hole", *h)
                            if h_node not in visited_nodes:
                                visited_nodes.add(h_node)
                                queue.append(h_node)

            # Find all jumpers attached to curr_node (both front and back side!)
            for j in self.jumpers:
                if j not in net_jumpers:
                    s_node = j.start_node()
                    e_node = j.end_node()
                    if curr_node == s_node:
                        net_jumpers.add(j)
                        if e_node not in visited_nodes:
                            visited_nodes.add(e_node)
                            queue.append(e_node)
                    elif curr_node == e_node:
                        net_jumpers.add(j)
                        if s_node not in visited_nodes:
                            visited_nodes.add(s_node)
                            queue.append(s_node)

        return list(net_traces), list(net_jumpers)

    def identify_target_at(self, col: int, row: int, scene_pos: QPointF) -> AutoConnectTarget | None:
        """
        Identifies whether a click or hover is over a component pin, solder trace, or jumper end.
        Returns an AutoConnectTarget with the full conductive hole set, or None.
        """
        pad_thresh = self.config.pad_radius_px * 1.5

        # 1. Check Component Pins
        for c_item in self.component_items:
            comp = c_item.instance
            comp_def = c_item.comp_def
            pins = comp.get_pin_positions(comp_def)
            for pname, pc, pr, ptype in pins:
                bx, by = self.config.grid_to_board_pos(pc, pr)
                dist = math.hypot(scene_pos.x() - bx, scene_pos.y() - by)
                if (pc, pr) == (col, row) or dist <= pad_thresh:
                    net_traces, net_jumpers = self.get_conductive_net_at(pc, pr, scene_pos)
                    holes = set([(pc, pr)])
                    for t in net_traces:
                        holes.update(t.holes)
                    for j in net_jumpers:
                        for jh in (j.start_hole(), j.end_hole()):
                            if jh is not None:
                                holes.add(jh)

                    label = f"{comp.label} [{pname}]"
                    return AutoConnectTarget(
                        target_type="pin",
                        label=label,
                        holes=holes,
                        center_hole=(pc, pr),
                        component_item=c_item,
                        pin_name=pname
                    )

        # 2. Check Jumper Ends
        for j_item in self.jumper_items:
            j = j_item.jumper
            s_hole = j.start_hole()
            e_hole = j.end_hole()
            s_pos = self.config.grid_to_board_pos(j.start_col, j.start_row)
            e_pos = self.config.grid_to_board_pos(j.end_col, j.end_row)
            if s_hole is not None and (math.hypot(scene_pos.x() - s_pos[0], scene_pos.y() - s_pos[1]) <= pad_thresh or (col, row) == s_hole):
                net_traces, net_jumpers = self.get_conductive_net_at(s_hole[0], s_hole[1], scene_pos)
                holes = set([s_hole] + ([e_hole] if e_hole is not None else []))
                for t in net_traces:
                    holes.update(t.holes)
                for jw in net_jumpers:
                    for jh in (jw.start_hole(), jw.end_hole()):
                        if jh is not None:
                            holes.add(jh)
                c_name = col_index_to_name(s_hole[0])
                return AutoConnectTarget(
                    target_type="jumper_end",
                    label=f"Jumper End ({c_name}{s_hole[1] + 1})",
                    holes=holes,
                    center_hole=s_hole,
                    jumper_item=j_item,
                    jumper_end_idx=0
                )
            if e_hole is not None and (math.hypot(scene_pos.x() - e_pos[0], scene_pos.y() - e_pos[1]) <= pad_thresh or (col, row) == e_hole):
                net_traces, net_jumpers = self.get_conductive_net_at(e_hole[0], e_hole[1], scene_pos)
                holes = set([e_hole] + ([s_hole] if s_hole is not None else []))
                for t in net_traces:
                    holes.update(t.holes)
                for jw in net_jumpers:
                    for jh in (jw.start_hole(), jw.end_hole()):
                        if jh is not None:
                            holes.add(jh)
                c_name = col_index_to_name(e_hole[0])
                return AutoConnectTarget(
                    target_type="jumper_end",
                    label=f"Jumper End ({c_name}{e_hole[1] + 1})",
                    holes=holes,
                    center_hole=e_hole,
                    jumper_item=j_item,
                    jumper_end_idx=1
                )

        # 3. Check Solder Trace at Hole
        if self.config.is_valid_hole(col, row):
            trace = self.solder_mgr.find_trace_with_hole(col, row)
            if trace:
                net_traces, net_jumpers = self.get_conductive_net_at(col, row, scene_pos)
                holes = set(trace.holes)
                for t in net_traces:
                    holes.update(t.holes)
                for jw in net_jumpers:
                    holes.add((jw.start_col, jw.start_row))
                    holes.add((jw.end_col, jw.end_row))
                c_name = col_index_to_name(col)
                return AutoConnectTarget(
                    target_type="solder",
                    label=f"Solder Trace #{trace.id} ({c_name}{row + 1})",
                    holes=holes,
                    center_hole=(col, row),
                    solder_trace=trace
                )

        # 4. Check Proximity to Solder Segment
        for trace in self.solder_mgr.traces:
            for h1, h2 in trace.segments:
                p1 = QPointF(*self.config.grid_to_board_pos(*h1))
                p2 = QPointF(*self.config.grid_to_board_pos(*h2))
                if dist_to_segment(scene_pos, p1, p2) <= pad_thresh:
                    net_traces, net_jumpers = self.get_conductive_net_at(h1[0], h1[1], scene_pos)
                    holes = set(trace.holes)
                    for t in net_traces:
                        holes.update(t.holes)
                    for jw in net_jumpers:
                        holes.add((jw.start_col, jw.start_row))
                        holes.add((jw.end_col, jw.end_row))
                    return AutoConnectTarget(
                        target_type="solder",
                        label=f"Solder Trace #{trace.id}",
                        holes=holes,
                        center_hole=h1,
                        solder_trace=trace
                    )

        return None

    def _targets_match(self, t1: AutoConnectTarget, t2: AutoConnectTarget) -> bool:
        if t1 == t2:
            return True
        if t1.target_type == t2.target_type and t1.center_hole == t2.center_hole:
            return True
        if t1.target_type == "solder" and t2.target_type == "solder":
            return bool(t1.holes.intersection(t2.holes))
        return False

    def group_selected_targets(self):
        """
        Groups or merges currently selected conductors (Ctrl+G).
        - If selected items are not in any group: creates a new group with a unique color.
        - If selected items touch one existing group: adds un-grouped items into that group.
        - If selected items touch multiple groups: merges those groups and adds un-grouped items.
        """
        if not self.autoconnect_selected_targets:
            return

        selected = list(self.autoconnect_selected_targets)

        # Find which existing groups contain at least one of the selected targets
        touched_groups: list[AutoConnectGroup] = []
        for g in self.autoconnect_groups:
            for t in g.targets:
                if any(self._targets_match(t, s) for s in selected):
                    touched_groups.append(g)
                    break

        if not touched_groups:
            # Case 1: Brand new group
            existing_ids = [g.id for g in self.autoconnect_groups]
            next_id = max(existing_ids, default=0) + 1
            color = get_group_color(len(self.autoconnect_groups))
            new_group = AutoConnectGroup(
                id=next_id,
                color=color,
                targets=list(selected)
            )
            self.autoconnect_groups.append(new_group)
            log_action("AutoConnect Group Created", f"Group #{next_id} ({color}) with {len(selected)} conductors")

        elif len(touched_groups) == 1:
            # Case 2: One group touched -> add any un-grouped selected items
            target_g = touched_groups[0]
            added = 0
            for s in selected:
                if not any(self._targets_match(t, s) for t in target_g.targets):
                    target_g.targets.append(s)
                    added += 1
            log_action("AutoConnect Group Expanded", f"Group #{target_g.id}: added {added} conductors (now {len(target_g.targets)})")

        else:
            # Case 3: Multiple groups touched -> merge all into the first group
            primary_g = touched_groups[0]
            for other_g in touched_groups[1:]:
                for t in other_g.targets:
                    if not any(self._targets_match(ext, t) for ext in primary_g.targets):
                        primary_g.targets.append(t)
                if other_g in self.autoconnect_groups:
                    self.autoconnect_groups.remove(other_g)

            # Add any un-grouped selected items
            for s in selected:
                if not any(self._targets_match(t, s) for t in primary_g.targets):
                    primary_g.targets.append(s)

            log_action("AutoConnect Groups Merged", f"Merged into Group #{primary_g.id} (now {len(primary_g.targets)} conductors)")

        # Clear active transient selection
        self.autoconnect_selected_targets.clear()
        self.autoconnect_overlay.set_selected_targets([])
        self.autoconnect_overlay.set_groups(self.autoconnect_groups)
        self._sync_partner_autoconnect_overlay()
        self.autoconnect_selection_changed.emit([])
        self.autoconnect_groups_changed.emit(self.autoconnect_groups)

    def ungroup_selected_targets(self):
        """
        Removes selected conductors from any groups they belong to (Ctrl+Shift+G).
        """
        if not self.autoconnect_selected_targets:
            return

        selected = list(self.autoconnect_selected_targets)
        modified = False

        for g in list(self.autoconnect_groups):
            orig_count = len(g.targets)
            g.targets = [t for t in g.targets if not any(self._targets_match(t, s) for s in selected)]
            if len(g.targets) != orig_count:
                modified = True
            if len(g.targets) == 0:
                self.autoconnect_groups.remove(g)

        if modified:
            log_action("AutoConnect Ungrouped", "Removed conductors from group(s)")

        self.autoconnect_selected_targets.clear()
        self.autoconnect_overlay.set_selected_targets([])
        self.autoconnect_overlay.set_groups(self.autoconnect_groups)
        self._sync_partner_autoconnect_overlay()
        self.autoconnect_selection_changed.emit([])
        self.autoconnect_groups_changed.emit(self.autoconnect_groups)

    def remove_autoconnect_group(self, group_id: int):
        """Removes an entire conductor group by ID."""
        self.autoconnect_groups[:] = [g for g in self.autoconnect_groups if g.id != group_id]
        self.autoconnect_overlay.set_groups(self.autoconnect_groups)
        self._sync_partner_autoconnect_overlay()
        self.autoconnect_groups_changed.emit(self.autoconnect_groups)

    def clear_autoconnect_groups(self):
        """Clears all conductor groups."""
        self.autoconnect_groups.clear()
        self.autoconnect_overlay.set_groups([])
        self._sync_partner_autoconnect_overlay()
        self.autoconnect_groups_changed.emit([])

    def perform_autoconnect(
        self,
        targets: list[AutoConnectTarget] | None = None,
        groups: list[AutoConnectGroup] | None = None,
        is_recalculate: bool = False
    ) -> dict[str, Any]:
        """
        Connects conductors in the most efficient way possible without shorting.
        Supports multi-group routing (simultaneously routing all groups without intersections)
        or single-group routing.
        """
        if self._primary_view is not None:
            return self._primary_view.perform_autoconnect(
                targets=targets, groups=groups, is_recalculate=is_recalculate
            )

        # Capture base state BEFORE modifying canvas
        base_state = self.serialize_state()

        # Determine if groups are active
        active_groups: list[AutoConnectGroup] = []
        if groups is not None:
            active_groups = [g.copy() for g in groups]
        elif self.autoconnect_groups:
            # If user has pending un-grouped targets (>= 2), group them before running!
            if len(self.autoconnect_selected_targets) >= 2:
                self.group_selected_targets()
            active_groups = [g.copy() for g in self.autoconnect_groups]

        if active_groups:
            # Multi-group simultaneous routing without intersections
            for g in active_groups:
                if len(g.targets) < 2:
                    res = {
                        "success": False,
                        "message": f"Group #{g.id} has fewer than 2 conductors ({len(g.targets)}). Each group needs at least 2 conductors."
                    }
                    if not is_recalculate:
                        self.autoconnect_completed.emit(res)
                    return res

            res = connect_multiple_groups(
                groups=active_groups,
                config=self.config,
                solder_mgr=self.solder_mgr,
                jumpers=self.jumpers,
                components=self.placed_components,
                registry=REGISTRY,
                settings=self.autoconnect_settings
            )

            if not res["success"]:
                if not is_recalculate:
                    self.autoconnect_completed.emit(res)
                return res

            self._apply_routing_plan(res)

            # Atomic undo snapshot for the multi-group autoconnect
            self._suppress_invalidation = True
            try:
                self.record_undo_snapshot()
            finally:
                self._suppress_invalidation = False

            self._autoconnect_base_state = base_state
            self._last_autoconnect_groups = [g.copy() for g in active_groups]
            self._last_autoconnect_targets = None
            self._is_last_action_autoconnect = True

            if not is_recalculate:
                self.autoconnect_groups.clear()
                self.autoconnect_selected_targets.clear()
                self.autoconnect_overlay.set_groups([])
                self.autoconnect_overlay.set_selected_targets([])
                self._sync_partner_autoconnect_overlay()
                self.autoconnect_groups_changed.emit([])
                self.autoconnect_selection_changed.emit([])

            log_action(
                "Multi-Group AutoConnect executed",
                f"groups={len(active_groups)}, cost={res.get('total_cost', 0)}, solders={len(res.get('solder_segments', []))}, jumpers={len(res.get('jumpers', []))}"
            )
            self.autoconnect_completed.emit(res)
            return res

        # Single-group routing (targets)
        if targets is None:
            targets = list(self.autoconnect_selected_targets)

        if len(targets) < 2:
            res = {
                "success": False,
                "message": "Select at least 2 conductors (pins, traces, or jumper ends) to connect."
            }
            if not is_recalculate:
                self.autoconnect_completed.emit(res)
            return res

        res = connect_targets(
            targets=targets,
            config=self.config,
            solder_mgr=self.solder_mgr,
            jumpers=self.jumpers,
            components=self.placed_components,
            registry=REGISTRY,
            settings=self.autoconnect_settings
        )

        if not res["success"]:
            if not is_recalculate:
                self.autoconnect_completed.emit(res)
            return res

        self._apply_routing_plan(res)

        self._suppress_invalidation = True
        try:
            self.record_undo_snapshot()
        finally:
            self._suppress_invalidation = False

        self._autoconnect_base_state = base_state
        self._last_autoconnect_targets = list(targets)
        self._last_autoconnect_groups = None
        self._is_last_action_autoconnect = True

        if not is_recalculate:
            self.autoconnect_selected_targets.clear()
            self.autoconnect_overlay.set_selected_targets([])
            self._sync_partner_autoconnect_overlay()
            self.autoconnect_selection_changed.emit([])

        log_action(
            "AutoConnect executed",
            f"targets={len(targets)}, cost={res.get('total_cost', 0)}, solders={len(res.get('solder_segments', []))}, jumpers={len(res.get('jumpers', []))}"
        )
        self.autoconnect_completed.emit(res)
        return res

    def _apply_routing_plan(self, res: dict[str, Any]) -> None:
        """Applies routed solder segments and jumpers from a solver result onto the canvas."""
        solder_added = False
        for h1, h2 in res.get("solder_segments", []):
            self.solder_mgr.connect_holes(h1, h2)
            solder_added = True

        if solder_added:
            self.solder_item.update()

        for j_data in res.get("jumpers", []):
            self.add_jumper(
                c1=j_data["start"][0],
                r1=j_data["start"][1],
                c2=j_data["end"][0],
                r2=j_data["end"][1],
                color=j_data.get("color", "#00e6ff"),
                side=j_data.get("side", "top"),
                bends=j_data.get("bends", []),
                record_undo=False
            )

    def get_optimize_board_groups(self) -> list[AutoConnectGroup]:
        """Extracts shorted component pin nets from current board continuity."""
        if self._primary_view is not None:
            return self._primary_view.get_optimize_board_groups()
        return extract_connected_pin_groups(
            config=self.config,
            solder_mgr=self.solder_mgr,
            jumpers=self.jumpers,
            components=self.placed_components,
            registry=REGISTRY,
        )

    def optimize_board(self, precomputed_groups: list[AutoConnectGroup] | None = None) -> dict[str, Any]:
        """
        Traces component pin continuity to group shorted pins, clears all existing
        solder traces and jumpers, and runs multi-group autoconnect with current weights.
        Supports real-time weight slider recalculation and single-step Ctrl+Z undo.
        """
        if self._primary_view is not None:
            return self._primary_view.optimize_board(precomputed_groups=precomputed_groups)
        groups = [g.copy() for g in precomputed_groups] if precomputed_groups is not None else self.get_optimize_board_groups()
        if not groups:
            return {
                "success": False,
                "message": "No electrically connected component pin groups (2+ pins) found to optimize."
            }

        original_state = self.serialize_state()
        preserved_view_side = self.config.view_side

        # Clear existing solder paths and on-board jumpers while preserving off-grid/off-board jumpers
        self._clear_net_highlight()
        preserved_jumpers, _ = partition_offgrid_jumpers(self.config, self.jumpers)
        preserved_ids = {id(j) for j in preserved_jumpers}
        kept_items = []
        for j_it in list(self.jumper_items):
            if id(j_it.jumper) in preserved_ids:
                kept_items.append(j_it)
            else:
                j_it.setSelected(False)
                if j_it.scene() == self.scene:
                    self.scene.removeItem(j_it)
        self.jumper_items = kept_items
        self.jumpers = list(preserved_jumpers)
        self.solder_mgr.clear()
        self.solder_item.update()

        cleared_base_state = self.serialize_state()

        res = connect_multiple_groups(
            groups=groups,
            config=self.config,
            solder_mgr=self.solder_mgr,
            jumpers=self.jumpers,
            components=self.placed_components,
            registry=REGISTRY,
            settings=self.autoconnect_settings,
        )

        if not res["success"]:
            self._suppress_invalidation = True
            try:
                self.load_state(original_state, record_undo=False)
                self.config.view_side = preserved_view_side
            finally:
                self._suppress_invalidation = False
            self.autoconnect_completed.emit(res)
            return res

        self._apply_routing_plan(res)

        self._suppress_invalidation = True
        try:
            self.record_undo_snapshot()
        finally:
            self._suppress_invalidation = False

        # Base state for real-time slider updates is the cleared (component-only) board
        self._autoconnect_base_state = cleared_base_state
        self._last_autoconnect_groups = [g.copy() for g in groups]
        self._last_autoconnect_targets = None
        self._is_last_action_autoconnect = True

        self.autoconnect_groups.clear()
        self.autoconnect_selected_targets.clear()
        self.autoconnect_overlay.set_groups([])
        self.autoconnect_overlay.set_selected_targets([])
        self._sync_partner_autoconnect_overlay()
        self.autoconnect_groups_changed.emit([])
        self.autoconnect_selection_changed.emit([])

        log_action(
            "Optimize Board executed",
            f"groups={len(groups)}, cost={res.get('total_cost', 0)}, solders={len(res.get('solder_segments', []))}, jumpers={len(res.get('jumpers', []))}"
        )
        self.autoconnect_completed.emit(res)
        return res

    def recalculate_autoconnect(self) -> dict[str, Any]:
        """
        Re-runs the previous autoconnect with updated cost weights in real time.
        Restores solder and jumpers to base state, tests new routing,
        and replaces the top state in undo history in-place if successful.
        NEVER pops earlier history or deletes/moves components!
        """
        if self._primary_view is not None:
            return self._primary_view.recalculate_autoconnect()
        if not getattr(self, "_is_last_action_autoconnect", False) or not hasattr(self, "_autoconnect_base_state") or self._autoconnect_base_state is None:
            return {
                "success": False,
                "message": "No previous autoconnect operation to recalculate."
            }

        groups = [g.copy() for g in self._last_autoconnect_groups] if self._last_autoconnect_groups else None
        targets = list(self._last_autoconnect_targets) if self._last_autoconnect_targets else None

        if not groups and not targets:
            return {
                "success": False,
                "message": "No targets or groups to recalculate."
            }

        last_valid_state = self.serialize_state()
        preserved_view_side = self.config.view_side

        # Temporarily restore base state to test new routing
        self._suppress_invalidation = True
        try:
            self.load_state(self._autoconnect_base_state, record_undo=False)
            self.config.view_side = preserved_view_side
        finally:
            self._suppress_invalidation = False

        if groups:
            res = connect_multiple_groups(
                groups=groups,
                config=self.config,
                solder_mgr=self.solder_mgr,
                jumpers=self.jumpers,
                components=self.placed_components,
                registry=REGISTRY,
                settings=self.autoconnect_settings
            )
        else:
            res = connect_targets(
                targets=targets,
                config=self.config,
                solder_mgr=self.solder_mgr,
                jumpers=self.jumpers,
                components=self.placed_components,
                registry=REGISTRY,
                settings=self.autoconnect_settings
            )

        if not res["success"]:
            # Restore previous valid state so board doesn't break
            self._suppress_invalidation = True
            try:
                self.load_state(last_valid_state, record_undo=False)
                self.config.view_side = preserved_view_side
            finally:
                self._suppress_invalidation = False
            self.autoconnect_completed.emit(res)
            return res

        # Routing succeeded! Apply newly planned solder segments and jumpers
        self._apply_routing_plan(res)

        # Replace top of undo stack IN PLACE without clearing redo or pushing duplicate states
        new_state = self.serialize_state()
        if hasattr(self, "history"):
            self.history.replace_top_state(new_state)

        self._notify_partner_sync(full=True)

        # Maintain autoconnect state for subsequent slider changes
        self._is_last_action_autoconnect = True

        log_action(
            "AutoConnect recalculated",
            f"cost={res.get('total_cost', 0)}, solders={len(res.get('solder_segments', []))}, jumpers={len(res.get('jumpers', []))}"
        )
        self.autoconnect_completed.emit(res)
        return res

    def set_autoconnect_settings(self, settings: AutoConnectSettings):
        self.autoconnect_settings = settings
        if getattr(self, "_is_last_action_autoconnect", False) and (self._last_autoconnect_targets or self._last_autoconnect_groups):
            self.recalculate_autoconnect()

    def remove_selected_item(self):
        if self.current_mode == "shape" and self.selected_cutout_uid:
            self.remove_cutout_by_uid(self.selected_cutout_uid)
            return

        comp = self.get_selected_component_item()
        if comp:
            log_action("Delete Component", f"type={comp.instance.type_id}, pos=({comp.instance.grid_x},{comp.instance.grid_y}), rot={comp.instance.rotation}")
            comp.setSelected(False)
            if comp in self.component_items:
                self.component_items.remove(comp)
            if comp.instance in self.placed_components:
                self.placed_components.remove(comp.instance)
            if comp.scene() == self.scene:
                self.scene.removeItem(comp)
            self.selection_changed.emit(None)
            self.record_undo_snapshot()
            return

        jumper = self.get_selected_jumper_item()
        if jumper:
            log_action("Delete Jumper", f"from=({jumper.jumper.start_col},{jumper.jumper.start_row}) to=({jumper.jumper.end_col},{jumper.jumper.end_row})")
            jumper.setSelected(False)
            if jumper in self.jumper_items:
                self.jumper_items.remove(jumper)
            if jumper.jumper in self.jumpers:
                self.jumpers.remove(jumper.jumper)
            if jumper.scene() == self.scene:
                self.scene.removeItem(jumper)
            self.selection_changed.emit(None)
            self.record_undo_snapshot()
            return

        if self._selected_solder_trace is not None:
            trace = self._selected_solder_trace
            log_action("Delete Solder Path", f"id={trace.id}, holes={len(trace.holes)}")
            if trace in self.solder_mgr.traces:
                self.solder_mgr.traces.remove(trace)
            self.select_solder_trace(None)
            self._clear_net_highlight()
            self.solder_item.update()
            self._sync_partner_solder()
            self.record_undo_snapshot()

    def _other_double_view(self):
        return self._partner_view if self._partner_view is not None else self._primary_view

    def hide_selected_object(self) -> bool:
        """Hides currently selected component(s), jumper(s), or solder trace in selection mode."""
        if self.current_mode != "select":
            return False

        hid_any = False
        other = self._other_double_view()

        for it in list(self.scene.selectedItems()):
            if isinstance(it, ComponentItem):
                it.setSelected(False)
                it.setVisible(False)
                hid_any = True
                if other is not None:
                    for o_it in other.component_items:
                        if o_it.instance is it.instance:
                            o_it.setSelected(False)
                            o_it.setVisible(False)
            elif isinstance(it, JumperItem):
                it.setSelected(False)
                it.setVisible(False)
                hid_any = True
                if other is not None:
                    for o_it in other.jumper_items:
                        if o_it.jumper is it.jumper:
                            o_it.setSelected(False)
                            o_it.setVisible(False)

        if self._selected_solder_trace is not None:
            tid = self._selected_solder_trace.id
            self.solder_item.hidden_trace_ids.add(tid)
            self.select_solder_trace(None)
            self._clear_net_highlight()
            self.solder_item.update()
            if other is not None:
                other.solder_item.hidden_trace_ids.add(tid)
                other.select_solder_trace(None)
                other._clear_net_highlight()
                other.solder_item.update()
            hid_any = True

        if hid_any:
            self.selection_changed.emit(None)
            log_action("Hide Object", "selection hidden")
        return hid_any

    def unhide_all_objects(self) -> int:
        """Unhides all hidden components, jumpers, and solder traces across all modes."""
        count = 0
        for view in (self, self._other_double_view()):
            if view is None:
                continue
            for it in view.component_items:
                if not it.isVisible():
                    it.setVisible(True)
                    if view is self:
                        count += 1
            for it in view.jumper_items:
                if not it.isVisible():
                    it.setVisible(True)
                    if view is self:
                        count += 1
            if not view.solder_item.isVisible():
                view.solder_item.setVisible(True)
                if view is self:
                    count += 1
            if not view.board_item.isVisible():
                view.board_item.setVisible(True)
                view.solder_item.set_board_visible(True)
                view._update_solder_z()
                view.solder_item.update()
                if view is self:
                    count += 1
            if view.solder_item.hidden_trace_ids:
                if view is self:
                    count += len(view.solder_item.hidden_trace_ids)
                view.solder_item.hidden_trace_ids.clear()
                view.solder_item.update()

        if count > 0:
            self.objects_unhidden.emit()
            log_action("Unhide All Objects", f"count={count}")
        return count

    def set_component_visible(self, comp: PlacedComponent, visible: bool):
        """Sets visibility for a single placed component instance across views."""
        for view in (self, self._other_double_view()):
            if view is None:
                continue
            for it in view.component_items:
                if it.instance is comp:
                    if it.isSelected() and not visible:
                        it.setSelected(False)
                    it.setVisible(visible)

    def set_collection_visible(self, visible: bool):
        """Sets visibility for all placed components across views."""
        for view in (self, self._other_double_view()):
            if view is None:
                continue
            for it in view.component_items:
                if it.isSelected() and not visible:
                    it.setSelected(False)
                it.setVisible(visible)

    def set_solders_visible(self, visible: bool):
        """Sets visibility for all solder traces across views."""
        for view in (self, self._other_double_view()):
            if view is None:
                continue
            view.solder_item.setVisible(visible)
            if not visible:
                view.select_solder_trace(None)

    def set_jumpers_visible(self, visible: bool):
        """Sets visibility for all jumper wires across views."""
        for view in (self, self._other_double_view()):
            if view is None:
                continue
            for it in view.jumper_items:
                if it.isSelected() and not visible:
                    it.setSelected(False)
                it.setVisible(visible)

    def set_board_visible(self, visible: bool):
        """Sets visibility for the perfboard base item across views."""
        for view in (self, self._other_double_view()):
            if view is None:
                continue
            view.board_item.setVisible(visible)
            view.solder_item.set_board_visible(visible)
            view._update_solder_z()
            view.solder_item.update()

    def get_selected_component_item(self) -> ComponentItem | None:
        items = self.scene.selectedItems()
        for it in items:
            if isinstance(it, ComponentItem):
                return it
        return None

    def get_selected_jumper_item(self) -> JumperItem | None:
        items = self.scene.selectedItems()
        for it in items:
            if isinstance(it, JumperItem):
                return it
        return None

    def select_component(self, comp: PlacedComponent, ensure_visible: bool = True):
        """Finds and selects the ComponentItem matching the PlacedComponent instance."""
        target_item = None
        for it in self.component_items:
            if it.instance is comp:
                target_item = it
                break
        if target_item is None:
            return

        self.scene.clearSelection()
        target_item.setSelected(True)
        if ensure_visible:
            self.ensureVisible(target_item, 50, 50)
        self.selection_changed.emit(target_item)

    def start_placement_mode(self, type_id: str):
        self.set_mode("select")
        self.cancel_placement_mode()
        comp_def = REGISTRY.get(type_id)
        if not comp_def:
            return

        self.placement_type_id = type_id
        self.placement_rotation = 0
        self.placement_ghost = PlacedComponent(
            type_id=type_id,
            grid_x=0,
            grid_y=0,
            label=comp_def.default_label,
            rotation=0
        )
        self.placement_ghost_item = ComponentItem(self.placement_ghost, comp_def, self.config)
        self.placement_ghost_item.setOpacity(0.65)
        self.placement_ghost_item.setZValue(50)
        self.placement_ghost_item.setEnabled(False)
        self.scene.addItem(self.placement_ghost_item)

    def cancel_placement_mode(self):
        if self.placement_ghost_item:
            self.scene.removeItem(self.placement_ghost_item)
            self.placement_ghost_item = None
        self.placement_type_id = None
        self.placement_ghost = None

    def _on_scene_selection_changed(self):
        if self._syncing_selection:
            return
        items = self.scene.selectedItems()
        selected = items[0] if items else None
        if self._selected_solder_trace is not None:
            self._selected_solder_trace = None
            self.solder_item.set_selected_trace(None)
            if self._partner_view is not None and not self._syncing_partner:
                self._partner_view._selected_solder_trace = None
                self._partner_view.solder_item.set_selected_trace(None)
        if self._partner_view is not None and not self._syncing_partner:
            partner = self._partner_view
            partner._syncing_selection = True
            try:
                partner.scene.clearSelection()
                if isinstance(selected, ComponentItem):
                    for it in partner.component_items:
                        if it.instance is selected.instance:
                            it.setSelected(True)
                            break
                elif isinstance(selected, JumperItem):
                    for j_it in partner.jumper_items:
                        if j_it.jumper is selected.jumper:
                            j_it.setSelected(True)
                            break
            finally:
                partner._syncing_selection = False
        self.selection_changed.emit(selected)

    # Mouse & Keyboard Event Handling
    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        if self._bevel_active:
            step = 1 if delta > 0 else (-1 if delta < 0 else 0)
            if step != 0:
                self._bevel_segments = max(0, min(20, self._bevel_segments + step))
                self._update_bevel_preview(self._bevel_last_dist)
            event.accept()
            return

        factor = 1.15 if delta > 0 else (1.0 / 1.15 if delta < 0 else 1.0)
        new_zoom = self._zoom_factor * factor
        if 0.15 <= new_zoom <= 8.0:
            self._zoom_factor = new_zoom
            self.scale(factor, factor)
            self.mirror_camera_to_partner()
            scene_pos = self.mapToScene(event.position().toPoint())
            if self._double_view_active and self._partner_view is not None:
                self._partner_view.set_mirrored_cursor_pos(
                    QPointF(self.config.width_px - scene_pos.x(), scene_pos.y())
                )
            if self.current_mode == "shape" and self._drawing_custom_cutout is not None:
                board_pos = self.board_item.mapFromScene(scene_pos)
                cx = (self.config.width_px - board_pos.x()) if self.config.view_side == "bottom" else board_pos.x()
                cy = board_pos.y()
                sx, sy, guides = self._snap_custom_vertex(cx, cy, self._drawing_custom_cutout.vertices)
                dx_disp = (self.config.width_px - sx) if self.config.view_side == "bottom" else sx
                self.board_item.drawing_custom_cursor = QPointF(dx_disp, sy)
                self.board_item.custom_snap_guides = guides
                self.board_item.update()
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.current_mode == "shape"
            and self._drawing_custom_cutout is not None
        ):
            if len(self._drawing_custom_cutout.vertices) >= 3:
                self._finish_custom_drawing()
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        # Pan handlers
        if event.button() == Qt.MouseButton.MiddleButton or (event.button() == Qt.MouseButton.LeftButton and self._space_pressed):
            self._is_panning = True
            self._pan_start_pos = event.position()
            self._update_cursor()
            event.accept()
            return
        elif event.button() == Qt.MouseButton.RightButton:
            if self._bevel_active:
                self._cancel_bevel()
                event.accept()
                return
            if self._drawing_custom_cutout is not None:
                self._cancel_custom_drawing()
                event.accept()
                return
            if self.placement_type_id:
                self.cancel_placement_mode()
                event.accept()
                return
            if self._solder_drag_active:
                self._solder_drag_active = False
                self.solder_item.set_current_drawing(None)
                self._sync_partner_solder()
                event.accept()
                return
            if self._jumper_drag_active:
                self._cancel_jumper_preview()
                event.accept()
                return
            if self._jumper_handle_drag_item:
                self._jumper_handle_drag_item._dragging_handle_idx = None
                self._jumper_handle_drag_item = None
                self._jumper_handle_drag_idx = None
                event.accept()
                return
            self._is_panning = True
            self._pan_start_pos = event.position()
            self._update_cursor()
            event.accept()
            return

        scene_pos = self.mapToScene(event.pos())
        col, row = self.config.board_pos_to_grid(scene_pos.x(), scene_pos.y())
        is_shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier) or self._shift_pressed
        is_ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier) or self._ctrl_pressed

        # Placement mode click (allowed both on and outside the perfboard)
        if event.button() == Qt.MouseButton.LeftButton and self.placement_type_id:
            self.add_component(self.placement_type_id, col, row, self.placement_rotation)
            event.accept()
            return

        # SHAPE PERFBOARD MODE (5)
        if event.button() == Qt.MouseButton.LeftButton and self.current_mode == "shape":
            board_pos = self.board_item.mapFromScene(scene_pos)
            if self._bevel_active:
                self._commit_bevel()
                event.accept()
                return

            if self._drawing_custom_cutout is not None:
                verts = self._drawing_custom_cutout.vertices
                if len(verts) >= 3:
                    v0x, v0y = verts[0]
                    d0x = (self.config.width_px - v0x) if self.config.view_side == "bottom" else v0x
                    if math.hypot(board_pos.x() - d0x, board_pos.y() - v0y) <= 10.0 / max(0.25, self._zoom_factor):
                        self._finish_custom_drawing()
                        event.accept()
                        return
                cx = (self.config.width_px - board_pos.x()) if self.config.view_side == "bottom" else board_pos.x()
                cy = board_pos.y()
                sx, sy, _ = self._snap_custom_vertex(cx, cy, verts)
                verts.append((sx, sy))
                self.board_item.update()
                event.accept()
                return

            self._cutout_click_hits = []
            self._cutout_click_was_selected = False
            if self.active_cutout_shape == "select":
                sel_cutout = self._get_selected_cutout()
                if sel_cutout is not None:
                    if self._hit_test_cutout_rot_handle(board_pos, sel_cutout):
                        rect = self._cutout_display_rect(sel_cutout)
                        center = rect.center()
                        self._cutout_drag_mode = "rotate"
                        self._cutout_drag_start_board = board_pos
                        self._cutout_rot_start_angle = math.degrees(
                            math.atan2(board_pos.y() - center.y(), board_pos.x() - center.x())
                        )
                        self._cutout_rot_orig = sel_cutout.rotation
                        self._cutout_drag_changed = False
                        event.accept()
                        return

                    v_idx = self._hit_test_cutout_vertex(board_pos, sel_cutout)
                    if v_idx is not None:
                        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                            self._select_vertex(v_idx, toggle=True)
                            event.accept()
                            return
                        self._select_vertex(v_idx, toggle=False)
                        self._cutout_drag_mode = "move_vertex"
                        self._cutout_drag_start_board = board_pos
                        self._cutout_orig_vertices = list(sel_cutout.vertices)
                        self._cutout_drag_changed = False
                        event.accept()
                        return

                    handle = self._hit_test_cutout_handle(board_pos, sel_cutout)
                    if handle:
                        rect = self._cutout_display_rect(sel_cutout)
                        self._cutout_drag_mode = "resize"
                        self._cutout_resize_handle = handle
                        self._cutout_drag_start_board = board_pos
                        self._cutout_orig_rect = (rect.left(), rect.top(), rect.width(), rect.height())
                        self._cutout_orig_vertices = list(sel_cutout.vertices)
                        self._cutout_drag_changed = False
                        event.accept()
                        return

                hits = self._hit_test_cutouts(board_pos)
                if hits:
                    self._cutout_click_hits = hits
                    if self.selected_cutout_uid and any(c.uid == self.selected_cutout_uid for c in hits):
                        self._cutout_click_was_selected = True
                        target = self._get_selected_cutout() or hits[0]
                    else:
                        self._cutout_click_was_selected = False
                        target = hits[0]
                        self._select_cutout(target.uid)
                    self._select_vertex(None)
                    rect = self._cutout_display_rect(target)
                    self._cutout_drag_mode = "move"
                    self._cutout_resize_handle = ""
                    self._cutout_drag_start_board = board_pos
                    self._cutout_orig_rect = (rect.left(), rect.top(), rect.width(), rect.height())
                    self._cutout_orig_vertices = list(target.vertices)
                    self._cutout_drag_changed = False
                    self.setCursor(Qt.CursorShape.SizeAllCursor)
                    event.accept()
                    return

                # Clicked empty space in Select mode: deselect without drawing
                self._select_cutout(None)
                self._select_vertex(None)
                event.accept()
                return

            # Cutter shape active: guarantee drawing new shape (even over existing shapes)
            self._select_vertex(None)
            if self.active_cutout_shape == "custom":
                cx = (self.config.width_px - board_pos.x()) if self.config.view_side == "bottom" else board_pos.x()
                cy = board_pos.y()
                new_custom = BoardCutout(
                    shape="custom",
                    inverted=self.active_cutout_inverted,
                    vertices=[(cx, cy)],
                )
                self._drawing_custom_cutout = new_custom
                self.board_item.drawing_custom_cutout = new_custom
                self.board_item.drawing_custom_cursor = board_pos
                self.board_item.custom_snap_guides = []
                self.board_item.update()
                event.accept()
                return

            new_cutout = BoardCutout(
                shape=self.active_cutout_shape,
                corner_radius=self.active_cutout_corner_radius,
                inverted=(self.active_cutout_inverted or self.active_cutout_shape == "inverted_oval"),
            )
            self._set_cutout_from_display_rect(
                new_cutout, QRectF(board_pos.x(), board_pos.y(), 4.0, 4.0)
            )
            self.config.cutouts.append(new_cutout)
            self._select_cutout(new_cutout.uid)
            self._cutout_drag_mode = "create"
            self._cutout_resize_handle = ""
            self._cutout_drag_start_board = board_pos
            self._cutout_orig_rect = (board_pos.x(), board_pos.y(), 4.0, 4.0)
            self._cutout_drag_changed = True
            self.board_item.update()
            self._notify_partner_sync(full=False)
            event.accept()
            return

        # Perfboard edge / corner resize initiation (works cleanly outside hole pads)
        if event.button() == Qt.MouseButton.LeftButton and not self.placement_type_id:
            edges = self._detect_board_resize_edges(scene_pos)
            if edges:
                self._board_resize_active = True
                self._board_resize_edges = edges
                self._board_resize_changed = False
                self._board_resize_last_vp_pos = event.position()
                self._board_resize_accum_x = 0.0
                self._board_resize_accum_y = 0.0
                self._board_resize_scroll_rem_x = 0.0
                self._board_resize_scroll_rem_y = 0.0
                self.board_item.set_hovered_hole(-1, -1)
                self.board_item.set_resize_edges(edges, active_drag=True)
                self._update_cursor()
                event.accept()
                return

        # AUTOCONNECT MODE (4)
        if event.button() == Qt.MouseButton.LeftButton and self.current_mode == "autoconnect":
            target = self.identify_target_at(col, row, scene_pos)
            if target:
                if is_shift:
                    found_idx = -1
                    for idx, t in enumerate(self.autoconnect_selected_targets):
                        if t == target:
                            found_idx = idx
                            break
                    if found_idx >= 0:
                        self.autoconnect_selected_targets.pop(found_idx)
                    else:
                        self.autoconnect_selected_targets.append(target)
                else:
                    self.autoconnect_selected_targets = [target]
            else:
                if not is_shift:
                    self.autoconnect_selected_targets.clear()

            self.autoconnect_overlay.set_selected_targets(self.autoconnect_selected_targets)
            self._sync_partner_autoconnect_overlay()
            self.autoconnect_selection_changed.emit(self.autoconnect_selected_targets)
            event.accept()
            return

        # SOLDER MODE (2)
        if event.button() == Qt.MouseButton.LeftButton and self.current_mode == "solder":
            if is_ctrl:
                # SOLDER ERASE MODE: delete solder at clicked hole
                self._solder_erase_active = True
                self._solder_last_hole = (col, row)
                if self.config.is_valid_hole(col, row):
                    if self.solder_mgr.delete_at_hole(col, row):
                        self.solder_item.update()
                        self._sync_partner_solder()
                event.accept()
                return
            else:
                # SOLDER DRAW MODE
                if self.config.is_valid_hole(col, row):
                    self._solder_drag_active = True
                    self._solder_start_hole = (col, row)
                    self._solder_last_hole = (col, row)
                    existing_trace = self.solder_mgr.find_trace_with_hole(col, row)
                    if not existing_trace:
                        t = self.solder_mgr.create_trace()
                        t.add_single_hole((col, row))
                    self.solder_item.update()
                    self._sync_partner_solder()
                event.accept()
                return

        # JUMPER MODE (3)
        if event.button() == Qt.MouseButton.LeftButton and self.current_mode == "jumper":
            # 1. Check Shift + Click to insert a bend point on a jumper wire body!
            if is_shift:
                for j_item in reversed(self.jumper_items):
                    seg_idx = j_item.get_segment_index_at(scene_pos, threshold=12.0)
                    if seg_idx is not None:
                        # Insert bend point at nearest grid hole (col, row)
                        bend_idx = j_item.jumper.insert_bend_at_segment(col, row, seg_idx)
                        j_item.prepareGeometryChange()
                        j_item.update()
                        # Select and immediately enable dragging of this new bend point!
                        self._jumper_handle_drag_item = j_item
                        self._jumper_handle_drag_idx = bend_idx + 1 # in all_points: 0 is start, 1..N-2 bends
                        j_item._dragging_handle_idx = self._jumper_handle_drag_idx
                        self.scene.clearSelection()
                        j_item.setSelected(True)
                        self.selection_changed.emit(j_item)
                        self.record_undo_snapshot()
                        event.accept()
                        return

            # 2. Check clicking on existing handle of a jumper (endpoints or bends) to drag it
            for j_item in self.jumper_items:
                h_idx = j_item.get_handle_at(scene_pos)
                if h_idx is not None:
                    self._jumper_handle_drag_item = j_item
                    self._jumper_handle_drag_idx = h_idx
                    j_item._dragging_handle_idx = h_idx
                    self.scene.clearSelection()
                    j_item.setSelected(True)
                    self.selection_changed.emit(j_item)
                    event.accept()
                    return

            # 3. Otherwise: start drawing a new straight jumper from off-grid pin, off-board aligned pin, or perfboard hole
            pin_hit = self._find_off_grid_pin_at(scene_pos)
            if pin_hit is not None:
                comp_inst, pin_idx, pin_name, sc_val, sr_val = pin_hit
                start_pin = (comp_inst.uid, pin_idx, pin_name)
                self._jumper_drag_active = True
                self._jumper_start_hole = (sc_val, sr_val)
                self._jumper_start_pin = start_pin
                preview_wire = JumperWire(
                    start_col=sc_val,
                    start_row=sr_val,
                    end_col=sc_val,
                    end_row=sr_val,
                    color=self.active_jumper_color,
                    side=self.config.view_side,
                    start_pin=start_pin,
                )
                self._jumper_preview_item = JumperItem(preview_wire, self.config)
                self._jumper_preview_item.setOpacity(0.8)
                self.scene.addItem(self._jumper_preview_item)
            else:
                offboard_hit = self._find_offboard_aligned_pin_at(scene_pos)
                start_hole = None
                if offboard_hit is not None:
                    start_hole = (offboard_hit[1], offboard_hit[2])
                elif self.config.is_valid_hole(col, row):
                    start_hole = (col, row)
                if start_hole is not None:
                    sc, sr = start_hole
                    self._jumper_drag_active = True
                    self._jumper_start_hole = (sc, sr)
                    self._jumper_start_pin = None
                    preview_wire = JumperWire(
                        start_col=sc, start_row=sr, end_col=sc, end_row=sr,
                        color=self.active_jumper_color, side=self.config.view_side
                    )
                    self._jumper_preview_item = JumperItem(preview_wire, self.config)
                    self._jumper_preview_item.setOpacity(0.8)
                    self.scene.addItem(self._jumper_preview_item)
            event.accept()
            return

        # SELECT MODE (1)
        if event.button() == Qt.MouseButton.LeftButton and self.current_mode == "select":
            # Check if clicking on an endpoint or bend handle of any jumper wire
            for j_item in self.jumper_items:
                h_idx = j_item.get_handle_at(scene_pos)
                if h_idx is not None:
                    self._jumper_handle_drag_item = j_item
                    self._jumper_handle_drag_idx = h_idx
                    j_item._dragging_handle_idx = h_idx
                    self.scene.clearSelection()
                    j_item.setSelected(True)
                    self.selection_changed.emit(j_item)
                    event.accept()
                    return

            # Check if clicking on a visible/highlighted solder path
            trace = self._find_solder_trace_at(col, row, scene_pos)
            if trace is not None:
                self.select_solder_trace(trace)
                event.accept()
                return

        super().mousePressEvent(event)

        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.current_mode == "select"
            and not self.scene.selectedItems()
            and self._selected_solder_trace is not None
        ):
            self.select_solder_trace(None)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._is_panning:
            delta = event.position() - self._pan_start_pos
            self._pan_start_pos = event.position()
            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - delta.x()))
            self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - delta.y()))
            self.mirror_camera_to_partner()
            event.accept()
            return

        if self._board_resize_active:
            cur_vp = event.position()
            dvp = cur_vp - self._board_resize_last_vp_pos
            self._board_resize_last_vp_pos = cur_vp
            trans = self.transform()
            scale_x = abs(trans.m11()) or 1.0
            scale_y = abs(trans.m22()) or 1.0
            self._board_resize_accum_x += dvp.x() / scale_x
            self._board_resize_accum_y += dvp.y() / scale_y

            pitch = self.config.pitch_px
            steps_x = int(self._board_resize_accum_x / pitch + (0.5 if self._board_resize_accum_x >= 0 else -0.5))
            steps_y = int(self._board_resize_accum_y / pitch + (0.5 if self._board_resize_accum_y >= 0 else -0.5))

            req_l = -steps_x if "L" in self._board_resize_edges else 0
            req_r = steps_x if "R" in self._board_resize_edges else 0
            req_t = -steps_y if "T" in self._board_resize_edges else 0
            req_b = steps_y if "B" in self._board_resize_edges else 0

            if req_l or req_r or req_t or req_b:
                app_l, app_r, app_t, app_b = self.resize_board_from_edges(
                    add_vis_left=req_l,
                    add_vis_right=req_r,
                    add_top=req_t,
                    add_bottom=req_b,
                    shift_view=True,
                )
                if "R" in self._board_resize_edges:
                    self._board_resize_accum_x -= app_r * pitch
                elif "L" in self._board_resize_edges:
                    self._board_resize_accum_x += app_l * pitch

                if "B" in self._board_resize_edges:
                    self._board_resize_accum_y -= app_b * pitch
                elif "T" in self._board_resize_edges:
                    self._board_resize_accum_y += app_t * pitch

                if app_l or app_r or app_t or app_b:
                    self._board_resize_changed = True
                    self.board_item.set_resize_edges(self._board_resize_edges, active_drag=True)

            event.accept()
            return

        scene_pos = self.mapToScene(event.pos())
        col, row = self.config.board_pos_to_grid(scene_pos.x(), scene_pos.y())
        is_shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier) or self._shift_pressed
        is_ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier) or self._ctrl_pressed

        # Update mirrored '+' cursor on partner viewport in Double-View
        if self._double_view_active and self._partner_view is not None:
            self._partner_view.set_mirrored_cursor_pos(
                QPointF(self.config.width_px - scene_pos.x(), scene_pos.y())
            )

        # SHAPE PERFBOARD MODE (5): drag or hover
        if self.current_mode == "shape":
            board_pos = self.board_item.mapFromScene(scene_pos)
            if self._bevel_active and self._bevel_orig_vertices and self._bevel_vertex_indices:
                if self._bevel_start_pos is None:
                    self._bevel_start_pos = board_pos
                dist = math.hypot(
                    board_pos.x() - self._bevel_start_pos.x(),
                    board_pos.y() - self._bevel_start_pos.y(),
                )
                self.board_item.bevel_guide_line = (self._bevel_start_pos, board_pos)
                self._update_bevel_preview(dist)
                super().mouseMoveEvent(event)
                return

            if self._drawing_custom_cutout is not None:
                cx = (self.config.width_px - board_pos.x()) if self.config.view_side == "bottom" else board_pos.x()
                cy = board_pos.y()
                sx, sy, guides = self._snap_custom_vertex(cx, cy, self._drawing_custom_cutout.vertices)
                dx_disp = (self.config.width_px - sx) if self.config.view_side == "bottom" else sx
                self.board_item.drawing_custom_cursor = QPointF(dx_disp, sy)
                self.board_item.custom_snap_guides = guides
                self.board_item.update()
                super().mouseMoveEvent(event)
                self.setCursor(Qt.CursorShape.CrossCursor)
                return

            sel_cutout = self._get_selected_cutout()
            if self._cutout_drag_mode and sel_cutout is not None:
                ox, oy, ow, oh = self._cutout_orig_rect
                if self._cutout_drag_mode == "create":
                    rect = QRectF(self._cutout_drag_start_board, board_pos).normalized()
                    if rect.width() < 4.0:
                        rect.setWidth(4.0)
                    if rect.height() < 4.0:
                        rect.setHeight(4.0)
                    self._set_cutout_from_display_rect(sel_cutout, rect)
                    self._cutout_drag_changed = True
                elif self._cutout_drag_mode == "move":
                    dx = board_pos.x() - self._cutout_drag_start_board.x()
                    dy = board_pos.y() - self._cutout_drag_start_board.y()
                    self._set_cutout_from_display_rect(
                        sel_cutout, QRectF(ox + dx, oy + dy, ow, oh)
                    )
                    if sel_cutout.shape == "custom" and self._cutout_orig_vertices:
                        cdx = -dx if self.config.view_side == "bottom" else dx
                        sel_cutout.vertices = [(vx + cdx, vy + dy) for vx, vy in self._cutout_orig_vertices]
                        sel_cutout.recompute_custom_bounds()
                    if math.hypot(dx, dy) > 2.5:
                        self._cutout_drag_changed = True
                elif self._cutout_drag_mode == "rotate":
                    rect = self._cutout_display_rect(sel_cutout)
                    center = rect.center()
                    cur_ang = math.degrees(math.atan2(board_pos.y() - center.y(), board_pos.x() - center.x()))
                    delta_ang = cur_ang - self._cutout_rot_start_angle
                    while delta_ang > 180.0:
                        delta_ang -= 360.0
                    while delta_ang < -180.0:
                        delta_ang += 360.0
                    if self.config.view_side == "bottom":
                        delta_ang = -delta_ang
                    raw_ang = self._cutout_rot_orig + delta_ang
                    if is_ctrl and is_shift:
                        new_ang = round(raw_ang / 15.0) * 15.0
                    elif is_shift:
                        new_ang = self._cutout_rot_orig + round(delta_ang / 15.0) * 15.0
                    else:
                        new_ang = raw_ang
                    # Normalize to (-180, 180]
                    new_ang = ((new_ang + 180.0) % 360.0) - 180.0
                    sel_cutout.rotation = new_ang
                    self._cutout_drag_changed = True
                elif self._cutout_drag_mode == "move_vertex" and self.selected_vertex_idx is not None:
                    local_pos = self._board_to_cutout_local_display(board_pos, sel_cutout)
                    cx = (self.config.width_px - local_pos.x()) if self.config.view_side == "bottom" else local_pos.x()
                    cy = local_pos.y()
                    other_verts = [
                        v for i, v in enumerate(sel_cutout.vertices) if i != self.selected_vertex_idx
                    ]
                    sx, sy, guides = self._snap_custom_vertex(cx, cy, other_verts)
                    sel_cutout.vertices[self.selected_vertex_idx] = (sx, sy)
                    sel_cutout.recompute_custom_bounds()
                    self.board_item.custom_snap_guides = guides
                    self._cutout_drag_changed = True
                elif self._cutout_drag_mode == "resize":
                    orig_center = QPointF(ox + ow * 0.5, oy + oh * 0.5)
                    rot = -sel_cutout.rotation if self.config.view_side == "bottom" else sel_cutout.rotation
                    t_inv = QTransform()
                    t_inv.translate(orig_center.x(), orig_center.y())
                    t_inv.rotate(-rot)
                    t_inv.translate(-orig_center.x(), -orig_center.y())
                    loc_cur = t_inv.map(board_pos)
                    loc_start = t_inv.map(self._cutout_drag_start_board)
                    dx = loc_cur.x() - loc_start.x()
                    dy = loc_cur.y() - loc_start.y()

                    x1, y1, x2, y2 = ox, oy, ox + ow, oy + oh
                    h_code = self._cutout_resize_handle
                    min_sz = 8.0
                    if "L" in h_code:
                        x1 = min(x2 - min_sz, ox + dx)
                    if "R" in h_code:
                        x2 = max(x1 + min_sz, ox + ow + dx)
                    if "T" in h_code:
                        y1 = min(y2 - min_sz, oy + dy)
                    if "B" in h_code:
                        y2 = max(y1 + min_sz, oy + oh + dy)
                    nw, nh = x2 - x1, y2 - y1
                    dcx_loc = (x1 + x2) * 0.5 - orig_center.x()
                    dcy_loc = (y1 + y2) * 0.5 - orig_center.y()
                    rad = math.radians(rot)
                    dcx_w = dcx_loc * math.cos(rad) - dcy_loc * math.sin(rad)
                    dcy_w = dcx_loc * math.sin(rad) + dcy_loc * math.cos(rad)
                    new_cx = orig_center.x() + dcx_w
                    new_cy = orig_center.y() + dcy_w
                    new_disp_rect = QRectF(new_cx - nw * 0.5, new_cy - nh * 0.5, nw, nh)
                    self._set_cutout_from_display_rect(sel_cutout, new_disp_rect)
                    if sel_cutout.shape == "custom" and self._cutout_orig_vertices and ow > 1e-6 and oh > 1e-6:
                        # Scale vertices from original canonical bounds to new canonical bounds
                        old_xs = [v[0] for v in self._cutout_orig_vertices]
                        old_ys = [v[1] for v in self._cutout_orig_vertices]
                        omx, omy = min(old_xs), min(old_ys)
                        omw = max(4.0, max(old_xs) - omx)
                        omh = max(4.0, max(old_ys) - omy)
                        sel_cutout.vertices = [
                            (
                                sel_cutout.x + ((vx - omx) / omw) * sel_cutout.w,
                                sel_cutout.y + ((vy - omy) / omh) * sel_cutout.h,
                            )
                            for vx, vy in self._cutout_orig_vertices
                        ]
                    if math.hypot(dx, dy) > 0.1:
                        self._cutout_drag_changed = True
                self.board_item.update()
                self._notify_partner_sync(full=False)
                event.accept()
                return

            super().mouseMoveEvent(event)
            # Hover cursor feedback in shape mode
            if self.active_cutout_shape != "select":
                self.setCursor(Qt.CursorShape.CrossCursor)
            elif sel_cutout is not None and self._hit_test_cutout_rot_handle(board_pos, sel_cutout):
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            elif sel_cutout is not None and self._hit_test_cutout_vertex(board_pos, sel_cutout) is not None:
                self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                handle = self._hit_test_cutout_handle(board_pos, sel_cutout) if sel_cutout is not None else ""
                if handle in ("TL", "BR"):
                    self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                elif handle in ("TR", "BL"):
                    self.setCursor(Qt.CursorShape.SizeBDiagCursor)
                elif handle in ("L", "R"):
                    self.setCursor(Qt.CursorShape.SizeHorCursor)
                elif handle in ("T", "B"):
                    self.setCursor(Qt.CursorShape.SizeVerCursor)
                elif self._hit_test_cutout(board_pos) is not None:
                    self.setCursor(Qt.CursorShape.SizeAllCursor)
                else:
                    self.setCursor(Qt.CursorShape.ArrowCursor)
            self.board_item.set_hovered_hole(-1, -1)
            return

        # Detect hovered resize border when idle (not placement/stroke/handle dragging)
        hover_edges = ""
        if (
            not self._space_pressed
            and not self.placement_type_id
            and not self._solder_drag_active
            and not self._solder_erase_active
            and not self._jumper_drag_active
            and self._jumper_handle_drag_item is None
            and self.current_mode != "shape"
        ):
            hover_edges = self._detect_board_resize_edges(scene_pos)
        if hover_edges != self._hovered_resize_edges:
            self._hovered_resize_edges = hover_edges
            self.board_item.set_resize_edges(hover_edges, active_drag=False)
            self._update_cursor()

        # Update hover hole reticle (suppress when hovering an outer resize edge)
        if not hover_edges and self.config.is_valid_hole(col, row):
            self.board_item.set_hovered_hole(col, row)
            if self._double_view_active and self._partner_view is not None:
                self._partner_view.board_item.set_hovered_hole(col, row)
            col_name = col_index_to_name(col)
            self.hover_hole_changed.emit(col, row, col_name)
        else:
            self.board_item.set_hovered_hole(-1, -1)
            if self._double_view_active and self._partner_view is not None:
                self._partner_view.board_item.set_hovered_hole(-1, -1)

        # Move placement ghost if active
        if self.placement_ghost and self.placement_ghost_item:
            self.placement_ghost.grid_x = col
            self.placement_ghost.grid_y = row
            self.placement_ghost_item.update_position_from_grid()

        # Selection Mode on Back View (or any side in Transparent Mode or when Board is Hidden): Highlight Entire Conductive Net!
        board_hidden = not self.board_item.isVisible()
        if self.current_mode == "select" and (
            self.config.view_side == "bottom" or bool(getattr(self.config, "transparent", False)) or board_hidden
        ):
            net_traces, net_jumpers = self.get_conductive_net_at(col, row, scene_pos)
            self._apply_net_highlight(net_traces, net_jumpers)
        else:
            self._clear_net_highlight()

        # AutoConnect Mode: Update hover indicator
        if self.current_mode == "autoconnect":
            hover_target = self.identify_target_at(col, row, scene_pos)
            if hover_target:
                self.autoconnect_overlay.set_hover(hover_target.center_hole, hover_target.label)
            else:
                self.autoconnect_overlay.set_hover(None)

        # Handle Jumper endpoint / bend point dragging
        if self._jumper_handle_drag_item is not None and self._jumper_handle_drag_idx is not None:
            all_pts = self._jumper_handle_drag_item.jumper.all_points()
            is_endpoint = (
                self._jumper_handle_drag_idx == 0
                or self._jumper_handle_drag_idx == len(all_pts) - 1
            )
            adj_idx = 1 if self._jumper_handle_drag_idx == 0 else self._jumper_handle_drag_idx - 1
            anchor_pt = all_pts[adj_idx] if 0 <= adj_idx < len(all_pts) else None

            if is_endpoint:
                c_target, r_target, pin_ref = self._snap_jumper_endpoint(
                    scene_pos, col, row, anchor_pt=anchor_pt, is_shift=is_shift
                )
            else:
                pin_ref = None
                c_target, r_target = col, row
                if is_shift and anchor_pt is not None:
                    ac, ar = int(round(anchor_pt[0])), int(round(anchor_pt[1]))
                    if abs(c_target - ac) >= abs(r_target - ar):
                        r_target = ar
                    else:
                        c_target = ac
                c_target = max(0, min(self.config.cols - 1, c_target))
                r_target = max(0, min(self.config.rows - 1, r_target))

            self._jumper_handle_drag_item.jumper.move_point(
                self._jumper_handle_drag_idx, c_target, r_target, pin_ref=pin_ref
            )
            self._jumper_handle_drag_item.prepareGeometryChange()
            self._jumper_handle_drag_item.update()
            self._sync_partner_jumper(self._jumper_handle_drag_item.jumper)
            self.selection_changed.emit(self._jumper_handle_drag_item)
            event.accept()
            return

        # Solder Erase drag (with LCtrl)
        if self._solder_erase_active and self.current_mode == "solder":
            if self._solder_last_hole and (col, row) != self._solder_last_hole:
                line_holes = bresenham_line(
                    self._solder_last_hole[0], self._solder_last_hole[1],
                    col, row
                )
                changed = False
                for hc, hr in line_holes:
                    if self.config.is_valid_hole(hc, hr):
                        if self.solder_mgr.delete_at_hole(hc, hr):
                            changed = True
                self._solder_last_hole = (col, row)
                if changed:
                    self.solder_item.update()
                    self._sync_partner_solder()
            event.accept()
            return

        # Solder drawing drag
        if self._solder_drag_active and self._solder_start_hole:
            c_target, r_target = col, row
            if is_shift:
                sc, sr = self._solder_start_hole
                dx = abs(c_target - sc)
                dy = abs(r_target - sr)
                if dx >= dy:
                    r_target = sr
                else:
                    c_target = sc

            if self.config.is_valid_hole(c_target, r_target) and self._solder_last_hole:
                if (c_target, r_target) != self._solder_last_hole:
                    line_holes = bresenham_line(
                        self._solder_last_hole[0], self._solder_last_hole[1],
                        c_target, r_target
                    )
                    for i in range(len(line_holes) - 1):
                        self.solder_mgr.connect_holes(line_holes[i], line_holes[i + 1])
                    self._solder_last_hole = (c_target, r_target)
                    self.solder_item.update()
                    self._sync_partner_solder()
            event.accept()
            return

        # Jumper rubberband drag
        if self._jumper_drag_active and self._jumper_start_hole and self._jumper_preview_item:
            c_target, r_target, end_pin = self._snap_jumper_endpoint(
                scene_pos, col, row, anchor_pt=self._jumper_start_hole, is_shift=is_shift
            )
            self._jumper_preview_item.jumper.end_col = c_target
            self._jumper_preview_item.jumper.end_row = r_target
            self._jumper_preview_item.jumper.end_pin = end_pin
            self._jumper_preview_item.prepareGeometryChange()
            self._jumper_preview_item.update()
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._is_panning:
            self._is_panning = False
            self._update_cursor()
            event.accept()
            return

        # Finish Shape Perfboard drag
        if self._cutout_drag_mode is not None:
            mode = self._cutout_drag_mode
            changed = self._cutout_drag_changed
            self._cutout_drag_mode = None
            self._cutout_resize_handle = ""
            self._cutout_drag_changed = False
            sel_cutout = self._get_selected_cutout()
            if mode == "create" and sel_cutout is not None:
                if sel_cutout.w < 6.0 and sel_cutout.h < 6.0:
                    cx = self._cutout_drag_start_board.x()
                    cy = self._cutout_drag_start_board.y()
                    self._set_cutout_from_display_rect(
                        sel_cutout, QRectF(cx - 30.0, cy - 30.0, 60.0, 60.0)
                    )
                    changed = True
                self._switch_cutout_tool_to_select()
            elif mode == "move" and not changed and self._cutout_click_was_selected:
                if len(self._cutout_click_hits) > 1:
                    # Cycle to the next shape behind the current selection; wrap back to top
                    uids = [c.uid for c in self._cutout_click_hits]
                    if self.selected_cutout_uid in uids:
                        cur_idx = uids.index(self.selected_cutout_uid)
                        next_uid = uids[(cur_idx + 1) % len(uids)]
                        self._select_cutout(next_uid)
                else:
                    # Nothing else under the cursor to cycle to -> deselect
                    self._select_cutout(None)
                    self._select_vertex(None)
            self.board_item.custom_snap_guides = []
            self._cutout_click_hits = []
            self._cutout_click_was_selected = False
            self.board_item.update()
            self._notify_partner_sync(full=False)
            if changed:
                self.record_undo_snapshot()
                self.cutout_selection_changed.emit(self.selected_cutout_uid)
            self._update_cursor()
            event.accept()
            return

        # Finish board edge resize drag
        if self._board_resize_active:
            changed = self._board_resize_changed
            self._board_resize_active = False
            self._board_resize_edges = ""
            self._board_resize_changed = False
            scene_pos = self.mapToScene(event.pos())
            self._hovered_resize_edges = self._detect_board_resize_edges(scene_pos)
            self.board_item.set_resize_edges(self._hovered_resize_edges, active_drag=False)
            self._update_cursor()
            if changed:
                self.record_undo_snapshot()
                self.board_resized.emit(self.config.cols, self.config.rows)
                log_action("Board resized via edge drag", f"cols={self.config.cols}, rows={self.config.rows}")
            event.accept()
            return

        # Finish handle drag
        if self._jumper_handle_drag_item is not None:
            self._jumper_handle_drag_item._dragging_handle_idx = None
            self._jumper_handle_drag_item.update()
            self._jumper_handle_drag_item = None
            self._jumper_handle_drag_idx = None
            self.record_undo_snapshot()
            event.accept()
            return

        # Finish solder erase
        if self._solder_erase_active:
            self._solder_erase_active = False
            self._solder_last_hole = None
            self.record_undo_snapshot()
            event.accept()
            return

        # Finish solder stroke
        if self._solder_drag_active:
            self._solder_drag_active = False
            self._solder_start_hole = None
            self._solder_last_hole = None
            self.solder_item.set_current_drawing(None)
            self.solder_item.update()
            self.record_undo_snapshot()
            event.accept()
            return

        # Finish jumper stroke
        if self._jumper_drag_active:
            self._jumper_drag_active = False
            scene_pos = self.mapToScene(event.pos())
            col, row = self.config.board_pos_to_grid(scene_pos.x(), scene_pos.y())
            is_shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier) or self._shift_pressed

            c_target, r_target, end_pin = self._snap_jumper_endpoint(
                scene_pos, col, row, anchor_pt=self._jumper_start_hole, is_shift=is_shift
            )

            start_h = self._jumper_start_hole
            start_pin = self._jumper_start_pin
            self._cancel_jumper_preview()

            if start_h and (
                (start_pin is not None and end_pin != start_pin)
                or (start_pin is None and (end_pin is not None or (c_target, r_target) != start_h))
            ):
                new_jumper = self.add_jumper(
                    start_h[0],
                    start_h[1],
                    c_target,
                    r_target,
                    start_pin=start_pin,
                    end_pin=end_pin,
                )
                self.scene.clearSelection()
                new_jumper.setSelected(True)
                self.selection_changed.emit(new_jumper)

            self._jumper_start_hole = None
            self._jumper_start_pin = None
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        if not self._board_resize_active and self._hovered_resize_edges:
            self._hovered_resize_edges = ""
            self.board_item.set_resize_edges("", active_drag=False)
            self._update_cursor()
        self._clear_net_highlight()
        self.board_item.set_hovered_hole(-1, -1)
        if self._partner_view is not None:
            self._partner_view.set_mirrored_cursor_pos(None)
            self._partner_view.board_item.set_hovered_hole(-1, -1)
        super().leaveEvent(event)

    def _cancel_jumper_preview(self):
        if self._jumper_preview_item:
            self.scene.removeItem(self._jumper_preview_item)
            self._jumper_preview_item = None
        self._jumper_drag_active = False
        self._jumper_start_hole = None
        self._jumper_start_pin = None

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        modifiers = event.modifiers()
        key_seq_name = QKeySequence(key).toString()
        key_display = key_seq_name if key_seq_name else (event.text() if event.text() else f"Key_{key}")
        mod_names = []
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            mod_names.append("Shift")
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            mod_names.append("Ctrl")
        if modifiers & Qt.KeyboardModifier.AltModifier:
            mod_names.append("Alt")
        mod_str = "+".join(mod_names)

        sel = self.get_selected_component_item()
        sel_desc = f"comp={sel.instance.type_id}" if sel else ("jumper" if self.get_selected_jumper_item() else "none")
        log_keypress(key_display, mod_str, f"mode={self.current_mode}, selected={sel_desc}")

        if key == Qt.Key.Key_Shift:
            self._shift_pressed = True
        elif key in (Qt.Key.Key_Control,):
            self._ctrl_pressed = True
            self._update_cursor()

        if key == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_pressed = True
            self._update_cursor()
            event.accept()
            return

        # Undo / Redo shortcuts (Ctrl+Z for undo, Ctrl+Y or Ctrl+Shift+Z for redo)
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_Z:
                if modifiers & Qt.KeyboardModifier.ShiftModifier:
                    self.redo()
                else:
                    self.undo()
                event.accept()
                return
            elif key == Qt.Key.Key_Y:
                self.redo()
                event.accept()
                return
            elif key == Qt.Key.Key_C:
                if self.copy_selection():
                    event.accept()
                    return
            elif key == Qt.Key.Key_V:
                if self.paste_selection():
                    event.accept()
                    return
            elif key == Qt.Key.Key_G:
                if self.current_mode == "autoconnect":
                    if modifiers & Qt.KeyboardModifier.ShiftModifier:
                        self.ungroup_selected_targets()
                    else:
                        self.group_selected_targets()
                    event.accept()
                    return

        # Keyboard mode switching: 1 = Select, 2 = Solder, 3 = Jumper
        if key == Qt.Key.Key_1:
            self.set_mode("select")
            event.accept()
            return
        elif key == Qt.Key.Key_2:
            self.set_mode("solder")
            event.accept()
            return
        elif key == Qt.Key.Key_3:
            self.set_mode("jumper")
            event.accept()
            return
        elif key == Qt.Key.Key_4:
            self.set_mode("autoconnect")
            event.accept()
            return
        elif key == Qt.Key.Key_5:
            self.set_mode("shape")
            event.accept()
            return

        elif key == Qt.Key.Key_B and (modifiers & Qt.KeyboardModifier.ControlModifier):
            if self.current_mode == "shape" and self._start_bevel():
                event.accept()
                return

        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.current_mode == "shape" and self._drawing_custom_cutout is not None:
                if len(self._drawing_custom_cutout.vertices) >= 3:
                    self._finish_custom_drawing()
                event.accept()
                return
            if self.current_mode == "autoconnect":
                self.perform_autoconnect()
                event.accept()
                return

        elif key == Qt.Key.Key_R:
            # Rotate
            if self.placement_ghost and self.placement_ghost_item:
                if modifiers & Qt.KeyboardModifier.ShiftModifier:
                    self.placement_ghost_item.rotate_ccw()
                else:
                    self.placement_ghost_item.rotate_cw()
                self.placement_rotation = self.placement_ghost.rotation
            else:
                selected = self.get_selected_component_item()
                if selected:
                    if modifiers & Qt.KeyboardModifier.ShiftModifier:
                        selected.rotate_ccw()
                    else:
                        selected.rotate_cw()
                    self.selection_changed.emit(selected)
            event.accept()
            return
        elif key == Qt.Key.Key_F:
            self.toggle_view_side()
            event.accept()
            return
        elif key == Qt.Key.Key_H:
            if modifiers & Qt.KeyboardModifier.AltModifier:
                self.unhide_all_objects()
                event.accept()
                return
            if not (modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)):
                if self.hide_selected_object():
                    event.accept()
                    return
        elif key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.remove_selected_item()
            event.accept()
            return
        elif key == Qt.Key.Key_Escape:
            if self.current_mode == "shape":
                if self._bevel_active:
                    self._cancel_bevel()
                elif self._drawing_custom_cutout is not None:
                    self._cancel_custom_drawing()
                elif self.selected_vertex_idx is not None:
                    self._select_vertex(None)
                elif self.selected_cutout_uid is not None:
                    self._select_cutout(None)
                event.accept()
                return
            if self.current_mode == "autoconnect":
                if self.autoconnect_selected_targets:
                    self.autoconnect_selected_targets.clear()
                    self.autoconnect_overlay.set_selected_targets([])
                    self._sync_partner_autoconnect_overlay()
                    self.autoconnect_selection_changed.emit([])
                elif self.autoconnect_groups:
                    self.clear_autoconnect_groups()
            elif self.placement_type_id:
                self.cancel_placement_mode()
            else:
                self.scene.clearSelection()
                if self._selected_solder_trace is not None:
                    self.select_solder_trace(None)
            event.accept()
            return

        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent):
        key = event.key()
        if key == Qt.Key.Key_Shift:
            self._shift_pressed = False
        elif key in (Qt.Key.Key_Control,):
            self._ctrl_pressed = False
            self._update_cursor()
        elif key == Qt.Key.Key_Space:
            self._space_pressed = False
            self._update_cursor()
            event.accept()
            return
        super().keyReleaseEvent(event)

    # Drag and Drop from Toolbox
    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-perfboard-component"):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat("application/x-perfboard-component"):
            scene_pos = self.mapToScene(event.position().toPoint())
            col, row = self.config.board_pos_to_grid(scene_pos.x(), scene_pos.y())
            if self.config.is_valid_hole(col, row):
                self.board_item.set_hovered_hole(col, row)
                self.hover_hole_changed.emit(col, row, col_index_to_name(col))
            else:
                self.board_item.set_hovered_hole(-1, -1)
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasFormat("application/x-perfboard-component"):
            type_id = event.mimeData().data("application/x-perfboard-component").data().decode("utf-8")
            scene_pos = self.mapToScene(event.position().toPoint())
            col, row = self.config.board_pos_to_grid(scene_pos.x(), scene_pos.y())
            self.add_component(type_id, col, row)
            self.board_item.set_hovered_hole(-1, -1)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def zoom_to_fit(self):
        margin = 40
        rect = QRectF(-margin, -margin, self.config.width_px + 2 * margin, self.config.height_px + 2 * margin)
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom_factor = self.transform().m11()
        self.mirror_camera_to_partner()

    def zoom_in(self):
        self._zoom_factor *= 1.25
        self.scale(1.25, 1.25)
        self.mirror_camera_to_partner()

    def zoom_out(self):
        self._zoom_factor /= 1.25
        self.scale(1.0 / 1.25, 1.0 / 1.25)
        self.mirror_camera_to_partner()
