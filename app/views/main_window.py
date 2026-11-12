"""
Main application window for PerfBoardMaker with viewport toolbar and mode handling.
Supports .pbrd file saving/loading and 200-step undo/redo.
"""
import os
import shutil
import threading
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QToolBar, QStatusBar, QLabel, QDockWidget, QFileDialog,
    QMessageBox, QInputDialog, QComboBox, QWidget, QVBoxLayout, QHBoxLayout,
    QToolButton, QSplitter, QSplitterHandle, QPushButton, QMenu, QWidgetAction,
    QProgressDialog,
)
from PyQt6.QtGui import QAction, QIcon, QKeySequence, QPixmap, QPainter, QColor
from PyQt6.QtCore import Qt, QSize, QRectF, QTimer, QSettings, QObject, pyqtSignal
from app.models.board import BoardConfig, col_index_to_name
from app.models.project import PROJECT_FILE_EXTENSION, PROJECT_FILE_FILTER, load_project_file
from app.utils.autosave import save_autosave_snapshot, get_latest_autosave_file, get_all_autosave_files, AUTOSAVES_DIR
from app.utils.logger import check_crash_log, clear_crash_log, write_no_crash, log_action
from app.utils.updater import (
    fetch_remote_version,
    get_local_version,
    is_newer_version,
    download_and_stage_update,
    launch_detached_updater,
)
from app.views.canvas_view import CanvasView
from app.views.toolbox_widget import ToolboxWidget
from app.views.properties_widget import PropertiesWidget
from app.views.viewport_toolbar import ViewportToolbar
from app.views.update_button import RainbowUpdateButton
from app.views.styles import DARK_THEME

VALID_BOARD_THEMES = ("green", "brown", "blue", "black")
_SETTINGS_ORG = "PerfBoardMaker"
_SETTINGS_APP = "PerfBoardMaker"
_NATIVE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "native")
_APP_ICON_CACHE: QIcon | None = None


def get_app_icon_path() -> str:
    """Returns the filesystem path to the bundled PerfBoardMaker icon."""
    for fname in ("Perficon.png", "perficon.png"):
        candidate = os.path.join(_NATIVE_DIR, fname)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(_NATIVE_DIR, "Perficon.png")


def get_app_icon() -> QIcon:
    """Returns the multi-resolution application QIcon loaded from app/native/Perficon.png."""
    global _APP_ICON_CACHE
    if _APP_ICON_CACHE is not None:
        return _APP_ICON_CACHE

    icon = QIcon()
    path = get_app_icon_path()
    pix = QPixmap(path)
    if not pix.isNull():
        for sz in (16, 24, 32, 48, 64, 128, 256):
            scaled = pix.scaled(
                sz, sz,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            icon.addPixmap(scaled)
        _APP_ICON_CACHE = icon
    return icon


class DoubleViewSplitterHandle(QSplitterHandle):
    """Splitter handle with a right-click context menu to swap Front/Back viewports."""

    def __init__(self, orientation: Qt.Orientation, parent: QSplitter):
        super().__init__(orientation, parent)
        self._last_menu = None

    def build_swap_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: #2b2d31; border: 1px solid #4e5058; border-radius: 6px; padding: 4px; }"
        )
        btn = QPushButton("←\n→", menu)
        btn.setObjectName("swap_double_view_btn")
        btn.setToolTip("Switch Left and Right Viewports")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #313338; color: #f2f3f5; border: 1px solid #4e5058;"
            "  border-radius: 4px; padding: 6px 18px; font-weight: bold; font-size: 13px;"
            "}"
            "QPushButton:hover { background-color: #5865f2; border-color: #7983f5; color: #ffffff; }"
        )
        action = QWidgetAction(menu)
        action.setText("←\n→")
        action.setDefaultWidget(btn)
        btn.clicked.connect(lambda _=False: (self.splitter().swap_requested.emit(), menu.close()))
        menu.addAction(action)
        menu._swap_btn = btn
        menu._swap_action = action
        return menu

    def contextMenuEvent(self, event):
        menu = self.build_swap_menu()
        self._last_menu = menu
        menu.exec(event.globalPos())
        event.accept()


class DoubleViewSplitter(QSplitter):
    """Horizontal splitter for Double-View supporting middle-bar right-click swap."""

    swap_requested = pyqtSignal()

    def createHandle(self) -> QSplitterHandle:
        return DoubleViewSplitterHandle(self.orientation(), self)
_SETTINGS_THEME_KEY = "board/last_theme"

BOARD_PRESETS = {
    "Standard (34 x 24)": (34, 24),
    "Small (24 x 18)": (24, 18),
    "Compact (20 x 14)": (20, 14),
    "Large (48 x 32)": (48, 32),
    "Eurocard (60 x 40)": (60, 40),
}

class _UpdateSignals(QObject):
    update_available = pyqtSignal(str, str)  # (local_ver, remote_ver)
    download_progress = pyqtSignal(int, int)  # (downloaded_bytes, total_bytes)
    download_finished = pyqtSignal(str, str)  # (staged_repo_root, temp_base_dir)
    download_failed = pyqtSignal(str)


class MainWindow(QMainWindow):
    @staticmethod
    def _get_last_board_theme() -> str:
        """Returns the last persisted board substrate theme, defaulting to 'green'."""
        settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        theme = str(settings.value(_SETTINGS_THEME_KEY, "green"))
        return theme if theme in VALID_BOARD_THEMES else "green"

    @staticmethod
    def _save_last_board_theme(theme: str) -> None:
        """Persists the last used board substrate theme across launches."""
        if theme not in VALID_BOARD_THEMES:
            return
        settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        settings.setValue(_SETTINGS_THEME_KEY, theme)
        settings.sync()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PerfBoardMaker - Untitled.pbrd")
        icon = get_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)
        self.resize(1340, 840)
        self.setStyleSheet(DARK_THEME)

        # File & Save tracking
        self.current_project_path: str | None = None

        # Board Configuration
        last_theme = self._get_last_board_theme()
        self.config = BoardConfig(cols=34, rows=24, pitch_px=24.0, style=last_theme, view_side="top")
        self._back_config = BoardConfig(
            cols=self.config.cols,
            rows=self.config.rows,
            pitch_px=self.config.pitch_px,
            margin_px=self.config.margin_px,
            hole_radius_px=self.config.hole_radius_px,
            pad_radius_px=self.config.pad_radius_px,
            style=self.config.style,
            view_side="bottom",
            transparent=self.config.transparent,
            transparent_components=self.config.transparent_components,
        )

        # Central Area with Viewport Toolbar and Canvas Host
        self.central_container = QWidget(self)
        central_layout = QVBoxLayout(self.central_container)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        # Viewport Toolbar directly above canvas, spanning the full width of the viewport
        self.viewport_toolbar = ViewportToolbar(self)
        central_layout.addWidget(self.viewport_toolbar, 0)

        # Viewport Host holds the QSplitter (Front | Back) plus top-left overlay toggles
        self.viewport_host = QWidget(self.central_container)
        vp_host_layout = QVBoxLayout(self.viewport_host)
        vp_host_layout.setContentsMargins(0, 0, 0, 0)
        vp_host_layout.setSpacing(0)

        self.viewport_splitter = DoubleViewSplitter(Qt.Orientation.Horizontal, self.viewport_host)
        self.viewport_splitter.setChildrenCollapsible(False)
        self.viewport_splitter.setHandleWidth(6)
        self.viewport_splitter.swap_requested.connect(self.swap_double_view_sides)
        self.viewport_splitter.setStyleSheet(
            "QSplitter::handle { background-color: #3f4249; }"
            "QSplitter::handle:hover { background-color: #5865f2; }"
        )

        self.canvas = CanvasView(self.config, self.viewport_splitter)
        self.canvas_back = CanvasView(self._back_config, self.viewport_splitter, primary_view=self.canvas)
        self.canvas.link_partner(self.canvas_back)
        self.canvas_back.hide()

        self.viewport_splitter.addWidget(self.canvas)
        self.viewport_splitter.addWidget(self.canvas_back)
        vp_host_layout.addWidget(self.viewport_splitter)

        # Floating Top-Left Viewport Toggle Buttons
        self.viewport_overlay = QWidget(self.viewport_host)
        self.viewport_overlay.setObjectName("ViewportOverlay")
        overlay_layout = QHBoxLayout(self.viewport_overlay)
        overlay_layout.setContentsMargins(4, 4, 4, 4)
        overlay_layout.setSpacing(6)
        self.viewport_overlay.setStyleSheet(
            "#ViewportOverlay {"
            "  background-color: rgba(24, 26, 31, 195);"
            "  border: 1px solid #3f4249;"
            "  border-radius: 6px;"
            "}"
        )

        self.btn_transparent = QPushButton("Transparent PCB", self.viewport_overlay)
        self.btn_transparent.setCheckable(True)
        self.btn_transparent.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_transparent.setToolTip("Make perfboard semi-transparent to see back-side solder traces, jumpers, and highlights")
        self.btn_transparent.setStyleSheet(
            "QPushButton {"
            "  background-color: #2b2d31; color: #dcddde; border: 1px solid #4e5058;"
            "  border-radius: 4px; padding: 4px 10px; font-weight: 600; font-size: 11px;"
            "}"
            "QPushButton:hover { background-color: #35373c; border-color: #6d707a; }"
            "QPushButton:checked { background-color: #0ea5e9; color: #ffffff; border: 1px solid #38bdf8; }"
            "QPushButton:checked:hover { background-color: #0284c7; }"
        )

        self.btn_transparent_components = QPushButton("Transparent Components", self.viewport_overlay)
        self.btn_transparent_components.setCheckable(True)
        self.btn_transparent_components.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_transparent_components.setToolTip("Make placed components semi-transparent independently of the PCB, solder traces, and jumpers")
        self.btn_transparent_components.setStyleSheet(self.btn_transparent.styleSheet())

        self.btn_double_view = QPushButton("Double-View", self.viewport_overlay)
        self.btn_double_view.setCheckable(True)
        self.btn_double_view.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_double_view.setToolTip("Split viewport side-by-side (Left: Front side, Right: Back side) with mirrored cursor & zoom")
        self.btn_double_view.setStyleSheet(
            "QPushButton {"
            "  background-color: #2b2d31; color: #dcddde; border: 1px solid #4e5058;"
            "  border-radius: 4px; padding: 4px 10px; font-weight: 600; font-size: 11px;"
            "}"
            "QPushButton:hover { background-color: #35373c; border-color: #6d707a; }"
            "QPushButton:checked { background-color: #5865f2; color: #ffffff; border: 1px solid #7983f5; }"
            "QPushButton:checked:hover { background-color: #4752c4; }"
        )

        overlay_layout.addWidget(self.btn_transparent)
        overlay_layout.addWidget(self.btn_transparent_components)
        overlay_layout.addWidget(self.btn_double_view)
        self.viewport_overlay.adjustSize()
        self.viewport_overlay.move(10, 10)
        self.viewport_overlay.raise_()

        central_layout.addWidget(self.viewport_host, 1)
        self.setCentralWidget(self.central_container)

        # Initial saved state tracking
        self._last_saved_state = self.canvas.serialize_state()

        # Toolbox Dock (Left)
        self.toolbox = ToolboxWidget(self)
        self.dock_toolbox = QDockWidget("Toolbox", self)
        self.dock_toolbox.setWidget(self.toolbox)
        self.dock_toolbox.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.dock_toolbox)

        # Properties Dock (Right)
        self.properties = PropertiesWidget(self.config, self)
        self.dock_props = QDockWidget("Inspector", self)
        self.dock_props.setWidget(self.properties)
        self.dock_props.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_props)

        # Connect Signals
        self._connect_signals()

        # Build UI Elements
        self._build_menu()
        self._build_toolbar()
        self._build_statusbar()
        self._setup_shortcuts()

        # Subscribe to undo/redo history notifications
        self.canvas.history.add_listener(self._on_history_changed)
        self._on_history_changed()

        # Autosave periodic timer (every 10 seconds)
        self._last_autosaved_state = None
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(10000)  # 10 seconds
        self.autosave_timer.timeout.connect(self._perform_autosave)
        self.autosave_timer.start()

        # Check crash log and recover session if needed
        QTimer.singleShot(100, self._check_crash_recovery)

        # Startup update check from GitHub
        self._local_version = get_local_version()
        self._remote_version: str | None = None
        self._updating_exit = False
        self._update_in_progress = False
        self._update_cancel_event: threading.Event | None = None
        self._update_progress_dlg: QProgressDialog | None = None
        self._update_signals = _UpdateSignals(self)
        self._update_signals.update_available.connect(self._on_update_available)
        self._update_signals.download_progress.connect(self._on_download_progress)
        self._update_signals.download_finished.connect(self._on_download_finished)
        self._update_signals.download_failed.connect(self._on_download_failed)
        QTimer.singleShot(350, self._start_update_check)

        # Fit board after initial window show & layout completes
        self._initial_fit_done = False

    def _connect_signals(self):
        # Viewport Overlay Toggles
        self.btn_transparent.toggled.connect(self._on_transparent_toggled)
        self.btn_transparent_components.toggled.connect(self._on_transparent_components_toggled)
        self.btn_double_view.toggled.connect(self._on_double_view_toggled)

        # Canvas & Back Partner Canvas to Status / Props
        for cv in (self.canvas, self.canvas_back):
            cv.hover_hole_changed.connect(self._on_hover_hole_changed)
            cv.selection_changed.connect(self._on_selection_changed)
            cv.component_placed.connect(self._on_component_placed)
            cv.board_resized.connect(self._on_canvas_board_resized)
            cv.mode_changed.connect(self._set_app_mode)
            cv.autoconnect_selection_changed.connect(self.properties.set_autoconnect_targets)
            cv.autoconnect_groups_changed.connect(self.properties.set_autoconnect_groups)
            cv.autoconnect_completed.connect(self._on_autoconnect_completed)

        self.canvas.view_side_changed.connect(self._on_view_side_changed)

        # Mode switching from ViewportToolbar
        self.viewport_toolbar.mode_changed.connect(self._set_app_mode)

        # Jumper color sync
        self.viewport_toolbar.jumper_color_changed.connect(self._on_jumper_color_changed)
        self.properties.active_color_changed.connect(self._on_jumper_color_changed)

        # Toolbox to Canvas
        self.toolbox.component_selected.connect(self.canvas.start_placement_mode)

        # Properties to Canvas
        self.properties.property_changed.connect(self._on_property_changed)
        self.properties.board_changed.connect(self._on_board_settings_changed)
        self.properties.delete_requested.connect(self.canvas.remove_selected_item)

        # AutoConnect triggers
        self.properties.connect_requested.connect(self.canvas.perform_autoconnect)
        self.properties.autoconnect_settings_changed.connect(self.canvas.set_autoconnect_settings)
        self.properties.group_remove_requested.connect(self.canvas.remove_autoconnect_group)
        self.properties.group_all_requested.connect(self.canvas.group_selected_targets)
        self.properties.ungroup_requested.connect(self.canvas.ungroup_selected_targets)
        self.properties.clear_groups_requested.connect(self.canvas.clear_autoconnect_groups)
        self.properties.optimize_board_requested.connect(self._on_optimize_board_requested)

    def _setup_shortcuts(self):
        # Hotkeys 1, 2, 3, 4 for modes
        act_mode_1 = QAction("Select Mode", self)
        act_mode_1.setShortcut(QKeySequence("1"))
        act_mode_1.triggered.connect(lambda: self._set_app_mode("select"))
        self.addAction(act_mode_1)

        act_mode_2 = QAction("Solder Mode", self)
        act_mode_2.setShortcut(QKeySequence("2"))
        act_mode_2.triggered.connect(lambda: self._set_app_mode("solder"))
        self.addAction(act_mode_2)

        act_mode_3 = QAction("Jumper Mode", self)
        act_mode_3.setShortcut(QKeySequence("3"))
        act_mode_3.triggered.connect(lambda: self._set_app_mode("jumper"))
        self.addAction(act_mode_3)

        act_mode_4 = QAction("AutoConnect Mode", self)
        act_mode_4.setShortcut(QKeySequence("4"))
        act_mode_4.triggered.connect(lambda: self._set_app_mode("autoconnect"))
        self.addAction(act_mode_4)

        # AutoConnect grouping shortcuts
        act_group = QAction("Group Conductors", self)
        act_group.setShortcut(QKeySequence("Ctrl+G"))
        act_group.triggered.connect(self.canvas.group_selected_targets)
        self.addAction(act_group)

        act_ungroup = QAction("Ungroup Conductors", self)
        act_ungroup.setShortcut(QKeySequence("Ctrl+Shift+G"))
        act_ungroup.triggered.connect(self.canvas.ungroup_selected_targets)
        self.addAction(act_ungroup)

    def _set_app_mode(self, mode: str):
        if self.viewport_toolbar.current_mode != mode:
            self.viewport_toolbar.set_mode(mode)
        if self.canvas.current_mode != mode:
            self.canvas.set_mode(mode)
        if self.canvas_back.current_mode != mode:
            self.canvas_back.set_mode(mode)
        self.properties.set_mode(mode)
        self._update_mode_status(mode)

    def _on_jumper_color_changed(self, hex_color: str):
        self.canvas.set_active_jumper_color(hex_color)
        self.canvas_back.active_jumper_color = hex_color
        self.viewport_toolbar.set_active_jumper_color(hex_color)
        self.properties.set_active_jumper_color(hex_color)

    def _build_menu(self):
        menubar = self.menuBar()

        # --- FILE MENU ---
        file_menu = menubar.addMenu("&File")

        self.act_new = QAction("📄 New Project", self)
        self.act_new.setShortcut(QKeySequence.StandardKey.New)
        self.act_new.triggered.connect(self._new_project)
        file_menu.addAction(self.act_new)

        self.act_open = QAction("📂 Open Project...", self)
        self.act_open.setShortcut(QKeySequence.StandardKey.Open)
        self.act_open.triggered.connect(self._open_project)
        file_menu.addAction(self.act_open)

        self.act_save = QAction("💾 Save Project", self)
        self.act_save.setShortcut(QKeySequence.StandardKey.Save)
        self.act_save.triggered.connect(self._save_project)
        file_menu.addAction(self.act_save)

        self.act_save_as = QAction("💾 Save Project As...", self)
        self.act_save_as.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.act_save_as.triggered.connect(self._save_project_as)
        file_menu.addAction(self.act_save_as)

        file_menu.addSeparator()

        self.act_export = QAction("📷 Export Image...", self)
        self.act_export.setShortcut(QKeySequence("Ctrl+E"))
        self.act_export.triggered.connect(self._export_image)
        file_menu.addAction(self.act_export)

        file_menu.addSeparator()

        act_exit = QAction("❌ Exit", self)
        act_exit.setShortcut(QKeySequence("Ctrl+Q"))
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        # --- EDIT MENU ---
        edit_menu = menubar.addMenu("&Edit")

        self.act_undo = QAction("↩️ Undo", self)
        self.act_undo.setShortcut(QKeySequence.StandardKey.Undo)  # Ctrl+Z
        self.act_undo.triggered.connect(self._undo)
        self.act_undo.setEnabled(False)
        edit_menu.addAction(self.act_undo)

        self.act_redo = QAction("↪️ Redo", self)
        # Redo shortcuts: Ctrl+Y and Ctrl+Shift+Z
        self.act_redo.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        self.act_redo.triggered.connect(self._redo)
        self.act_redo.setEnabled(False)
        edit_menu.addAction(self.act_redo)

        edit_menu.addSeparator()

        self.act_rot_cw = QAction("↷ Rotate CW", self)
        self.act_rot_cw.setShortcut(QKeySequence("R"))
        self.act_rot_cw.triggered.connect(self._rotate_cw)
        edit_menu.addAction(self.act_rot_cw)

        self.act_rot_ccw = QAction("↶ Rotate CCW", self)
        self.act_rot_ccw.setShortcut(QKeySequence("Shift+R"))
        self.act_rot_ccw.triggered.connect(self._rotate_ccw)
        edit_menu.addAction(self.act_rot_ccw)

        edit_menu.addSeparator()

        act_delete = QAction("🗑️ Delete Selected", self)
        act_delete.setShortcut(QKeySequence.StandardKey.Delete)
        act_delete.triggered.connect(self.canvas.remove_selected_item)
        edit_menu.addAction(act_delete)

        self.act_clear = QAction("🧹 Clear Board...", self)
        self.act_clear.triggered.connect(self._clear_board)
        edit_menu.addAction(self.act_clear)

        # --- VIEW MENU ---
        view_menu = menubar.addMenu("&View")

        self.act_flip = QAction("🔄 Flip Board Side", self)
        self.act_flip.setShortcut(QKeySequence("F"))
        self.act_flip.triggered.connect(self.canvas.toggle_view_side)
        view_menu.addAction(self.act_flip)

        view_menu.addSeparator()

        self.act_zoom_in = QAction("🔍+ Zoom In", self)
        self.act_zoom_in.setShortcut(QKeySequence.StandardKey.ZoomIn)
        self.act_zoom_in.triggered.connect(self.canvas.zoom_in)
        view_menu.addAction(self.act_zoom_in)

        self.act_zoom_out = QAction("🔍- Zoom Out", self)
        self.act_zoom_out.setShortcut(QKeySequence.StandardKey.ZoomOut)
        self.act_zoom_out.triggered.connect(self.canvas.zoom_out)
        view_menu.addAction(self.act_zoom_out)

        self.act_zoom_fit = QAction("⛶ Fit Board", self)
        self.act_zoom_fit.setShortcut(QKeySequence("Ctrl+0"))
        self.act_zoom_fit.triggered.connect(self.canvas.zoom_to_fit)
        view_menu.addAction(self.act_zoom_fit)

        view_menu.addSeparator()

        self.act_mode_select = QAction("Select Mode (1)", self)
        self.act_mode_select.triggered.connect(lambda: self._set_app_mode("select"))
        view_menu.addAction(self.act_mode_select)

        self.act_mode_solder = QAction("Solder Mode (2)", self)
        self.act_mode_solder.triggered.connect(lambda: self._set_app_mode("solder"))
        view_menu.addAction(self.act_mode_solder)

        self.act_mode_jumper = QAction("Jumper Mode (3)", self)
        self.act_mode_jumper.triggered.connect(lambda: self._set_app_mode("jumper"))
        view_menu.addAction(self.act_mode_jumper)

        self.act_mode_autoconnect = QAction("AutoConnect Mode (4)", self)
        self.act_mode_autoconnect.triggered.connect(lambda: self._set_app_mode("autoconnect"))
        view_menu.addAction(self.act_mode_autoconnect)

    def _build_toolbar(self):
        tb = QToolBar("Main Toolbar", self)
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        self.addToolBar(tb)

        # File actions
        tb.addAction(self.act_new)
        tb.addAction(self.act_open)
        tb.addAction(self.act_save)

        tb.addSeparator()

        # Undo / Redo actions
        tb.addAction(self.act_undo)
        tb.addAction(self.act_redo)

        tb.addSeparator()

        # Flip View Button (Top vs Bottom)
        tb.addAction(self.act_flip)

        self.btn_view_indicator = QToolButton()
        self.btn_view_indicator.setText("👁️ VIEW: TOP (Components)")
        self.btn_view_indicator.setStyleSheet("font-weight: bold; color: #5865f2; background-color: #2b2d31;")
        self.btn_view_indicator.clicked.connect(self.canvas.toggle_view_side)
        tb.addWidget(self.btn_view_indicator)

        tb.addSeparator()

        # Rotate Component
        tb.addAction(self.act_rot_cw)
        tb.addAction(self.act_rot_ccw)

        tb.addSeparator()

        # Zoom Controls
        tb.addAction(self.act_zoom_in)
        tb.addAction(self.act_zoom_out)
        tb.addAction(self.act_zoom_fit)

        tb.addSeparator()

        # Preset Board Sizes
        tb.addWidget(QLabel(" Size: "))
        self.combo_presets = QComboBox()
        self.combo_presets.addItems(list(BOARD_PRESETS.keys()) + ["Custom..."])
        self.combo_presets.currentIndexChanged.connect(self._on_preset_size_changed)
        tb.addWidget(self.combo_presets)

        # Board Substrate Theme
        tb.addWidget(QLabel(" Theme: "))
        self.combo_theme = QComboBox()
        self.combo_theme.addItems(["Green FR4", "Phenolic Brown", "Blue FR4", "Matte Black"])
        self.combo_theme.currentIndexChanged.connect(self._on_theme_changed)
        tb.addWidget(self.combo_theme)

        tb.addSeparator()

        # Clear and Export
        tb.addAction(self.act_clear)
        tb.addAction(self.act_export)

    def _build_statusbar(self):
        sb = self.statusBar()
        sb.setMinimumHeight(30)

        self.lbl_mode = QLabel("[MODE: SELECT (1)]")
        self.lbl_mode.setMinimumWidth(145)
        self.lbl_mode.setStyleSheet("font-weight: bold; color: #5865f2;")
        sb.addWidget(self.lbl_mode)

        self.lbl_hole_coord = QLabel("Hole: --")
        self.lbl_hole_coord.setMinimumWidth(95)
        sb.addWidget(self.lbl_hole_coord)

        self.lbl_view_side = QLabel("[TOP VIEW - Component Side]")
        self.lbl_view_side.setMinimumWidth(175)
        self.lbl_view_side.setStyleSheet("font-weight: bold; color: #5865f2;")
        sb.addWidget(self.lbl_view_side)

        self.lbl_comp_count = QLabel("Components: 0 | Jumpers: 0")
        self.lbl_comp_count.setMinimumWidth(165)
        sb.addWidget(self.lbl_comp_count)

        # Center area for update notification button
        self._sb_left_spacer = QWidget(sb)
        self._sb_left_spacer.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        sb.addWidget(self._sb_left_spacer, 1)

        self.btn_update = RainbowUpdateButton("Newer Version Found", sb)
        self.btn_update.setVisible(False)
        self.btn_update.clicked.connect(self._on_update_button_clicked)
        sb.addWidget(self.btn_update, 0)

        self._sb_right_spacer = QWidget(sb)
        self._sb_right_spacer.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        sb.addWidget(self._sb_right_spacer, 8)

        sb.addPermanentWidget(QLabel("1-4: Modes | Ctrl+G: Group | Enter: Connect | F: Flip"))

    def _update_mode_status(self, mode: str):
        mode_titles = {
            "select": "[MODE: SELECT (1)]",
            "solder": "[MODE: SOLDER (2)]",
            "jumper": "[MODE: JUMPER (3)]",
            "autoconnect": "[MODE: AUTOCONNECT (4)]"
        }
        self.lbl_mode.setText(mode_titles.get(mode, "[MODE: SELECT]"))

    def _on_autoconnect_completed(self, res: dict):
        if not res or not res.get("success"):
            reason = res.get("message") or res.get("reason", "AutoConnect failed")
            self.statusBar().showMessage(f"⚠️ AutoConnect: {reason}", 5000)
        else:
            n_solder = len(res.get("solder_segments", []))
            n_jumpers = len(res.get("jumpers", []))
            cost = res.get("total_cost", 0)
            n_groups = len(res.get("group_details", []))
            if n_groups > 1:
                msg = f"✅ AutoConnect completed! Routed {n_groups} groups without intersection ({n_solder} solder segments, {n_jumpers} jumpers). Total cost: {cost}"
            else:
                msg = f"✅ AutoConnect completed! Added {n_solder} solder segments, {n_jumpers} jumpers. Total cost: {cost}"
            self.statusBar().showMessage(msg, 6000)

    def _on_optimize_board_requested(self):
        groups = self.canvas.get_optimize_board_groups()
        if not groups:
            QMessageBox.information(
                self,
                "Optimize Board",
                "No shorted component pin groups (2 or more connected pins) were found on the board.\n\n"
                "Nothing was modified.",
            )
            return

        total_pins = sum(len(g.targets) for g in groups)
        n_traces = len(self.canvas.solder_mgr.traces)
        n_jumpers = len(self.canvas.jumpers)

        reply = QMessageBox.warning(
            self,
            "Optimize Board",
            f"Optimize Board detected {len(groups)} electrically connected pin group(s) "
            f"({total_pins} component pins total).\n\n"
            f"Proceeding will:\n"
            f"• Delete ALL existing solder traces ({n_traces}) and jumper wires ({n_jumpers}) on the board\n"
            f"• Re-route all {len(groups)} pin group(s) cleanly using the current Routing Cost Weights\n\n"
            f"After optimization, you can adjust the Routing Cost Weights in real time or press Ctrl+Z to undo.\n\n"
            f"Do you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        res = self.canvas.optimize_board(precomputed_groups=groups)
        self._update_comp_count()
        if not res or not res.get("success"):
            reason = (res or {}).get("message") or (res or {}).get("reason", "Optimize Board failed.")
            QMessageBox.warning(self, "Optimize Board Failed", reason)

    # Event handlers
    def _rotate_cw(self):
        sel = self.canvas.get_selected_component_item()
        if sel:
            sel.rotate_cw()
            self.properties.show_component_properties(sel)
        elif self.canvas.placement_ghost_item:
            self.canvas.placement_ghost_item.rotate_cw()
            self.canvas.placement_rotation = self.canvas.placement_ghost.rotation

    def _rotate_ccw(self):
        sel = self.canvas.get_selected_component_item()
        if sel:
            sel.rotate_ccw()
            self.properties.show_component_properties(sel)
        elif self.canvas.placement_ghost_item:
            self.canvas.placement_ghost_item.rotate_ccw()
            self.canvas.placement_rotation = self.canvas.placement_ghost.rotation

    def _on_hover_hole_changed(self, col: int, row: int, col_name: str):
        self.lbl_hole_coord.setText(f"Hole: {col_name}{row + 1} (Col: {col}, Row: {row})")

    def _on_selection_changed(self, item):
        self.properties.set_selected_item(item)

    def _on_transparent_toggled(self, checked: bool):
        self.canvas.set_transparent(checked)
        self.viewport_overlay.raise_()

    def _on_transparent_components_toggled(self, checked: bool):
        self.canvas.set_components_transparent(checked)
        self.viewport_overlay.raise_()

    def swap_double_view_sides(self):
        if not self.btn_double_view.isChecked() or self.viewport_splitter.count() < 2:
            return
        w0 = self.viewport_splitter.widget(0)
        w1 = self.viewport_splitter.widget(1)
        sizes = self.viewport_splitter.sizes()
        self.viewport_splitter.insertWidget(0, w1)
        self.viewport_splitter.insertWidget(1, w0)
        if len(sizes) == 2:
            self.viewport_splitter.setSizes([sizes[1], sizes[0]])
        left_is_front = (self.viewport_splitter.widget(0) is self.canvas)
        order_lbl = "Front | Back" if left_is_front else "Back | Front"
        self.lbl_view_side.setText(f"[DOUBLE VIEW - {order_lbl}]")
        self.viewport_overlay.raise_()

    def _on_double_view_toggled(self, checked: bool):
        if checked:
            self.canvas.set_double_view_active(True, badge="FRONT (TOP)")
            self.canvas_back.set_double_view_active(True, badge="BACK (BOTTOM)")
            self.canvas._notify_partner_sync(full=True)
            self.canvas_back.show()

            total_w = max(400, self.viewport_splitter.width())
            half_w = total_w // 2
            self.viewport_splitter.setSizes([half_w, total_w - half_w])

            self.act_flip.setEnabled(False)
            self.btn_view_indicator.setEnabled(False)
            self.btn_view_indicator.setText("👁️ VIEW: FRONT + BACK (Double)")
            self.btn_view_indicator.setStyleSheet("font-weight: bold; color: #7983f5; background-color: #2b2d31;")
            left_is_front = (self.viewport_splitter.widget(0) is self.canvas)
            order_lbl = "Front | Back" if left_is_front else "Back | Front"
            self.lbl_view_side.setText(f"[DOUBLE VIEW - {order_lbl}]")

            self.canvas.zoom_to_fit()
            QTimer.singleShot(0, self.canvas.zoom_to_fit)
        else:
            if self.viewport_splitter.widget(0) is not self.canvas:
                self.viewport_splitter.insertWidget(0, self.canvas)
                self.viewport_splitter.insertWidget(1, self.canvas_back)
            self.canvas.set_double_view_active(False)
            self.canvas_back.set_double_view_active(False)
            self.canvas_back.hide()

            self.act_flip.setEnabled(True)
            self.btn_view_indicator.setEnabled(True)
            self._on_view_side_changed(self.config.view_side)
            QTimer.singleShot(0, self.canvas.zoom_to_fit)

        self.viewport_overlay.raise_()

    def _on_view_side_changed(self, side: str):
        if self.btn_double_view.isChecked():
            return
        if side == "top":
            self.btn_view_indicator.setText("👁️ VIEW: TOP (Components)")
            self.btn_view_indicator.setStyleSheet("font-weight: bold; color: #5865f2; background-color: #2b2d31;")
            self.lbl_view_side.setText("[TOP VIEW - Component Side]")
        else:
            self.btn_view_indicator.setText("👁️ VIEW: BOTTOM (Solder Side)")
            self.btn_view_indicator.setStyleSheet("font-weight: bold; color: #f0b232; background-color: #2b2d31;")
            self.lbl_view_side.setText("[BOTTOM VIEW - Solder Side]")

    def _on_component_placed(self, comp):
        self._update_comp_count()

    def _on_property_changed(self):
        self._update_comp_count()
        self.canvas.record_undo_snapshot()

    def _on_board_settings_changed(self):
        self._save_last_board_theme(self.config.style)
        self.canvas.reinit_board()
        self.canvas.record_undo_snapshot()

    def _sync_preset_combo(self):
        """Synchronizes toolbar preset combo box with current config dimensions."""
        self.combo_presets.blockSignals(True)
        dims = (self.config.cols, self.config.rows)
        matched = False
        for i, (_, (w, h)) in enumerate(BOARD_PRESETS.items()):
            if (w, h) == dims:
                self.combo_presets.setCurrentIndex(i)
                matched = True
                break
        if not matched:
            custom_idx = self.combo_presets.findText("Custom...")
            if custom_idx >= 0:
                self.combo_presets.setCurrentIndex(custom_idx)
        self.combo_presets.blockSignals(False)

    def _on_canvas_board_resized(self, cols: int, rows: int):
        self._sync_preset_combo()
        # Update spinboxes live during drag without rebuilding layout; refresh full card on release
        if not (self.canvas._board_resize_active or self.canvas_back._board_resize_active):
            self.properties.refresh_view()
        elif self.properties.active_mode != "autoconnect" and not self.properties.selected_item:
            for attr, val in (("spin_cols", cols), ("spin_rows", rows)):
                spin = getattr(self.properties, attr, None)
                if spin is not None:
                    try:
                        spin.blockSignals(True)
                        spin.setValue(val)
                        spin.blockSignals(False)
                    except RuntimeError:
                        pass
        self.statusBar().showMessage(f"Board size: {cols} x {rows} holes", 1500)

    def _update_comp_count(self):
        c_cnt = len(self.canvas.placed_components)
        j_cnt = len(self.canvas.jumpers)
        self.lbl_comp_count.setText(f"Components: {c_cnt} | Jumpers: {j_cnt}")

    def _on_preset_size_changed(self, idx: int):
        text = self.combo_presets.currentText()
        if text == "Custom...":
            cols, ok1 = QInputDialog.getInt(self, "Board Width", "Columns (Holes):", self.config.cols, 8, 120)
            if not ok1:
                return
            rows, ok2 = QInputDialog.getInt(self, "Board Height", "Rows (Holes):", self.config.rows, 8, 100)
            if not ok2:
                return
            self.config.cols = cols
            self.config.rows = rows
        elif text in BOARD_PRESETS:
            self.config.cols, self.config.rows = BOARD_PRESETS[text]

        self.canvas.reinit_board()
        self.canvas._notify_partner_sync(full=False)
        self.canvas.zoom_to_fit()
        self.properties.refresh_view()
        self.canvas.record_undo_snapshot()

    def _on_theme_changed(self, idx: int):
        if 0 <= idx < len(VALID_BOARD_THEMES):
            self.config.style = VALID_BOARD_THEMES[idx]
            self._save_last_board_theme(self.config.style)
        self.canvas.reinit_board()
        self.canvas._notify_partner_sync(full=False)
        self.properties.refresh_view()
        self.canvas.record_undo_snapshot()

    # --- UNDO / REDO & HISTORY HANDLING ---
    def _undo(self):
        if self.canvas.undo():
            self.statusBar().showMessage("Undo executed", 1500)

    def _redo(self):
        if self.canvas.redo():
            self.statusBar().showMessage("Redo executed", 1500)

    def _is_modified(self) -> bool:
        return self.canvas.serialize_state() != self._last_saved_state

    def _update_window_title(self):
        name = os.path.basename(self.current_project_path) if self.current_project_path else "Untitled.pbrd"
        mod = "*" if self._is_modified() else ""
        self.setWindowTitle(f"PerfBoardMaker - {name}{mod}")
        self.setWindowModified(bool(mod))

    def _on_history_changed(self):
        can_undo = self.canvas.history.can_undo()
        can_redo = self.canvas.history.can_redo()
        self.act_undo.setEnabled(can_undo)
        self.act_redo.setEnabled(can_redo)

        undo_steps = max(0, len(self.canvas.history.undo_stack) - 1)
        redo_steps = len(self.canvas.history.redo_stack)
        self.act_undo.setToolTip(f"Undo (Ctrl+Z) - {undo_steps} step(s) available")
        self.act_redo.setToolTip(f"Redo (Ctrl+Y / Ctrl+Shift+Z) - {redo_steps} step(s) available")

        # Sync size combo without emitting signals
        self._sync_preset_combo()

        # Sync theme combo without emitting signals
        self.combo_theme.blockSignals(True)
        theme_names = {"green": 0, "brown": 1, "blue": 2, "black": 3}
        if self.config.style in theme_names:
            self.combo_theme.setCurrentIndex(theme_names[self.config.style])
        self.combo_theme.blockSignals(False)

        # Keep board dimensions UI synced on undo/redo
        spin_c = getattr(self.properties, "spin_cols", None)
        spin_r = getattr(self.properties, "spin_rows", None)
        if spin_c is not None and spin_r is not None:
            try:
                if spin_c.value() != self.config.cols or spin_r.value() != self.config.rows:
                    self.properties.refresh_view()
            except RuntimeError:
                pass

        self._update_comp_count()
        self._update_window_title()

    # --- PROJECT FILE HANDLING (.pbrd) ---
    def _maybe_save(self) -> bool:
        if not self._is_modified():
            return True
        name = os.path.basename(self.current_project_path) if self.current_project_path else "Untitled.pbrd"
        res = QMessageBox.question(
            self, "Save Project Changes?",
            f"The project '{name}' has unsaved changes.\n\nDo you want to save your changes before proceeding?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save
        )
        if res == QMessageBox.StandardButton.Save:
            return self._save_project()
        elif res == QMessageBox.StandardButton.Discard:
            return True
        return False

    def _new_project(self):
        if not self._maybe_save():
            return
        try:
            self._perform_autosave()
        except Exception:
            pass
        self._last_autosaved_state = None
        self.config.cols = 34
        self.config.rows = 24
        self.config.style = self._get_last_board_theme()
        self.config.view_side = "top"

        for item in list(self.canvas.component_items):
            self.canvas.scene.removeItem(item)
        self.canvas.component_items.clear()
        self.canvas.placed_components.clear()

        for j_item in list(self.canvas.jumper_items):
            self.canvas.scene.removeItem(j_item)
        self.canvas.jumper_items.clear()
        self.canvas.jumpers.clear()

        self.canvas.solder_mgr.clear()
        self.canvas.reinit_board()
        self.canvas._notify_partner_sync(full=True)
        self.canvas.zoom_to_fit()
        self._on_view_side_changed("top")
        self.properties.set_selected_item(None)

        self.current_project_path = None
        self.canvas.history.reset(self.canvas.serialize_state())
        self._last_saved_state = self.canvas.serialize_state()
        self._on_history_changed()
        self.statusBar().showMessage("New project created", 2000)

    def _open_project(self):
        if not self._maybe_save():
            return
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Open PerfBoard Project", "", PROJECT_FILE_FILTER
        )
        if not filepath:
            return
        try:
            self._perform_autosave()
        except Exception:
            pass
        self._last_autosaved_state = None
        try:
            self.canvas.load_project(filepath)
            self._save_last_board_theme(self.config.style)
            self.current_project_path = filepath
            self._last_saved_state = self.canvas.serialize_state()
            self.canvas.zoom_to_fit()
            self.properties.refresh_view()
            self._on_history_changed()
            self.statusBar().showMessage(f"Loaded: {os.path.basename(filepath)}", 3000)
        except Exception as e:
            QMessageBox.critical(self, "Open Project Error", f"Failed to open project:\n{str(e)}")

    def _save_project(self) -> bool:
        if self.current_project_path:
            try:
                self.canvas.save_project(self.current_project_path)
                self._last_saved_state = self.canvas.serialize_state()
                self._update_window_title()
                self.statusBar().showMessage(f"Saved: {os.path.basename(self.current_project_path)}", 3000)
                return True
            except Exception as e:
                QMessageBox.critical(self, "Save Project Error", f"Failed to save project:\n{str(e)}")
                return False
        else:
            return self._save_project_as()

    def _save_project_as(self) -> bool:
        default_name = self.current_project_path if self.current_project_path else "my_project.pbrd"
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Save PerfBoard Project As", default_name, PROJECT_FILE_FILTER
        )
        if not filepath:
            return False
        if not filepath.lower().endswith(PROJECT_FILE_EXTENSION):
            filepath += PROJECT_FILE_EXTENSION
        try:
            self.canvas.save_project(filepath)
            self.current_project_path = filepath
            self._last_saved_state = self.canvas.serialize_state()
            self._update_window_title()
            self.statusBar().showMessage(f"Saved: {os.path.basename(filepath)}", 3000)
            return True
        except Exception as e:
            QMessageBox.critical(self, "Save Project Error", f"Failed to save project:\n{str(e)}")
            return False

    def showEvent(self, event):
        super().showEvent(event)
        if not self._initial_fit_done:
            self._initial_fit_done = True
            QTimer.singleShot(0, self.canvas.zoom_to_fit)

    def closeEvent(self, event):
        if self._updating_exit:
            write_no_crash()
            event.accept()
            return
        if self._maybe_save():
            self._save_last_board_theme(self.config.style)
            # Perform final autosave if project was modified
            try:
                self._perform_autosave()
            except Exception:
                pass
            # Write NoCrash to crash.log before normal closure
            write_no_crash()
            event.accept()
        else:
            event.ignore()

    # --- AUTOSAVE & CRASH RECOVERY ---
    def _perform_autosave(self):
        try:
            if not hasattr(self, "canvas"):
                return
            current_state = self.canvas.serialize_state()
            if self._last_autosaved_state == current_state:
                return

            project_name = "Untitled"
            if self.current_project_path:
                project_name = os.path.splitext(os.path.basename(self.current_project_path))[0]

            filepath = save_autosave_snapshot(current_state, project_name, self.current_project_path)
            self._last_autosaved_state = current_state
            log_action("Autosave snapshot created", f"file={os.path.basename(filepath)}")
        except Exception as e:
            pass

    def _check_crash_recovery(self):
        status, content = check_crash_log()
        if status == "clean":
            # If the log says "NoCrash" and nothing else, delete everything in the crash log, and continue operating normally.
            clear_crash_log()
            return

        # If crash log is empty, (which means the app could not write NoCrash and could not record a crash so something went wrong),
        # or if there's a crash logged, prompt the user "The app is not closed properly, recover last session?"
        res = QMessageBox.question(
            self,
            "Crash Recovery",
            "The app is not closed properly, recover last session?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        if res == QMessageBox.StandardButton.Yes:
            self.recover_last_session()

        clear_crash_log()

    def recover_last_session(self) -> bool:
        latest_file = get_latest_autosave_file()
        if not latest_file:
            QMessageBox.information(
                self,
                "No Autosave Found",
                "No autosaved session was found in the autosaves directory."
            )
            return False

        try:
            self.canvas.load_project(latest_file)
            self._save_last_board_theme(self.config.style)
            try:
                raw_data = load_project_file(latest_file)
                meta = raw_data.get("meta", {})
                orig = meta.get("original_path")
                if orig and os.path.isfile(orig):
                    self.current_project_path = orig
                else:
                    self.current_project_path = None
            except Exception:
                self.current_project_path = None

            self._last_saved_state = None  # Mark as modified so user is prompted to save
            self.properties.refresh_view()
            self._on_history_changed()
            self.canvas.zoom_to_fit()
            fname = os.path.basename(latest_file)
            self.statusBar().showMessage(f"Recovered session from {fname}", 4000)
            log_action("Session recovered", f"file={fname}")
            return True
        except Exception as e:
            QMessageBox.critical(
                self,
                "Recovery Error",
                f"Failed to recover last session from autosave:\n{str(e)}"
            )
            return False

    def _clear_board(self):
        total = len(self.canvas.placed_components) + len(self.canvas.jumpers) + len(self.canvas.solder_mgr.traces)
        if total == 0:
            return
        ans = QMessageBox.question(
            self, "Clear Perfboard",
            f"Are you sure you want to clear all components, jumper wires, and solder traces?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if ans == QMessageBox.StandardButton.Yes:
            for item in list(self.canvas.component_items):
                self.canvas.scene.removeItem(item)
            self.canvas.component_items.clear()
            self.canvas.placed_components.clear()

            for j_item in list(self.canvas.jumper_items):
                self.canvas.scene.removeItem(j_item)
            self.canvas.jumper_items.clear()
            self.canvas.jumpers.clear()

            self.canvas.solder_mgr.clear()
            self.canvas.solder_item.update()

            self.properties.set_selected_item(None)
            self._update_comp_count()
            self.canvas.record_undo_snapshot()

    def _export_image(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Board Image", "perfboard.png", "PNG Images (*.png);;All Files (*)")
        if not path:
            return

        w = int(self.config.width_px)
        h = int(self.config.height_px)
        pix = QPixmap(w, h)
        pix.fill(QColor(24, 25, 28))

        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        self.canvas.scene.render(painter, target=QRectF(pix.rect()), source=self.canvas.board_item.boundingRect())
        painter.end()

        pix.save(path)
        QMessageBox.information(self, "Export Complete", f"Perfboard layout successfully exported to:\n{path}")

    # --- AUTO-UPDATE FROM GITHUB ---
    def _start_update_check(self):
        local_ver = self._local_version

        def _worker():
            remote_ver = fetch_remote_version()
            if remote_ver and is_newer_version(remote_ver, local_ver):
                try:
                    self._update_signals.update_available.emit(local_ver, remote_ver)
                except RuntimeError:
                    pass

        threading.Thread(target=_worker, name="PerfBoardUpdaterCheck", daemon=True).start()

    def _on_update_available(self, local_ver: str, remote_ver: str):
        self._local_version = local_ver
        self._remote_version = remote_ver
        self.btn_update.setToolTip(
            f"Newer Version Found: v{remote_ver} (Current: v{local_ver})\n"
            f"Click to download and replace files directly in the app folder."
        )
        self.btn_update.setVisible(True)
        log_action("Update available", f"local={local_ver}, remote={remote_ver}")

    def _on_update_button_clicked(self):
        if self._update_in_progress:
            return
        remote_ver = self._remote_version or "latest"
        ans = QMessageBox.question(
            self,
            "Newer Version Found",
            f"A newer version of PerfBoardMaker is available on GitHub!\n\n"
            f"Installed version: v{self._local_version}\n"
            f"Latest version: v{remote_ver}\n\n"
            f"Do you want to download it and replace the old files in the app folder now?\n"
            f"The application will restart automatically after updating.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        if not self._maybe_save():
            return

        self._update_in_progress = True
        self.btn_update.setEnabled(False)
        self._update_cancel_event = threading.Event()

        dlg = QProgressDialog("Downloading update from GitHub...", "Cancel", 0, 100, self)
        dlg.setWindowTitle("Updating PerfBoardMaker")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setValue(0)
        dlg.canceled.connect(self._on_update_download_canceled)
        dlg.show()
        self._update_progress_dlg = dlg

        cancel_ev = self._update_cancel_event

        def _download_worker():
            try:
                def _on_prog(downloaded: int, total: int):
                    try:
                        self._update_signals.download_progress.emit(downloaded, total)
                    except RuntimeError:
                        pass

                staged_root, temp_dir = download_and_stage_update(
                    progress_cb=_on_prog,
                    cancel_event=cancel_ev,
                )
                try:
                    self._update_signals.download_finished.emit(staged_root, temp_dir)
                except RuntimeError:
                    shutil.rmtree(temp_dir, ignore_errors=True)
            except InterruptedError:
                try:
                    self._update_signals.download_failed.emit("__CANCELLED__")
                except RuntimeError:
                    pass
            except Exception as exc:
                try:
                    self._update_signals.download_failed.emit(str(exc))
                except RuntimeError:
                    pass

        threading.Thread(target=_download_worker, name="PerfBoardUpdaterDownload", daemon=True).start()

    def _on_update_download_canceled(self):
        if self._update_cancel_event is not None:
            self._update_cancel_event.set()

    def _on_download_progress(self, downloaded: int, total: int):
        dlg = self._update_progress_dlg
        if dlg is None:
            return
        if total > 0:
            if dlg.maximum() == 0:
                dlg.setRange(0, 100)
            pct = max(0, min(100, int((downloaded * 100) / total)))
            dlg.setValue(pct)
            dlg.setLabelText(
                f"Downloading update from GitHub... {downloaded // 1024} KB / {total // 1024} KB"
            )
        else:
            if dlg.maximum() != 0:
                dlg.setRange(0, 0)
            dlg.setLabelText(f"Downloading update from GitHub... ({downloaded // 1024} KB)")

    def _close_update_progress_dialog(self):
        dlg = self._update_progress_dlg
        if dlg is not None:
            self._update_progress_dlg = None
            dlg.blockSignals(True)
            dlg.close()
            dlg.deleteLater()

    def _on_download_finished(self, staged_repo_root: str, temp_base_dir: str):
        was_canceled = (
            self._update_cancel_event is not None and self._update_cancel_event.is_set()
        )
        self._close_update_progress_dialog()

        if was_canceled:
            shutil.rmtree(temp_base_dir, ignore_errors=True)
            self._update_in_progress = False
            self.btn_update.setEnabled(True)
            return

        log_action("Applying update from GitHub", f"target_ver={self._remote_version}")
        self._save_last_board_theme(self.config.style)
        try:
            self._perform_autosave()
        except Exception:
            pass
        write_no_crash()

        try:
            launch_detached_updater(
                staged_repo_root=staged_repo_root,
                temp_base_dir=temp_base_dir,
                parent_pid=os.getpid(),
                relaunch_app=True,
            )
        except Exception as exc:
            shutil.rmtree(temp_base_dir, ignore_errors=True)
            self._update_in_progress = False
            self.btn_update.setEnabled(True)
            QMessageBox.critical(self, "Update Error", f"Failed to launch updater:\n{exc}")
            return

        self._updating_exit = True
        self.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _on_download_failed(self, err_msg: str):
        self._close_update_progress_dialog()

        self._update_in_progress = False
        self.btn_update.setEnabled(True)
        if err_msg == "__CANCELLED__":
            self.statusBar().showMessage("Update download cancelled.", 3000)
            return
        QMessageBox.warning(
            self,
            "Update Failed",
            f"Could not download the latest version from GitHub:\n\n{err_msg}",
        )

