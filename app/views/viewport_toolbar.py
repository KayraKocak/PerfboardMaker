"""
Viewport toolbar positioned directly above the perfboard canvas.
Provides Select (1), Solder (2), Jumper (3) modes and active jumper color palette.
"""
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QLabel, QButtonGroup, QFrame, QToolButton, QSizePolicy
)
from PyQt6.QtGui import QColor, QFont, QCursor
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from app.models.jumper import JUMPER_COLORS, DEFAULT_JUMPER_COLOR

class ColorSwatchButton(QPushButton):
    def __init__(self, color_hex: str, name: str, parent=None):
        super().__init__(parent)
        self.color_hex = color_hex
        self.color_name = name
        self.setFixedSize(18, 18)
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
                border-radius: 9px;
            }}
            QPushButton:hover {{
                border: 2px solid #5865f2;
            }}
        """)

    def setChecked(self, checked: bool):
        super().setChecked(checked)
        self._update_style(checked)


class ViewportToolbar(QFrame):
    mode_changed = pyqtSignal(str)          # "select", "solder", "jumper"
    jumper_color_changed = pyqtSignal(str)  # hex color

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_mode = "select"
        self.active_jumper_color = DEFAULT_JUMPER_COLOR

        self.setObjectName("viewport_toolbar")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(34)
        self.setStyleSheet("""
            QFrame#viewport_toolbar {
                background-color: #232428;
                border-bottom: 1px solid #35373c;
                padding: 1px 6px;
            }
            QPushButton.mode-btn {
                background-color: #2b2d31;
                color: #dbdee1;
                border: 1px solid #383a40;
                border-radius: 4px;
                padding: 3px 10px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton.mode-btn:hover {
                background-color: #35373c;
                border: 1px solid #4e5058;
            }
            QPushButton.mode-btn:checked {
                background-color: #5865f2;
                color: #ffffff;
                border: 1px solid #4752c4;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(8)

        # Mode Button Group
        self.btn_group = QButtonGroup(self)
        self.btn_group.setExclusive(True)

        self.btn_select = QPushButton("🖱️ Select (1)")
        self.btn_select.setCheckable(True)
        self.btn_select.setChecked(True)
        self.btn_select.setProperty("class", "mode-btn")
        self.btn_select.setToolTip("Select and drag components or jumper wires (Hotkey: 1)")
        self.btn_select.clicked.connect(lambda: self.set_mode("select"))
        self.btn_group.addButton(self.btn_select)
        layout.addWidget(self.btn_select)

        self.btn_solder = QPushButton("⚡ Solder (2)")
        self.btn_solder.setCheckable(True)
        self.btn_solder.setProperty("class", "mode-btn")
        self.btn_solder.setToolTip("Draw solder bridges on the back side (Hotkey: 2)")
        self.btn_solder.clicked.connect(lambda: self.set_mode("solder"))
        self.btn_group.addButton(self.btn_solder)
        layout.addWidget(self.btn_solder)

        self.btn_jumper = QPushButton("🔌 Jumper (3)")
        self.btn_jumper.setCheckable(True)
        self.btn_jumper.setProperty("class", "mode-btn")
        self.btn_jumper.setToolTip("Draw jumper wires on active view side (Hotkey: 3)")
        self.btn_jumper.clicked.connect(lambda: self.set_mode("jumper"))
        self.btn_group.addButton(self.btn_jumper)
        layout.addWidget(self.btn_jumper)

        self.btn_autoconnect = QPushButton("🔗 AutoConnect (4)")
        self.btn_autoconnect.setCheckable(True)
        self.btn_autoconnect.setProperty("class", "mode-btn")
        self.btn_autoconnect.setToolTip("AutoConnect selected pins, traces, or jumper ends (Hotkey: 4)")
        self.btn_autoconnect.clicked.connect(lambda: self.set_mode("autoconnect"))
        self.btn_group.addButton(self.btn_autoconnect)
        layout.addWidget(self.btn_autoconnect)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color: #383a40;")
        layout.addWidget(sep)

        # Jumper Colors Swatches Container
        self.swatch_container = QWidget()
        swatch_layout = QHBoxLayout(self.swatch_container)
        swatch_layout.setContentsMargins(0, 0, 0, 0)
        swatch_layout.setSpacing(4)

        swatch_lbl = QLabel("Wire Color:")
        swatch_lbl.setStyleSheet("color: #949ba4; font-size: 11px; font-weight: 500;")
        swatch_layout.addWidget(swatch_lbl)

        self.swatch_group = QButtonGroup(self)
        self.swatch_group.setExclusive(True)

        for col_hex, col_name in JUMPER_COLORS[:8]: # Show first 8 primary hookup colors
            btn = ColorSwatchButton(col_hex, col_name)
            if col_hex == self.active_jumper_color:
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, h=col_hex: self._on_swatch_clicked(h))
            self.swatch_group.addButton(btn)
            swatch_layout.addWidget(btn)

        layout.addWidget(self.swatch_container)

        # Mode Hint Label (Right aligned)
        layout.addStretch()
        self.lbl_hint = QLabel("Select components or drag to reposition")
        self.lbl_hint.setStyleSheet("color: #949ba4; font-size: 11px;")
        layout.addWidget(self.lbl_hint)

    def set_mode(self, mode: str):
        if mode not in ("select", "solder", "jumper", "autoconnect"):
            return
        self.current_mode = mode

        if mode == "select":
            self.btn_select.setChecked(True)
            self.lbl_hint.setText("Select components / jumpers. Drag to reposition. Press 'R' to rotate.")
            self.swatch_container.setVisible(True)
        elif mode == "solder":
            self.btn_solder.setChecked(True)
            self.lbl_hint.setText("⚡ Solder Mode: Drag between holes on back side. Hold Shift for straight lines.")
            self.swatch_container.setVisible(False)
        elif mode == "jumper":
            self.btn_jumper.setChecked(True)
            self.lbl_hint.setText("🔌 Jumper Mode: Drag from hole to hole. Active side: current view. Hold Shift for straight lines.")
            self.swatch_container.setVisible(True)
        elif mode == "autoconnect":
            self.btn_autoconnect.setChecked(True)
            self.lbl_hint.setText("🔗 AutoConnect Mode: Select pins, traces, or jumper ends (Shift for multi). Press Enter to connect.")
            self.swatch_container.setVisible(False)

        self.mode_changed.emit(mode)

    def _on_swatch_clicked(self, hex_color: str):
        self.active_jumper_color = hex_color
        # Update swatches checked
        for btn in self.swatch_group.buttons():
            if isinstance(btn, ColorSwatchButton):
                btn.setChecked(btn.color_hex == hex_color)
        self.jumper_color_changed.emit(hex_color)

    def set_active_jumper_color(self, hex_color: str):
        self.active_jumper_color = hex_color
        for btn in self.swatch_group.buttons():
            if isinstance(btn, ColorSwatchButton):
                btn.setChecked(btn.color_hex.lower() == hex_color.lower())
