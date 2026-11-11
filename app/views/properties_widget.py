"""
Right Properties panel for configuring selected component, jumper wire, or global perfboard properties.
Includes live Jumper color palette and solder tool information.
"""
import json
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QSpinBox,
    QAbstractSpinBox, QToolButton, QComboBox, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QFrame, QScrollArea, QGroupBox, QGridLayout,
    QApplication, QInputDialog, QMessageBox, QSplitter, QSizePolicy
)
from PyQt6.QtGui import QColor, QFont, QCursor
from PyQt6.QtCore import Qt, pyqtSignal, QSettings
from app.models.board import BoardConfig, col_index_to_name
from app.models.placed_component import PlacedComponent
from app.models.solder import SelectedSolderPath
from app.models.jumper import JumperWire, JUMPER_COLORS, DEFAULT_JUMPER_COLOR
from app.models.router import AutoConnectSettings, AutoConnectTarget, AutoConnectGroup
from app.views.component_item import ComponentItem
from app.views.jumper_item import JumperItem
from app.views.slideable_number_box import SlideableNumberBox

_SETTINGS_ORG = "PerfBoardMaker"
_SETTINGS_APP = "PerfBoardMaker"
_CUSTOM_PRESETS_KEY = "autoconnect/custom_presets"

# Tuple order: (cost_solder_move, cost_solder_turn, cost_jumper_start, cost_jumper_move, cost_jumper_turn, cost_jumper_cross)
BUILTIN_COST_PRESETS: dict[str, tuple[int, int, int, int, int, int]] = {
    "Balanced": (10, 15, 50, 2, 30, 100),
    "More jumper": (25, 35, 20, 2, 15, 60),
    "More solder": (5, 8, 120, 6, 50, 180),
}


class PlusMinusSpinBox(QSpinBox):
    """QSpinBox with '-' (left, decrease) and '+' (right, increase) buttons."""
    _BTN_WIDTH = 17

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.setMinimumWidth(68)
        self.setStyleSheet(
            "PlusMinusSpinBox { padding: 4px 38px 4px 6px; }"
        )

        btn_css = """
            QToolButton {
                background-color: #2b2d31;
                color: #e0e2e8;
                border: none;
                border-left: 1px solid #383a40;
                font-weight: bold;
                font-size: 13px;
                padding: 0px;
            }
            QToolButton:hover {
                background-color: #35373c;
                color: #ffffff;
            }
            QToolButton:pressed {
                background-color: #5865f2;
                color: #ffffff;
            }
            QToolButton:disabled {
                color: #5c5f66;
                background-color: #232428;
            }
        """

        self._btn_minus = QToolButton(self)
        self._btn_minus.setText("-")
        self._btn_minus.setToolTip("Decrease value")
        self._btn_minus.setAutoRepeat(True)
        self._btn_minus.setAutoRepeatDelay(300)
        self._btn_minus.setAutoRepeatInterval(60)
        self._btn_minus.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_minus.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_minus.setStyleSheet(btn_css)
        self._btn_minus.clicked.connect(self.stepDown)

        self._btn_plus = QToolButton(self)
        self._btn_plus.setText("+")
        self._btn_plus.setToolTip("Increase value")
        self._btn_plus.setAutoRepeat(True)
        self._btn_plus.setAutoRepeatDelay(300)
        self._btn_plus.setAutoRepeatInterval(60)
        self._btn_plus.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_plus.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_plus.setStyleSheet(btn_css + "QToolButton { border-top-right-radius: 3px; border-bottom-right-radius: 3px; }")
        self._btn_plus.clicked.connect(self.stepUp)

        self.valueChanged.connect(self._update_button_states)
        self._update_button_states()

    def setRange(self, minimum: int, maximum: int):
        super().setRange(minimum, maximum)
        self._update_button_states()

    def _update_button_states(self):
        self._btn_minus.setEnabled(self.value() > self.minimum())
        self._btn_plus.setEnabled(self.value() < self.maximum())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w = self.width()
        h = self.height()
        bw = self._BTN_WIDTH
        bh = max(12, h - 2)
        self._btn_minus.setGeometry(w - 2 * bw - 1, 1, bw, bh)
        self._btn_plus.setGeometry(w - bw - 1, 1, bw, bh)


class SwatchPickerButton(QPushButton):
    def __init__(self, color_hex: str, name: str, parent=None):
        super().__init__(parent)
        self.color_hex = color_hex
        self.color_name = name
        self.setFixedSize(26, 26)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip(f"{name} ({color_hex})")
        self.setCheckable(True)
        self._update_style(False)

    def _update_style(self, checked: bool):
        border = "2px solid #ffffff" if checked else "1px solid #4e5058"
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.color_hex};
                border: {border};
                border-radius: 13px;
            }}
            QPushButton:hover {{
                border: 2px solid #5865f2;
            }}
        """)

    def setChecked(self, checked: bool):
        super().setChecked(checked)
        self._update_style(checked)


class PropertiesWidget(QWidget):
    property_changed = pyqtSignal()
    board_changed = pyqtSignal()
    delete_requested = pyqtSignal()
    active_color_changed = pyqtSignal(str) # For Jumper mode active color
    connect_requested = pyqtSignal()       # Trigger autoconnect
    autoconnect_settings_changed = pyqtSignal(object) # Emit updated AutoConnectSettings
    group_remove_requested = pyqtSignal(int)          # Emit group_id to remove
    group_all_requested = pyqtSignal()               # Trigger Ctrl+G
    ungroup_requested = pyqtSignal()                 # Trigger Ctrl+Shift+G
    clear_groups_requested = pyqtSignal()
    optimize_board_requested = pyqtSignal()          # Re-extract shorted nets, clear traces/jumpers, and optimize

    def __init__(self, config: BoardConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.selected_item = None
        self.active_mode = "select"
        self.active_jumper_color = DEFAULT_JUMPER_COLOR

        # AutoConnect Settings, Presets, Targets & Groups
        self.autoconnect_settings = AutoConnectSettings()
        self.default_autoconnect_settings = AutoConnectSettings()
        self.custom_cost_presets: dict[str, tuple[int, int, int, int, int, int]] = self._load_custom_cost_presets()
        self.autoconnect_targets: list[AutoConnectTarget] = []
        self.autoconnect_groups: list[AutoConnectGroup] = []

        self.setMinimumWidth(280)
        self.setMaximumWidth(500)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(6)

        self.splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(6)
        self.splitter.setStyleSheet(
            "QSplitter::handle { background-color: #3f4249; border-radius: 2px; }"
            "QSplitter::handle:hover { background-color: #5865f2; }"
        )

        # Top panel: Tool / Mode properties (always visible)
        self.top_panel = QWidget(self.splitter)
        top_layout = QVBoxLayout(self.top_panel)
        top_layout.setContentsMargins(0, 0, 0, 4)
        top_layout.setSpacing(8)

        self.title_lbl = QLabel("PROPERTIES")
        self.title_lbl.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.title_lbl.setStyleSheet("color: #dbdee1; letter-spacing: 0.5px;")
        top_layout.addWidget(self.title_lbl)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self.container = QWidget()
        self.layout = QVBoxLayout(self.container)
        self.layout.setContentsMargins(0, 0, 4, 0)
        self.layout.setSpacing(12)

        self.scroll_area.setWidget(self.container)
        top_layout.addWidget(self.scroll_area)

        # Bottom panel: Selected object properties (hidden when nothing is selected)
        self.bottom_panel = QWidget(self.splitter)
        bot_layout = QVBoxLayout(self.bottom_panel)
        bot_layout.setContentsMargins(0, 4, 0, 0)
        bot_layout.setSpacing(8)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #3f4147; max-height: 1px;")
        bot_layout.addWidget(sep)

        self.obj_title_lbl = QLabel("SELECTED OBJECT")
        self.obj_title_lbl.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.obj_title_lbl.setStyleSheet("color: #7983f5; letter-spacing: 0.5px;")
        bot_layout.addWidget(self.obj_title_lbl)

        self.obj_scroll_area = QScrollArea()
        self.obj_scroll_area.setWidgetResizable(True)
        self.obj_scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self.obj_container = QWidget()
        self.obj_layout = QVBoxLayout(self.obj_container)
        self.obj_layout.setContentsMargins(0, 0, 4, 0)
        self.obj_layout.setSpacing(12)

        self.obj_scroll_area.setWidget(self.obj_container)
        bot_layout.addWidget(self.obj_scroll_area)

        self.splitter.addWidget(self.top_panel)
        self.splitter.addWidget(self.bottom_panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.bottom_panel.hide()

        main_layout.addWidget(self.splitter)

        self.refresh_view()

    def set_mode(self, mode: str):
        self.active_mode = mode
        self._refresh_tool_panel()

    def set_active_jumper_color(self, hex_color: str):
        self.active_jumper_color = hex_color
        if self.active_mode == "jumper":
            self._refresh_tool_panel()

    def set_selected_item(self, item):
        if self.selected_item is item:
            return
        self.selected_item = item
        self._refresh_object_panel()

    def set_autoconnect_targets(self, targets: list[AutoConnectTarget]):
        self.autoconnect_targets = list(targets)
        if self.active_mode == "autoconnect":
            if hasattr(self, "sel_targets_layout") and hasattr(self, "spin_s_move"):
                self._update_targets_list()
            else:
                self._refresh_tool_panel()

    def set_autoconnect_groups(self, groups: list[AutoConnectGroup]):
        self.autoconnect_groups = list(groups)
        if self.active_mode == "autoconnect":
            if hasattr(self, "sel_targets_layout") and hasattr(self, "spin_s_move"):
                self._update_targets_list()
            else:
                self._refresh_tool_panel()

    def refresh_view(self):
        self._refresh_tool_panel()
        self._refresh_object_panel()

    def _refresh_tool_panel(self):
        self._clear_tool_layout()
        if self.active_mode == "jumper":
            self.show_jumper_tool_settings()
        elif self.active_mode == "solder":
            self.show_solder_tool_settings()
        elif self.active_mode == "autoconnect":
            self.show_autoconnect_settings()
        else:
            self.show_board_properties()

    def _refresh_object_panel(self):
        self._clear_object_layout()
        if isinstance(self.selected_item, ComponentItem):
            self.show_component_properties(self.selected_item)
        elif isinstance(self.selected_item, JumperItem):
            self.show_jumper_properties(self.selected_item)
        elif isinstance(self.selected_item, SelectedSolderPath):
            self.show_solder_path_properties(self.selected_item)
        else:
            self.bottom_panel.hide()

    def _clear_qlayout(self, layout):
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
            elif child.layout():
                self._clear_qlayout(child.layout())

    def _clear_tool_layout(self):
        while QApplication.overrideCursor() is not None:
            QApplication.restoreOverrideCursor()
        if hasattr(self, "sel_targets_layout"):
            delattr(self, "sel_targets_layout")
        if hasattr(self, "sel_targets_grp"):
            delattr(self, "sel_targets_grp")
        self._clear_qlayout(self.layout)

    def _clear_object_layout(self):
        while QApplication.overrideCursor() is not None:
            QApplication.restoreOverrideCursor()
        for attr in ("solder_pins_table", "solder_pins_splitter"):
            if hasattr(self, attr):
                delattr(self, attr)
        self._clear_qlayout(self.obj_layout)

    # SOLDER PATH PROPERTIES (when a SolderTrace is selected)
    def show_solder_path_properties(self, sel: SelectedSolderPath):
        self._clear_object_layout()
        self.bottom_panel.show()
        self.obj_title_lbl.setText("SOLDER PATH")
        trace = sel.trace

        info_grp = QGroupBox(f"Solder Path #{trace.id}")
        info_grp.setStyleSheet("QGroupBox { font-weight: bold; color: #38bdf8; }")
        i_layout = QVBoxLayout(info_grp)
        i_layout.setSpacing(6)

        stats_lbl = QLabel(f"Holes: {len(trace.holes)} | Segments: {len(trace.segments)}")
        stats_lbl.setStyleSheet("color: #dbdee1; font-size: 11px; font-weight: 600;")
        i_layout.addWidget(stats_lbl)

        sorted_holes = sorted(trace.holes, key=lambda h: (h[1], h[0]))
        hole_names = ", ".join(f"{col_index_to_name(c)}{r + 1}" for c, r in sorted_holes)
        holes_lbl = QLabel(f"Path Holes: {hole_names}" if hole_names else "Path Holes: (empty)")
        holes_lbl.setWordWrap(True)
        holes_lbl.setStyleSheet("color: #949ba4; font-size: 11px;")
        i_layout.addWidget(holes_lbl)

        if sel.net_jumpers:
            net_lbl = QLabel(
                f"Conductive Net: {len(sel.net_traces)} trace(s), "
                f"{len(sel.net_jumpers)} jumper(s) ({len(sel.net_holes)} holes total)"
            )
            net_lbl.setWordWrap(True)
            net_lbl.setStyleSheet("color: #f0b232; font-size: 11px;")
            i_layout.addWidget(net_lbl)

        # Wrap info_grp in a compact scroll area so the splitter below can resize freely even with long hole lists
        info_scroll = QScrollArea()
        info_scroll.setWidgetResizable(True)
        info_scroll.setFrameShape(QFrame.Shape.NoFrame)
        info_scroll.setMinimumHeight(54)
        info_scroll.setWidget(info_grp)

        # Connected Component Pins Table (expandable & resizeable inside selected object panel)
        pins = sel.all_pins
        pins_grp = QGroupBox(f"Connected Pins ({len(pins)})")
        pins_grp.setStyleSheet("QGroupBox { font-weight: bold; color: #dbdee1; }")
        pins_grp.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        pins_grp.setMinimumHeight(90)
        pins_layout = QVBoxLayout(pins_grp)
        pins_layout.setContentsMargins(6, 10, 6, 6)

        if not pins:
            empty_lbl = QLabel("No component pins connected to this solder path.")
            empty_lbl.setWordWrap(True)
            empty_lbl.setStyleSheet("color: #949ba4; font-size: 11px;")
            pins_layout.addWidget(empty_lbl)
            pins_layout.addStretch()
        else:
            table = QTableWidget(len(pins), 4)
            table.setHorizontalHeaderLabels(["Component", "Pin", "Hole", "Link"])
            header = table.horizontalHeader()
            for col_idx in range(4):
                header.setSectionResizeMode(col_idx, QHeaderView.ResizeMode.Interactive)
            header.setStretchLastSection(True)
            table.verticalHeader().setVisible(False)
            table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            table.setMinimumHeight(70)

            for row_idx, pin in enumerate(pins):
                item_comp = QTableWidgetItem(pin.component_label)
                item_comp.setToolTip(f"{pin.component_name} ({pin.component_label})")

                item_pin = QTableWidgetItem(pin.pin_name)
                item_pin.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                hole_str = f"{col_index_to_name(pin.col)}{pin.row + 1}"
                item_hole = QTableWidgetItem(hole_str)
                item_hole.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item_hole.setToolTip(f"Col: {pin.col}, Row: {pin.row}")

                link_text = "Via Jumper" if pin.via_jumper else f"Direct ({pin.pin_type})"
                item_link = QTableWidgetItem(link_text)
                item_link.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if pin.via_jumper:
                    item_link.setForeground(QApplication.palette().link())
                    item_link.setToolTip(f"Pin type: {pin.pin_type} (connected via jumper wire)")

                table.setItem(row_idx, 0, item_comp)
                table.setItem(row_idx, 1, item_pin)
                table.setItem(row_idx, 2, item_hole)
                table.setItem(row_idx, 3, item_link)

            table.resizeColumnsToContents()
            table.setColumnWidth(0, max(table.columnWidth(0) + 8, 72))
            self.solder_pins_table = table
            pins_layout.addWidget(table)

        solder_splitter = QSplitter(Qt.Orientation.Vertical)
        solder_splitter.setChildrenCollapsible(False)
        solder_splitter.setHandleWidth(6)
        solder_splitter.setStyleSheet(
            "QSplitter::handle { background-color: #3f4249; border-radius: 2px; }"
            "QSplitter::handle:hover { background-color: #5865f2; }"
        )
        solder_splitter.addWidget(info_scroll)
        solder_splitter.addWidget(pins_grp)
        solder_splitter.setStretchFactor(0, 0)
        solder_splitter.setStretchFactor(1, 1)
        solder_splitter.setSizes([95, 220])
        self.solder_pins_splitter = solder_splitter

        self.obj_layout.addWidget(solder_splitter, 1)

        del_btn = QPushButton("🗑️ Delete Solder Path (Del)")
        del_btn.setObjectName("danger_btn")
        del_btn.clicked.connect(self.delete_requested.emit)
        self.obj_layout.addWidget(del_btn)

    # JUMPER PROPERTIES (when a JumperItem is selected)
    def show_jumper_properties(self, item: JumperItem):
        self._clear_object_layout()
        self.bottom_panel.show()
        self.obj_title_lbl.setText("JUMPER WIRE")
        j = item.jumper

        grp = QGroupBox("Wire Configuration")
        grp.setStyleSheet("QGroupBox { font-weight: bold; color: #5865f2; }")
        g_layout = QVBoxLayout(grp)
        g_layout.setSpacing(10)

        # Color Selector Swatches
        lbl_col = QLabel("Wire Color:")
        lbl_col.setStyleSheet("color: #dbdee1; font-weight: 600;")
        g_layout.addWidget(lbl_col)

        swatch_grid = QGridLayout()
        swatch_grid.setSpacing(6)
        self.jumper_swatches: list[SwatchPickerButton] = []

        for i, (col_hex, name) in enumerate(JUMPER_COLORS):
            row = i // 4
            col = i % 4
            btn = SwatchPickerButton(col_hex, name)
            if col_hex.lower() == j.color.lower():
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, h=col_hex: self._on_jumper_color_selected(item, h))
            swatch_grid.addWidget(btn, row, col)
            self.jumper_swatches.append(btn)

        g_layout.addLayout(swatch_grid)

        # Wire side selector
        side_row = QHBoxLayout()
        side_row.addWidget(QLabel("Placement Side:"))
        combo_side = QComboBox()
        combo_side.addItems(["Top (Components)", "Bottom (Solder)"])
        combo_side.setCurrentIndex(0 if j.side == "top" else 1)
        combo_side.currentIndexChanged.connect(lambda idx: self._on_jumper_side_changed(item, idx))
        side_row.addWidget(combo_side)
        g_layout.addLayout(side_row)

        self.obj_layout.addWidget(grp)

        # Location and Metrics
        info_grp = QGroupBox("Connections & Length")
        info_grp.setStyleSheet("QGroupBox { font-weight: bold; color: #dbdee1; }")
        i_layout = QVBoxLayout(info_grp)
        i_layout.setSpacing(6)

        def _fmt_end(col, row, pin_ref):
            if pin_ref is not None:
                return f"Pin {pin_ref[2]} [Jumper-Only]"
            c_idx = int(round(col))
            r_idx = int(round(row))
            return f"{col_index_to_name(c_idx)}{r_idx + 1} (Col: {c_idx}, Row: {r_idx})"

        start_str = f"From: {_fmt_end(j.start_col, j.start_row, j.start_pin)}"
        end_str = f"To:   {_fmt_end(j.end_col, j.end_row, j.end_pin)}"
        len_str = f"Length: {j.length_holes:.2f} holes ({j.length_mm:.1f} mm)"

        for t in (start_str, end_str, len_str):
            lbl = QLabel(t)
            lbl.setStyleSheet("color: #949ba4; font-size: 11px;")
            i_layout.addWidget(lbl)

        if j.bends:
            bends_str = f"Bend Points ({len(j.bends)}): " + ", ".join([f"{col_index_to_name(c)}{r + 1}" for c, r in j.bends])
            lbl_bends = QLabel(bends_str)
            lbl_bends.setStyleSheet("color: #fcc419; font-size: 11px;")
            lbl_bends.setWordWrap(True)
            i_layout.addWidget(lbl_bends)

        self.obj_layout.addWidget(info_grp)

        # Delete button
        del_btn = QPushButton("🗑️ Delete Jumper (Del)")
        del_btn.setObjectName("danger_btn")
        del_btn.clicked.connect(self.delete_requested.emit)
        self.obj_layout.addWidget(del_btn)

        self.obj_layout.addStretch()

    def _on_jumper_color_selected(self, item: JumperItem, hex_color: str):
        item.jumper.color = hex_color
        self.active_jumper_color = hex_color
        for btn in self.jumper_swatches:
            btn.setChecked(btn.color_hex.lower() == hex_color.lower())
        item.update()
        self.property_changed.emit()
        self.active_color_changed.emit(hex_color)

    def _on_jumper_side_changed(self, item: JumperItem, idx: int):
        item.jumper.side = "top" if idx == 0 else "bottom"
        item.update()
        self.property_changed.emit()

    # JUMPER TOOL SETTINGS (mode == "jumper", no item selected)
    def show_jumper_tool_settings(self):
        self.title_lbl.setText("JUMPER WIRE TOOL (3)")

        grp = QGroupBox("Default Wire Color")
        grp.setStyleSheet("QGroupBox { font-weight: bold; color: #5865f2; }")
        g_layout = QVBoxLayout(grp)
        g_layout.setSpacing(10)

        lbl = QLabel("Click a color to select wire color:")
        lbl.setStyleSheet("color: #949ba4; font-size: 11px;")
        g_layout.addWidget(lbl)

        swatch_grid = QGridLayout()
        swatch_grid.setSpacing(6)
        for i, (col_hex, name) in enumerate(JUMPER_COLORS):
            row = i // 4
            col = i % 4
            btn = SwatchPickerButton(col_hex, name)
            if col_hex.lower() == self.active_jumper_color.lower():
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, h=col_hex: self._on_default_color_picked(h))
            swatch_grid.addWidget(btn, row, col)

        g_layout.addLayout(swatch_grid)
        self.layout.addWidget(grp)

        guide_grp = QGroupBox("How to Draw & Bend Jumpers")
        guide_grp.setStyleSheet("QGroupBox { font-weight: bold; color: #dbdee1; }")
        guide_layout = QVBoxLayout(guide_grp)
        tips = (
            "• Drag between holes to draw a straight jumper wire.\n"
            "• Hold Shift while drawing to lock to horizontal / vertical.\n"
            "• Hold Shift and CLICK on a jumper wire to insert a BEND POINT!\n"
            "• Multiple bends can be created and dragged around.\n"
            "• Drag endpoint handles to move wire ends to new holes.\n"
            "• Bend waypoints route over holes without making an electrical connection."
        )
        tips_lbl = QLabel(tips)
        tips_lbl.setStyleSheet("color: #949ba4; font-size: 11px; line-height: 1.4;")
        tips_lbl.setWordWrap(True)
        guide_layout.addWidget(tips_lbl)
        self.layout.addWidget(guide_grp)

        self.layout.addStretch()

    def _on_default_color_picked(self, hex_color: str):
        self.active_jumper_color = hex_color
        self.active_color_changed.emit(hex_color)
        self._refresh_tool_panel()

    # SOLDER TOOL SETTINGS (mode == "solder", no item selected)
    def show_solder_tool_settings(self):
        self.title_lbl.setText("SOLDER BRIDGE TOOL (2)")

        grp = QGroupBox("Solder Bridges (Back Side)")
        grp.setStyleSheet("QGroupBox { font-weight: bold; color: #5865f2; }")
        g_layout = QVBoxLayout(grp)
        g_layout.setSpacing(10)

        info = (
            "⚡ Solder Mode is ACTIVE.\n\n"
            "• Drag between holes on the back side to form solder bridges.\n"
            "• Hold Shift while drawing for straight horizontal or vertical lines.\n"
            "• Parallel or perpendicular lines that do not start from the same hole will NOT connect.\n"
            "• In front view, solder lines are rendered as a translucent ghost."
        )
        lbl = QLabel(info)
        lbl.setStyleSheet("color: #dbdee1; font-size: 11px; line-height: 1.4;")
        lbl.setWordWrap(True)
        g_layout.addWidget(lbl)

        flip_btn = QPushButton("🔄 Flip to Bottom Side (F)")
        flip_btn.clicked.connect(self._flip_board_request)
        g_layout.addWidget(flip_btn)

        self.layout.addWidget(grp)
        self.layout.addStretch()

    # Board Properties (when no item selected in select mode)
    def show_board_properties(self):
        self.title_lbl.setText("PERFBOARD SETTINGS")

        grp = QGroupBox("Board Configuration")
        grp.setStyleSheet("QGroupBox { font-weight: bold; color: #dbdee1; }")
        grp_layout = QVBoxLayout(grp)
        grp_layout.setSpacing(8)

        # Columns (Width)
        row_cols = QHBoxLayout()
        row_cols.addWidget(QLabel("Width (Holes / Cols):"))
        self.spin_cols = PlusMinusSpinBox()
        self.spin_cols.setRange(10, 120)
        self.spin_cols.setValue(self.config.cols)
        self.spin_cols.valueChanged.connect(self._on_board_dims_changed)
        row_cols.addWidget(self.spin_cols)
        grp_layout.addLayout(row_cols)

        # Rows (Height)
        row_rows = QHBoxLayout()
        row_rows.addWidget(QLabel("Height (Holes / Rows):"))
        self.spin_rows = PlusMinusSpinBox()
        self.spin_rows.setRange(8, 100)
        self.spin_rows.setValue(self.config.rows)
        self.spin_rows.valueChanged.connect(self._on_board_dims_changed)
        row_rows.addWidget(self.spin_rows)
        grp_layout.addLayout(row_rows)

        # Substrate Style
        row_style = QHBoxLayout()
        row_style.addWidget(QLabel("Board Substrate:"))
        self.combo_style = QComboBox()
        self.combo_style.addItems(["Green FR4", "Phenolic Brown", "Blue FR4", "Matte Black"])
        style_map = {"green": 0, "brown": 1, "blue": 2, "black": 3}
        self.combo_style.setCurrentIndex(style_map.get(self.config.style, 0))
        self.combo_style.currentIndexChanged.connect(self._on_board_style_changed)
        row_style.addWidget(self.combo_style)
        grp_layout.addLayout(row_style)

        # Pitch info
        info_lbl = QLabel(f"Grid Pitch: 2.54 mm (100 mil / 0.1\")\nTotal Holes: {self.config.cols * self.config.rows}")
        info_lbl.setStyleSheet("color: #949ba4; font-size: 11px;")
        grp_layout.addWidget(info_lbl)

        self.layout.addWidget(grp)

        # View Side Info Card
        view_grp = QGroupBox("Active View Side")
        view_grp.setStyleSheet("QGroupBox { font-weight: bold; color: #dbdee1; }")
        view_layout = QVBoxLayout(view_grp)

        curr_side = self.config.view_side.upper()
        side_desc = "TOP VIEW (Component Side)\nComponents are placed on top." if self.config.view_side == "top" else "BOTTOM VIEW (Solder Side)\nMirrored view showing solder pads & joints."
        side_lbl = QLabel(f"Current: {curr_side}\n\n{side_desc}")
        side_lbl.setStyleSheet("color: #5865f2; font-weight: bold;")
        side_lbl.setWordWrap(True)
        view_layout.addWidget(side_lbl)

        flip_btn = QPushButton("🔄 Flip Board (Hotkey: F)")
        flip_btn.clicked.connect(self._flip_board_request)
        view_layout.addWidget(flip_btn)

        self.layout.addWidget(view_grp)
        self.layout.addStretch()

    def _on_board_dims_changed(self):
        self.config.cols = self.spin_cols.value()
        self.config.rows = self.spin_rows.value()
        self.board_changed.emit()

    def _on_board_style_changed(self, idx: int):
        styles = ["green", "brown", "blue", "black"]
        self.config.style = styles[idx]
        self.board_changed.emit()

    def _flip_board_request(self):
        new_side = "bottom" if self.config.view_side == "top" else "top"
        self.config.view_side = new_side
        self.board_changed.emit()
        self._refresh_tool_panel()

    # Component Properties
    def show_component_properties(self, item: ComponentItem):
        self._clear_object_layout()
        self.bottom_panel.show()
        self.obj_title_lbl.setText("COMPONENT SETTINGS")
        inst = item.instance
        comp_def = item.comp_def

        # 1. Info Header
        info_grp = QGroupBox(comp_def.name)
        info_grp.setStyleSheet("QGroupBox { font-weight: bold; color: #5865f2; }")
        info_layout = QVBoxLayout(info_grp)
        desc_lbl = QLabel(comp_def.description)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("color: #949ba4; font-size: 11px;")
        info_layout.addWidget(desc_lbl)
        self.obj_layout.addWidget(info_grp)

        # 2. Main Parameters
        param_grp = QGroupBox("Parameters")
        param_grp.setStyleSheet("QGroupBox { font-weight: bold; color: #dbdee1; }")
        p_layout = QVBoxLayout(param_grp)
        p_layout.setSpacing(8)

        # Renameable Label / Part Number
        row_lbl = QHBoxLayout()
        row_lbl.addWidget(QLabel("Label / Value:"))
        self.edit_label = QLineEdit(inst.label)
        self.edit_label.setPlaceholderText("Enter label...")
        self.edit_label.textChanged.connect(self._on_label_changed)
        row_lbl.addWidget(self.edit_label)
        p_layout.addLayout(row_lbl)

        # Custom component properties
        for prop in comp_def.properties:
            if prop.id == "label":
                continue

            row_prop = QHBoxLayout()
            row_prop.addWidget(QLabel(f"{prop.label}:"))

            curr_val = inst.custom_props.get(prop.id, prop.default)
            if prop.type == "choice":
                combo = QComboBox()
                combo.addItems(prop.choices)
                if str(curr_val) in prop.choices:
                    combo.setCurrentText(str(curr_val))
                combo.currentTextChanged.connect(lambda val, pid=prop.id: self._on_custom_prop_changed(pid, val))
                row_prop.addWidget(combo)
            elif prop.type == "int":
                spin = PlusMinusSpinBox()
                if len(prop.choices) >= 2:
                    spin.setRange(int(prop.choices[0]), int(prop.choices[1]))
                else:
                    spin.setRange(1, 40)
                try:
                    spin.setValue(int(curr_val))
                except (TypeError, ValueError):
                    spin.setValue(int(prop.default))
                spin.setKeyboardTracking(False)
                spin.valueChanged.connect(lambda val, pid=prop.id: self._on_custom_prop_changed(pid, val))
                row_prop.addWidget(spin)
            elif prop.type == "str":
                edit = QLineEdit(str(curr_val))
                edit.textChanged.connect(lambda val, pid=prop.id: self._on_custom_prop_changed(pid, val))
                row_prop.addWidget(edit)

            p_layout.addLayout(row_prop)

        # Position (Col, Row)
        pos_layout = QHBoxLayout()
        pos_layout.addWidget(QLabel("Hole Position:"))

        self.spin_x = PlusMinusSpinBox()
        self.spin_x.setRange(0, self.config.cols - 1)
        self.spin_x.setValue(inst.grid_x)
        self.spin_x.valueChanged.connect(self._on_pos_changed)
        pos_layout.addWidget(QLabel("Col:"))
        pos_layout.addWidget(self.spin_x)

        self.spin_y = PlusMinusSpinBox()
        self.spin_y.setRange(0, self.config.rows - 1)
        self.spin_y.setValue(inst.grid_y)
        self.spin_y.valueChanged.connect(self._on_pos_changed)
        pos_layout.addWidget(QLabel("Row:"))
        pos_layout.addWidget(self.spin_y)
        p_layout.addLayout(pos_layout)

        # Rotation
        rot_layout = QHBoxLayout()
        rot_layout.addWidget(QLabel("Rotation:"))
        self.combo_rot = QComboBox()
        self.combo_rot.addItems(["0°", "90° CW", "180°", "270° CW"])
        rot_idx = (inst.rotation // 90) % 4
        self.combo_rot.setCurrentIndex(rot_idx)
        self.combo_rot.currentIndexChanged.connect(self._on_rotation_changed)
        rot_layout.addWidget(self.combo_rot)

        btn_rot = QPushButton("Rotate 90° (R)")
        btn_rot.clicked.connect(self._rotate_cw_clicked)
        rot_layout.addWidget(btn_rot)
        p_layout.addLayout(rot_layout)

        self.obj_layout.addWidget(param_grp)

        # 3. Pins Table
        pins_grp = QGroupBox("Pin Footprint & Perfboard Holes")
        pins_grp.setStyleSheet("QGroupBox { font-weight: bold; color: #dbdee1; }")
        pins_layout = QVBoxLayout(pins_grp)

        pins = inst.get_pin_positions(comp_def)
        off_pins = inst.get_off_grid_pin_positions(comp_def)
        total_rows = len(pins) + len(off_pins)
        table = QTableWidget(total_rows, 3)
        table.setHorizontalHeaderLabels(["Pin", "Hole", "Type"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().setVisible(False)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setMaximumHeight(min(220, total_rows * 28 + 32))

        for row, (pname, c, r, ptype) in enumerate(pins):
            c_name = col_index_to_name(c)
            hole_str = f"{c_name}{r + 1} ({c}, {r})" if self.config.is_valid_hole(c, r) else "OUT OF BOUNDS"

            item_name = QTableWidgetItem(pname)
            item_hole = QTableWidgetItem(hole_str)
            item_type = QTableWidgetItem(ptype)

            if not self.config.is_valid_hole(c, r):
                item_hole.setForeground(Qt.GlobalColor.red)

            table.setItem(row, 0, item_name)
            table.setItem(row, 1, item_hole)
            table.setItem(row, 2, item_type)

        for idx, (pname, _cf, _rf, ptype) in enumerate(off_pins):
            row = len(pins) + idx
            item_name = QTableWidgetItem(pname)
            item_hole = QTableWidgetItem("Jumper Only (Off-Grid)")
            item_hole.setForeground(QColor("#fd7e14"))
            item_type = QTableWidgetItem(ptype)

            table.setItem(row, 0, item_name)
            table.setItem(row, 1, item_hole)
            table.setItem(row, 2, item_type)

        pins_layout.addWidget(table)
        self.obj_layout.addWidget(pins_grp)

        # 4. Actions
        del_btn = QPushButton("🗑️ Delete Component (Del)")
        del_btn.setObjectName("danger_btn")
        del_btn.clicked.connect(self.delete_requested.emit)
        self.obj_layout.addWidget(del_btn)

        self.obj_layout.addStretch()

    def _on_label_changed(self, text: str):
        if self.selected_item and isinstance(self.selected_item, ComponentItem):
            self.selected_item.instance.label = text
            self.selected_item.update()
            self.property_changed.emit()

    def _on_custom_prop_changed(self, prop_id: str, value):
        if self.selected_item and isinstance(self.selected_item, ComponentItem):
            inst = self.selected_item.instance
            cdef = self.selected_item.comp_def
            old_pins = [(p.name, p.grid_x, p.grid_y, p.pin_type) for p in cdef.get_pins_for_instance(inst)]
            inst.custom_props[prop_id] = value
            new_pins = [(p.name, p.grid_x, p.grid_y, p.pin_type) for p in cdef.get_pins_for_instance(inst)]
            self.selected_item.refresh_geometry()
            self.property_changed.emit()
            if new_pins != old_pins:
                self.refresh_view()

    def _on_pos_changed(self):
        if self.selected_item and isinstance(self.selected_item, ComponentItem):
            self.selected_item.instance.grid_x = self.spin_x.value()
            self.selected_item.instance.grid_y = self.spin_y.value()
            self.selected_item.update_position_from_grid()
            self.selected_item.refresh_geometry()
            self.selected_item._notify_live_move()
            self.property_changed.emit()

    def _on_rotation_changed(self, idx: int):
        if self.selected_item and isinstance(self.selected_item, ComponentItem):
            self.selected_item.set_rotation(idx * 90)
            self.property_changed.emit()

    def _rotate_cw_clicked(self):
        if self.selected_item and isinstance(self.selected_item, ComponentItem):
            self.selected_item.rotate_cw()
            idx = (self.selected_item.instance.rotation // 90) % 4
            self.combo_rot.blockSignals(True)
            self.combo_rot.setCurrentIndex(idx)
            self.combo_rot.blockSignals(False)
            self.property_changed.emit()

    # AUTOCONNECT SETTINGS PANEL
    def show_autoconnect_settings(self):
        self.title_lbl.setText("AUTOCONNECT ROUTER (4)")

        # 1. Guide Card
        guide_grp = QGroupBox("How to Use AutoConnect")
        guide_grp.setStyleSheet("QGroupBox { font-weight: bold; color: #00e6ff; }")
        g_layout = QVBoxLayout(guide_grp)
        g_layout.setSpacing(6)
        tips = (
            "• Click pins, solder traces, or jumper ends to select.\n"
            "• Hold Shift while clicking for multiple selection.\n"
            "• Press Ctrl+G to group/merge selected conductors.\n"
            "• Press Ctrl+Shift+G to remove selected pins from group.\n"
            "• Press Enter (or click Connect below) to auto-route all groups.\n"
            "• All groups are routed simultaneously without intersections!"
        )
        tips_lbl = QLabel(tips)
        tips_lbl.setStyleSheet("color: #949ba4; font-size: 11px; line-height: 1.4;")
        tips_lbl.setWordWrap(True)
        g_layout.addWidget(tips_lbl)
        self.layout.addWidget(guide_grp)

        # 2. Selected Conductors Card
        sel_count = len(self.autoconnect_targets)
        self.sel_targets_grp = QGroupBox(f"Selected Conductors ({sel_count})")
        self.sel_targets_grp.setStyleSheet("QGroupBox { font-weight: bold; color: #dbdee1; }")
        self.sel_targets_layout = QVBoxLayout(self.sel_targets_grp)
        self.sel_targets_layout.setSpacing(6)
        self._populate_targets_layout()
        self.layout.addWidget(self.sel_targets_grp)

        # Optimize Board Button (below Selected Conductors, above Routing Cost Weights)
        self.btn_optimize_board = QPushButton("⚡ Optimize Board")
        self.btn_optimize_board.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_optimize_board.setToolTip(
            "Checks electrical continuity of all component pins, groups shorted pins together,\n"
            "clears all existing solder traces & jumpers, and re-routes the board optimally."
        )
        self.btn_optimize_board.setStyleSheet("""
            QPushButton {
                background-color: #2b2d31;
                color: #f0b232;
                font-weight: bold;
                padding: 8px;
                border: 1px solid #f0b232;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #3a3526;
                border: 1px solid #ffd166;
                color: #ffd166;
            }
            QPushButton:pressed {
                background-color: #4a4228;
            }
        """)
        self.btn_optimize_board.clicked.connect(self.optimize_board_requested.emit)
        self.layout.addWidget(self.btn_optimize_board)

        # 3. Routing Cost Weights
        cost_grp = QGroupBox("Routing Cost Weights")
        cost_grp.setStyleSheet("QGroupBox { font-weight: bold; color: #dbdee1; }")
        c_layout = QVBoxLayout(cost_grp)
        c_layout.setSpacing(8)

        explain_lbl = QLabel("Increasing cost weight values will result in less usage of that element.")
        explain_lbl.setStyleSheet("color: #949ba4; font-size: 11px; font-style: italic;")
        explain_lbl.setWordWrap(True)
        c_layout.addWidget(explain_lbl)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset:"))
        self.combo_cost_preset = QComboBox()
        self.combo_cost_preset.currentTextChanged.connect(self._on_cost_preset_selected)
        preset_row.addWidget(self.combo_cost_preset, 1)
        c_layout.addLayout(preset_row)

        # Cost_Solder_Move
        row1 = QHBoxLayout()
        lbl1 = QLabel("Solder Move:")
        lbl1.setToolTip("Moving one hole over with solder (Default: 10)\nDrag left/right to adjust or click to type")
        row1.addWidget(lbl1)
        self.spin_s_move = SlideableNumberBox(
            value=self.autoconnect_settings.cost_solder_move, min_val=1, max_val=500
        )
        self.spin_s_move.valueChanged.connect(self._on_cost_changed)
        row1.addWidget(self.spin_s_move)
        c_layout.addLayout(row1)

        # Cost_Solder_Turn
        row2 = QHBoxLayout()
        lbl2 = QLabel("Solder Turn:")
        lbl2.setToolTip("Changing direction with solder (Default: 15)\nDrag left/right to adjust or click to type")
        row2.addWidget(lbl2)
        self.spin_s_turn = SlideableNumberBox(
            value=self.autoconnect_settings.cost_solder_turn, min_val=0, max_val=500
        )
        self.spin_s_turn.valueChanged.connect(self._on_cost_changed)
        row2.addWidget(self.spin_s_turn)
        c_layout.addLayout(row2)

        # Cost_Jumper_Start
        row3 = QHBoxLayout()
        lbl3 = QLabel("Jumper Start:")
        lbl3.setToolTip("Placing a jumper requires stripping wire and soldering two points (Default: 50)\nDrag left/right to adjust or click to type")
        row3.addWidget(lbl3)
        self.spin_j_start = SlideableNumberBox(
            value=self.autoconnect_settings.cost_jumper_start, min_val=0, max_val=1000
        )
        self.spin_j_start.valueChanged.connect(self._on_cost_changed)
        row3.addWidget(self.spin_j_start)
        c_layout.addLayout(row3)

        # Cost_Jumper_Move
        row4 = QHBoxLayout()
        lbl4 = QLabel("Jumper Move:")
        lbl4.setToolTip("Extending a jumper wire per hole (Default: 2)\nDrag left/right to adjust or click to type")
        row4.addWidget(lbl4)
        self.spin_j_move = SlideableNumberBox(
            value=self.autoconnect_settings.cost_jumper_move, min_val=1, max_val=500
        )
        self.spin_j_move.valueChanged.connect(self._on_cost_changed)
        row4.addWidget(self.spin_j_move)
        c_layout.addLayout(row4)

        # Cost_Jumper_Turn
        row5 = QHBoxLayout()
        lbl5 = QLabel("Jumper Turn (90°):")
        lbl5.setToolTip("Bending a jumper wire 90 degrees (Default: 30)\nDrag left/right to adjust or click to type")
        row5.addWidget(lbl5)
        self.spin_j_turn = SlideableNumberBox(
            value=self.autoconnect_settings.cost_jumper_turn, min_val=0, max_val=500
        )
        self.spin_j_turn.valueChanged.connect(self._on_cost_changed)
        row5.addWidget(self.spin_j_turn)
        c_layout.addLayout(row5)

        # Cost_Jumper_Cross
        row6 = QHBoxLayout()
        lbl6 = QLabel("Jumper Cross:")
        lbl6.setToolTip("Penalty when jumper wires cross over each other (Default: 100)\nDrag left/right to adjust or click to type")
        row6.addWidget(lbl6)
        self.spin_j_cross = SlideableNumberBox(
            value=self.autoconnect_settings.cost_jumper_cross, min_val=0, max_val=1000
        )
        self.spin_j_cross.valueChanged.connect(self._on_cost_changed)
        row6.addWidget(self.spin_j_cross)
        c_layout.addLayout(row6)

        self._populate_cost_presets_combo()

        # Action Buttons under cost parameters
        btn_layout = QHBoxLayout()
        self.btn_add_preset = QPushButton("Add Preset")
        self.btn_add_preset.setToolTip("Save current cost weight values as a reusable preset")
        self.btn_add_preset.clicked.connect(self._on_add_preset_clicked)
        btn_layout.addWidget(self.btn_add_preset)

        self.btn_reset_default = QPushButton("Reset Defaults")
        self.btn_reset_default.setToolTip("Reset weights to Balanced defaults (10, 15, 50, 2, 30, 100)")
        self.btn_reset_default.clicked.connect(self._on_reset_default_clicked)
        btn_layout.addWidget(self.btn_reset_default)
        c_layout.addLayout(btn_layout)

        self.layout.addWidget(cost_grp)
        self.layout.addStretch()

    @staticmethod
    def _load_custom_cost_presets() -> dict[str, tuple[int, int, int, int, int, int]]:
        settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        raw = settings.value(_CUSTOM_PRESETS_KEY, "")
        if not raw:
            return {}
        try:
            data = json.loads(str(raw))
            result: dict[str, tuple[int, int, int, int, int, int]] = {}
            if isinstance(data, dict):
                for name, vals in data.items():
                    if isinstance(name, str) and isinstance(vals, (list, tuple)) and len(vals) == 6:
                        result[name] = tuple(int(v) for v in vals)  # type: ignore[assignment]
            return result
        except (ValueError, TypeError):
            return {}

    def _save_custom_cost_presets(self) -> None:
        settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        serializable = {k: list(v) for k, v in self.custom_cost_presets.items()}
        settings.setValue(_CUSTOM_PRESETS_KEY, json.dumps(serializable))

    def _get_all_cost_presets(self) -> dict[str, tuple[int, int, int, int, int, int]]:
        merged = dict(BUILTIN_COST_PRESETS)
        merged.update(self.custom_cost_presets)
        return merged

    def _current_cost_tuple(self) -> tuple[int, int, int, int, int, int]:
        s = self.autoconnect_settings
        return (
            int(s.cost_solder_move),
            int(s.cost_solder_turn),
            int(s.cost_jumper_start),
            int(s.cost_jumper_move),
            int(s.cost_jumper_turn),
            int(s.cost_jumper_cross),
        )

    def _find_matching_preset_name(self) -> str:
        curr = self._current_cost_tuple()
        for name, vals in self._get_all_cost_presets().items():
            if vals == curr:
                return name
        return "Custom"

    def _populate_cost_presets_combo(self):
        if not hasattr(self, "combo_cost_preset"):
            return
        try:
            self.combo_cost_preset.blockSignals(True)
            self.combo_cost_preset.clear()
            for name in self._get_all_cost_presets():
                self.combo_cost_preset.addItem(name)
            self.combo_cost_preset.addItem("Custom")
            self.combo_cost_preset.setCurrentText(self._find_matching_preset_name())
            self.combo_cost_preset.blockSignals(False)
        except RuntimeError:
            pass

    def _sync_cost_preset_combo(self):
        if not hasattr(self, "combo_cost_preset"):
            return
        try:
            match = self._find_matching_preset_name()
            self.combo_cost_preset.blockSignals(True)
            self.combo_cost_preset.setCurrentText(match)
            self.combo_cost_preset.blockSignals(False)
        except RuntimeError:
            pass

    def _apply_cost_tuple(self, vals: tuple[int, int, int, int, int, int]):
        self.autoconnect_settings.cost_solder_move = vals[0]
        self.autoconnect_settings.cost_solder_turn = vals[1]
        self.autoconnect_settings.cost_jumper_start = vals[2]
        self.autoconnect_settings.cost_jumper_move = vals[3]
        self.autoconnect_settings.cost_jumper_turn = vals[4]
        self.autoconnect_settings.cost_jumper_cross = vals[5]

        if hasattr(self, "spin_s_move"):
            spins = (
                self.spin_s_move,
                self.spin_s_turn,
                self.spin_j_start,
                self.spin_j_move,
                self.spin_j_turn,
                self.spin_j_cross,
            )
            for sp, val in zip(spins, vals):
                sp.blockSignals(True)
                sp.setValue(val)
                sp.blockSignals(False)

        self._sync_cost_preset_combo()
        self.autoconnect_settings_changed.emit(self.autoconnect_settings)

    def _on_cost_preset_selected(self, preset_name: str):
        all_presets = self._get_all_cost_presets()
        if preset_name in all_presets:
            self._apply_cost_tuple(all_presets[preset_name])

    def _on_cost_changed(self):
        if hasattr(self, "spin_s_move"):
            self.autoconnect_settings.cost_solder_move = self.spin_s_move.value()
            self.autoconnect_settings.cost_solder_turn = self.spin_s_turn.value()
            self.autoconnect_settings.cost_jumper_start = self.spin_j_start.value()
            self.autoconnect_settings.cost_jumper_move = self.spin_j_move.value()
            self.autoconnect_settings.cost_jumper_turn = self.spin_j_turn.value()
            self.autoconnect_settings.cost_jumper_cross = self.spin_j_cross.value()
            self._sync_cost_preset_combo()
            self.autoconnect_settings_changed.emit(self.autoconnect_settings)

    def _on_add_preset_clicked(self):
        self._on_cost_changed()
        name, ok = QInputDialog.getText(self, "Add Routing Preset", "Preset name:")
        if not ok:
            return
        clean = name.strip()
        if not clean:
            return
        reserved = {k.lower() for k in BUILTIN_COST_PRESETS} | {"custom"}
        if clean.lower() in reserved:
            QMessageBox.warning(
                self,
                "Reserved Preset Name",
                f"'{clean}' is a built-in preset name. Please choose another name.",
            )
            return
        self.custom_cost_presets[clean] = self._current_cost_tuple()
        self._save_custom_cost_presets()
        self._populate_cost_presets_combo()

    def _on_reset_default_clicked(self):
        self._apply_cost_tuple(BUILTIN_COST_PRESETS["Balanced"])

    def _populate_targets_layout(self):
        if not hasattr(self, "sel_targets_layout"):
            return

        # 1. Defined Groups List
        if self.autoconnect_groups:
            grp_header = QLabel(f"Groups Defined ({len(self.autoconnect_groups)}):")
            grp_header.setStyleSheet("color: #dbdee1; font-weight: bold; font-size: 11px;")
            self.sel_targets_layout.addWidget(grp_header)

            for g in self.autoconnect_groups:
                grp_card = QFrame()
                grp_card.setStyleSheet(f"""
                    QFrame {{
                        background-color: #1e1f22;
                        border: 1px solid {g.color};
                        border-radius: 6px;
                    }}
                """)
                card_layout = QVBoxLayout(grp_card)
                card_layout.setContentsMargins(6, 6, 6, 6)
                card_layout.setSpacing(4)

                # Header row
                h_row = QHBoxLayout()
                h_row.setContentsMargins(0, 0, 0, 0)

                # Color swatch circle
                swatch = QLabel()
                swatch.setFixedSize(12, 12)
                swatch.setStyleSheet(f"background-color: {g.color}; border-radius: 6px; border: 1px solid #ffffff;")
                h_row.addWidget(swatch)

                # Title
                t_label = QLabel(f"Group {g.id} ({len(g.targets)} items)")
                t_label.setStyleSheet(f"color: {g.color}; font-weight: bold; font-size: 11px;")
                h_row.addWidget(t_label)
                h_row.addStretch()

                # Remove button
                btn_del = QPushButton("✕")
                btn_del.setFixedSize(18, 18)
                btn_del.setToolTip(f"Remove Group {g.id}")
                btn_del.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
                btn_del.setStyleSheet("""
                    QPushButton {
                        background-color: transparent;
                        color: #949ba4;
                        border: none;
                        font-weight: bold;
                        font-size: 11px;
                    }
                    QPushButton:hover {
                        color: #ed4245;
                    }
                """)
                btn_del.clicked.connect(lambda checked, gid=g.id: self.group_remove_requested.emit(gid))
                h_row.addWidget(btn_del)
                card_layout.addLayout(h_row)

                # Targets in group
                for t in g.targets:
                    item_lbl = QLabel(f"• {t.label}")
                    item_lbl.setStyleSheet("color: #dbdee1; font-size: 10px; margin-left: 8px;")
                    card_layout.addWidget(item_lbl)

                self.sel_targets_layout.addWidget(grp_card)

        # 2. Pending Selection (Transient)
        if self.autoconnect_targets:
            sel_header = QLabel(f"Pending Selection ({len(self.autoconnect_targets)}):")
            sel_header.setStyleSheet("color: #00e6ff; font-weight: bold; font-size: 11px; margin-top: 4px;")
            self.sel_targets_layout.addWidget(sel_header)

            for idx, t in enumerate(self.autoconnect_targets):
                t_lbl = QLabel(f"#{idx + 1}: {t.label}")
                t_lbl.setStyleSheet("color: #00e6ff; font-weight: 600; font-size: 10px; margin-left: 6px;")
                self.sel_targets_layout.addWidget(t_lbl)

            # Action buttons for selection
            btn_bar = QHBoxLayout()
            btn_bar.setContentsMargins(0, 2, 0, 2)
            btn_bar.setSpacing(6)

            btn_group = QPushButton("➕ Group (Ctrl+G)")
            btn_group.setToolTip("Group or merge selected conductors (Ctrl+G)")
            btn_group.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn_group.setStyleSheet("background-color: #2b2d31; color: #00e6ff; font-weight: bold; padding: 5px; border: 1px solid #00e6ff; border-radius: 4px;")
            btn_group.clicked.connect(self.group_all_requested.emit)
            btn_bar.addWidget(btn_group)

            btn_ungroup = QPushButton("➖ Remove (Ctrl+Shift+G)")
            btn_ungroup.setToolTip("Remove selected conductors from their group (Ctrl+Shift+G)")
            btn_ungroup.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn_ungroup.setStyleSheet("background-color: #2b2d31; color: #949ba4; font-weight: bold; padding: 5px; border: 1px solid #4e5058; border-radius: 4px;")
            btn_ungroup.clicked.connect(self.ungroup_requested.emit)
            btn_bar.addWidget(btn_ungroup)

            self.sel_targets_layout.addLayout(btn_bar)

        # 3. Empty state if neither groups nor selection
        if not self.autoconnect_groups and not self.autoconnect_targets:
            empty_lbl = QLabel("No conductors selected.\nClick pins, traces, or jumper ends on the board.\nPress Ctrl+G to create groups.")
            empty_lbl.setStyleSheet("color: #949ba4; font-style: italic; font-size: 11px;")
            self.sel_targets_layout.addWidget(empty_lbl)

        # 4. Connect Button
        if self.autoconnect_groups:
            btn_text = f"🔗 Connect All Groups ({len(self.autoconnect_groups)}) (Enter)"
            can_connect = all(len(g.targets) >= 2 for g in self.autoconnect_groups)
        else:
            btn_text = "🔗 Connect Selected (Enter)"
            can_connect = len(self.autoconnect_targets) >= 2

        btn_connect = QPushButton(btn_text)
        btn_connect.setStyleSheet("background-color: #5865f2; color: #ffffff; font-weight: bold; padding: 7px; border-radius: 4px;")
        btn_connect.setEnabled(can_connect)
        btn_connect.setToolTip("Route optimal connections without intersection (Enter)")
        btn_connect.clicked.connect(self.connect_requested.emit)
        self.sel_targets_layout.addWidget(btn_connect)

    def _update_targets_list(self):
        if not hasattr(self, "sel_targets_layout") or not hasattr(self, "sel_targets_grp"):
            return
        if self.autoconnect_groups:
            self.sel_targets_grp.setTitle(f"Conductor Groups ({len(self.autoconnect_groups)})")
        else:
            sel_count = len(self.autoconnect_targets)
            self.sel_targets_grp.setTitle(f"Selected Conductors ({sel_count})")

        self._clear_qlayout(self.sel_targets_layout)
        self._populate_targets_layout()
