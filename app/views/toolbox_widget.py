"""
Left Toolbox panel showing categorized electronic components with drag-and-drop and click-to-place.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QScrollArea, QFrame,
    QLabel, QPushButton, QGridLayout, QSizePolicy
)
from PyQt6.QtGui import (
    QPainter, QColor, QPixmap, QDrag, QFont, QCursor
)
from PyQt6.QtCore import Qt, QMimeData, QPoint, QRectF, pyqtSignal
from app.models.component_def import ComponentDef
from app.models.placed_component import PlacedComponent
from app.components.registry import REGISTRY

class ComponentCard(QFrame):
    clicked = pyqtSignal(str) # type_id

    def __init__(self, comp_def: ComponentDef, parent=None):
        super().__init__(parent)
        self.comp_def = comp_def
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet("""
            ComponentCard {
                background-color: #2b2d31;
                border: 1px solid #383a40;
                border-radius: 6px;
                padding: 4px;
            }
            ComponentCard:hover {
                background-color: #35373c;
                border: 1px solid #5865f2;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)

        # Generate thumbnail icon
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(48, 48)
        self.icon_label.setPixmap(self._render_thumbnail(48, 48))
        layout.addWidget(self.icon_label)

        # Text labels
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        info_layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel(comp_def.name)
        title.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        title.setStyleSheet("color: #f2f3f5;")
        info_layout.addWidget(title)

        desc = QLabel(f"{len(comp_def.pins)} pins • {comp_def.default_label}")
        desc.setFont(QFont("Arial", 8))
        desc.setStyleSheet("color: #949ba4;")
        info_layout.addWidget(desc)

        layout.addLayout(info_layout)
        layout.addStretch()

        self._drag_start_pos = QPoint()

    def _render_thumbnail(self, w: int, h: int) -> QPixmap:
        pix = QPixmap(w, h)
        pix.fill(QColor(24, 25, 28))

        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # Center and scale component automatically from its shape bounds
        temp_inst = PlacedComponent(
            type_id=self.comp_def.type_id,
            grid_x=0, grid_y=0,
            label=self.comp_def.default_label
        )

        pitch = 14.0
        try:
            bounds = self.comp_def.get_shape(temp_inst, pitch).boundingRect()
        except Exception:
            bounds = QRectF()

        if bounds.isEmpty() or bounds.width() <= 0 or bounds.height() <= 0:
            bounds = QRectF(-pitch, -pitch, pitch * 2.0, pitch * 2.0)

        pad = 8.0
        scale = min((w - pad) / bounds.width(), (h - pad) / bounds.height(), 1.1)
        scale = max(scale, 0.08)

        painter.translate(w / 2.0, h / 2.0)
        painter.scale(scale, scale)
        painter.translate(-bounds.center().x(), -bounds.center().y())

        try:
            self.comp_def.draw_top(painter, temp_inst, pitch)
        except Exception:
            pass
        painter.end()
        return pix

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            if (event.pos() - self._drag_start_pos).manhattanLength() > 5:
                # Initiate Drag & Drop
                drag = QDrag(self)
                mime = QMimeData()
                mime.setData("application/x-perfboard-component", self.comp_def.type_id.encode("utf-8"))
                drag.setMimeData(mime)
                drag.setPixmap(self.icon_label.pixmap())
                drag.setHotSpot(QPoint(24, 24))
                drag.exec(Qt.DropAction.CopyAction)
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Emit click to place
            self.clicked.emit(self.comp_def.type_id)
        super().mouseReleaseEvent(event)


class ToolboxWidget(QWidget):
    component_selected = pyqtSignal(str) # type_id to place

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(260)
        self.setMaximumWidth(340)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # Header Title
        title_lbl = QLabel("COMPONENTS TOOLBOX")
        title_lbl.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color: #dbdee1; letter-spacing: 0.5px;")
        main_layout.addWidget(title_lbl)

        # Search filter
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍 Search components...")
        self.search_box.textChanged.connect(self._filter_components)
        main_layout.addWidget(self.search_box)

        hint_lbl = QLabel("💡 Drag onto board or click to place. Press 'R' to rotate.")
        hint_lbl.setFont(QFont("Arial", 8))
        hint_lbl.setWordWrap(True)
        hint_lbl.setStyleSheet("color: #949ba4; padding-bottom: 4px;")
        main_layout.addWidget(hint_lbl)

        # Scroll Area for component list
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 4, 0)
        self.list_layout.setSpacing(10)

        self.cards: list[tuple[ComponentDef, ComponentCard, QLabel | None]] = []
        self._populate_components()

        self.scroll_area.setWidget(self.list_container)
        main_layout.addWidget(self.scroll_area)

    def _populate_components(self):
        categories = REGISTRY.get_categories()

        for cat in categories:
            comps = REGISTRY.get_by_category(cat)
            if not comps:
                continue

            # Category Header
            cat_header = QLabel(cat.upper())
            cat_header.setFont(QFont("Arial", 9, QFont.Weight.Bold))
            cat_header.setStyleSheet("""
                color: #5865f2;
                border-bottom: 1px solid #383a40;
                padding-top: 6px;
                padding-bottom: 3px;
                margin-top: 4px;
            """)
            self.list_layout.addWidget(cat_header)

            for comp in comps:
                card = ComponentCard(comp)
                card.clicked.connect(self.component_selected.emit)
                self.list_layout.addWidget(card)
                self.cards.append((comp, card, cat_header))

        self.list_layout.addStretch()

    def _filter_components(self, query: str):
        query = query.strip().lower()
        visible_in_cat: dict[str, int] = {}

        for comp, card, cat_header in self.cards:
            matches = (
                query in comp.name.lower() or
                query in comp.category.lower() or
                query in comp.default_label.lower() or
                any(query in tag.lower() for tag in comp.tags)
            )
            card.setVisible(matches)
            if matches:
                visible_in_cat[comp.category] = visible_in_cat.get(comp.category, 0) + 1

        # Hide category headers if no visible items
        for comp, card, cat_header in self.cards:
            if cat_header:
                cat_header.setVisible(visible_in_cat.get(comp.category, 0) > 0)
