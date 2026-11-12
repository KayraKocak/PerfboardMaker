"""
QGraphicsItem representation of a placed component on the perfboard.
Handles interactive movement, hole snapping, selection, and rotation.
"""
from PyQt6.QtWidgets import (
    QGraphicsItem, QStyleOptionGraphicsItem, QWidget, QGraphicsSceneMouseEvent
)
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath, QTransform
from PyQt6.QtCore import Qt, QRectF, QPointF
from app.models.board import BoardConfig, col_index_to_name
from app.models.placed_component import PlacedComponent
from app.models.component_def import ComponentDef

class ComponentItem(QGraphicsItem):
    def __init__(self, instance: PlacedComponent, comp_def: ComponentDef, config: BoardConfig):
        super().__init__()
        self.instance = instance
        self.comp_def = comp_def
        self.config = config

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(10)  # Components sit above the board

        self._is_dragging = False
        self._drag_start_grid = (instance.grid_x, instance.grid_y)
        self.update_position_from_grid()

    def update_position_from_grid(self):
        """Synchronizes QGraphicsItem scene coordinates with instance grid_x, grid_y."""
        x, y = self.config.grid_to_board_pos(self.instance.grid_x, self.instance.grid_y)
        self.setPos(x, y)

    def refresh_geometry(self):
        """Notifies Qt scene of geometry/shape changes (e.g. rotation or property changes)."""
        self.prepareGeometryChange()
        self.update()

    def _notify_undo_change(self):
        if self.scene() and self.scene().views():
            view = self.scene().views()[0]
            if hasattr(view, "record_undo_snapshot"):
                view.record_undo_snapshot()

    def _notify_live_move(self):
        if self.scene() and self.scene().views():
            view = self.scene().views()[0]
            if hasattr(view, "_on_component_moved_live"):
                view._on_component_moved_live(self.instance)

    def rotate_cw(self):
        """Rotates component 90 deg clockwise with safe geometry update."""
        self.prepareGeometryChange()
        self.instance.rotate_cw()
        self.update()
        self._notify_live_move()
        self._notify_undo_change()

    def rotate_ccw(self):
        """Rotates component 90 deg counter-clockwise with safe geometry update."""
        self.prepareGeometryChange()
        self.instance.rotate_ccw()
        self.update()
        self._notify_live_move()
        self._notify_undo_change()

    def set_rotation(self, angle: int):
        """Sets rotation angle with safe geometry update."""
        self.prepareGeometryChange()
        self.instance.rotation = angle % 360
        self.update()
        self._notify_live_move()
        self._notify_undo_change()

    def shape(self) -> QPainterPath:
        """Accurate hitbox matching the component body and pins."""
        raw_path = self.comp_def.get_shape(self.instance, self.config.pitch_px)
        transform = QTransform()
        if self.config.view_side == "bottom":
            transform.scale(-1.0, 1.0)
        transform.rotate(self.instance.rotation)
        return transform.map(raw_path)

    def boundingRect(self) -> QRectF:
        """Tight bounding rect based on actual shape, with small padding for shadows and borders."""
        return self.shape().boundingRect().adjusted(-4, -4, 4, 4)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget = None):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        p = self.config.pitch_px
        is_bottom = (self.config.view_side == "bottom")
        is_transparent = bool(getattr(self.config, "transparent", False))
        comp_alpha = 0.5 if bool(getattr(self.config, "transparent_components", False)) else 1.0

        if is_bottom:
            painter.scale(-1.0, 1.0)
        painter.rotate(self.instance.rotation)

        painter.save()
        if comp_alpha < 1.0:
            painter.setOpacity(painter.opacity() * comp_alpha)
        if is_bottom:
            if is_transparent:
                painter.save()
                painter.setOpacity(painter.opacity() * 0.38)
                self.comp_def.draw_top(painter, self.instance, p)
                painter.restore()
            self.comp_def.draw_bottom(painter, self.instance, p)
        else:
            self.comp_def.draw_top(painter, self.instance, p)
        painter.restore()

        # Draw crisp selection contour matching exact component body
        if self.isSelected():
            painter.setPen(QPen(QColor(88, 101, 242, 230), 2.0, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(self.comp_def.get_shape(self.instance, p))

        painter.restore()

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedChange:
            is_selected = bool(value)
            if self.scene() is not None:
                self.setZValue(15 if is_selected else 10)
        elif change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.scene():
            new_pos = value
            # Calculate snapped grid coordinate (components may also live outside perfboard bounds)
            col, row = self.config.board_pos_to_grid(new_pos.x(), new_pos.y())

            changed = (col != self.instance.grid_x or row != self.instance.grid_y)
            self.instance.grid_x = col
            self.instance.grid_y = row
            if changed:
                self._notify_live_move()

            snapped_x, snapped_y = self.config.grid_to_board_pos(col, row)
            return QPointF(snapped_x, snapped_y)

        return super().itemChange(change, value)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        self._is_dragging = True
        self._drag_start_grid = (self.instance.grid_x, self.instance.grid_y)
        self.setZValue(30) # Lift above other components during interaction
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        self._is_dragging = False
        self.setZValue(15 if self.isSelected() else 10)
        super().mouseReleaseEvent(event)
        if (self.instance.grid_x, self.instance.grid_y) != self._drag_start_grid:
            self._drag_start_grid = (self.instance.grid_x, self.instance.grid_y)
            self._notify_undo_change()

    def hoverMoveEvent(self, event):
        # Update pin hover tooltip
        local_pos = event.pos()
        p = self.config.pitch_px
        pins = self.instance.get_pin_positions(self.comp_def)
        matched_pin = None
        matched_off_grid = None

        for pin_name, abs_col, abs_row, ptype in pins:
            px, py = self.config.grid_to_board_pos(abs_col, abs_row)
            item_pin_pos = self.mapFromScene(QPointF(px, py))
            dist = (item_pin_pos.x() - local_pos.x())**2 + (item_pin_pos.y() - local_pos.y())**2
            if dist < (p * 0.6)**2:
                matched_pin = (pin_name, abs_col, abs_row, ptype)
                break

        if not matched_pin:
            for pin_name, abs_col_f, abs_row_f, ptype in self.instance.get_off_grid_pin_positions(self.comp_def):
                px, py = self.config.grid_to_board_pos(abs_col_f, abs_row_f)
                item_pin_pos = self.mapFromScene(QPointF(px, py))
                dist = (item_pin_pos.x() - local_pos.x())**2 + (item_pin_pos.y() - local_pos.y())**2
                if dist < (p * 0.55)**2:
                    matched_off_grid = (pin_name, ptype)
                    break

        if matched_pin:
            name, c, r, ptype = matched_pin
            col_letter = col_index_to_name(c)
            self.setToolTip(f"{self.comp_def.name}: Pin {name} ({ptype})\nHole: {col_letter}{r + 1} (Col: {c}, Row: {r})")
        elif matched_off_grid:
            name, ptype = matched_off_grid
            self.setToolTip(f"{self.comp_def.name}: Pin {name} ({ptype})\nOff-grid (Jumper-only: solder a jumper wire to perfboard)")
        else:
            self.setToolTip(f"{self.comp_def.name} [{self.instance.label}]\nPos: ({self.instance.grid_x}, {self.instance.grid_y}) | Rot: {self.instance.rotation}°")

        super().hoverMoveEvent(event)
