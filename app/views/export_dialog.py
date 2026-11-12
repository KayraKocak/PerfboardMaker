"""
Dialog for configuring image export settings (resolution/scale, format, quality, background).
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QComboBox, QSpinBox, QCheckBox, QSlider, QPushButton,
    QDialogButtonBox, QGroupBox,
)
from PyQt6.QtCore import Qt


class ExportImageDialog(QDialog):
    """Lets the user configure size, format, quality, and background before exporting."""

    def __init__(self, base_width: float, base_height: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export Board Image")
        self.setMinimumWidth(380)

        self._base_w = max(1, int(round(base_width)))
        self._base_h = max(1, int(round(base_height)))
        self._aspect = self._base_w / max(1, self._base_h)
        self._updating_dims = False

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # --- Size / Resolution ---
        size_group = QGroupBox("Size & Resolution")
        size_form = QFormLayout(size_group)

        self.combo_scale = QComboBox()
        self.combo_scale.addItems([
            "1x (Native)",
            "2x (High Res)",
            "3x (Very High)",
            "4x (Ultra)",
            "Custom",
        ])
        self.combo_scale.setCurrentIndex(1)  # Default 2x for crisp exports
        size_form.addRow("Scale:", self.combo_scale)

        dims_row = QHBoxLayout()
        self.spin_width = QSpinBox()
        self.spin_width.setRange(64, 16384)
        self.spin_width.setSuffix(" px")

        self.spin_height = QSpinBox()
        self.spin_height.setRange(64, 16384)
        self.spin_height.setSuffix(" px")

        dims_row.addWidget(self.spin_width)
        dims_row.addWidget(QLabel("×"))
        dims_row.addWidget(self.spin_height)
        size_form.addRow("Dimensions:", dims_row)

        self.chk_aspect = QCheckBox("Lock aspect ratio")
        self.chk_aspect.setChecked(True)
        size_form.addRow("", self.chk_aspect)

        layout.addWidget(size_group)

        # --- Format & Quality ---
        fmt_group = QGroupBox("Format & Quality")
        fmt_form = QFormLayout(fmt_group)

        self.combo_format = QComboBox()
        self.combo_format.addItems(["PNG", "JPEG", "WebP"])
        fmt_form.addRow("Format:", self.combo_format)

        qual_row = QHBoxLayout()
        self.slider_quality = QSlider(Qt.Orientation.Horizontal)
        self.slider_quality.setRange(1, 100)
        self.slider_quality.setValue(95)

        self.spin_quality = QSpinBox()
        self.spin_quality.setRange(1, 100)
        self.spin_quality.setValue(95)
        self.spin_quality.setSuffix("%")

        qual_row.addWidget(self.slider_quality, 1)
        qual_row.addWidget(self.spin_quality)
        fmt_form.addRow("Quality:", qual_row)

        self.lbl_quality_note = QLabel("PNG is lossless.")
        self.lbl_quality_note.setStyleSheet("color: #9aa0a6; font-size: 11px;")
        fmt_form.addRow("", self.lbl_quality_note)

        self.combo_bg = QComboBox()
        self.combo_bg.addItems(["Dark (#18191C)", "White (#FFFFFF)", "Transparent"])
        fmt_form.addRow("Background:", self.combo_bg)

        layout.addWidget(fmt_group)

        # --- Buttons ---
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Export...")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Signals
        self.combo_scale.currentIndexChanged.connect(self._on_scale_changed)
        self.spin_width.valueChanged.connect(self._on_width_changed)
        self.spin_height.valueChanged.connect(self._on_height_changed)
        self.combo_format.currentIndexChanged.connect(self._on_format_changed)
        self.slider_quality.valueChanged.connect(self.spin_quality.setValue)
        self.spin_quality.valueChanged.connect(self.slider_quality.setValue)

        self._apply_scale_preset(1)
        self._on_format_changed()

    def _apply_scale_preset(self, index: int):
        factors = {0: 1, 1: 2, 2: 3, 3: 4}
        if index not in factors:
            return
        factor = factors[index]
        self._updating_dims = True
        try:
            self.spin_width.setValue(min(16384, self._base_w * factor))
            self.spin_height.setValue(min(16384, self._base_h * factor))
        finally:
            self._updating_dims = False

    def _on_scale_changed(self, index: int):
        self._apply_scale_preset(index)

    def _on_width_changed(self, value: int):
        if self._updating_dims:
            return
        self._updating_dims = True
        try:
            if self.chk_aspect.isChecked():
                self.spin_height.setValue(max(64, min(16384, int(round(value / self._aspect)))))
            self.combo_scale.setCurrentIndex(4)  # Custom
        finally:
            self._updating_dims = False

    def _on_height_changed(self, value: int):
        if self._updating_dims:
            return
        self._updating_dims = True
        try:
            if self.chk_aspect.isChecked():
                self.spin_width.setValue(max(64, min(16384, int(round(value * self._aspect)))))
            self.combo_scale.setCurrentIndex(4)  # Custom
        finally:
            self._updating_dims = False

    def _on_format_changed(self):
        fmt = self.combo_format.currentText()
        is_png = (fmt == "PNG")
        self.slider_quality.setEnabled(not is_png)
        self.spin_quality.setEnabled(not is_png)
        if is_png:
            self.lbl_quality_note.setText("PNG is lossless.")
        else:
            self.lbl_quality_note.setText(f"{fmt} compression quality (higher = sharper, larger file).")

        # JPEG does not support alpha transparency
        trans_idx = self.combo_bg.findText("Transparent")
        if trans_idx >= 0:
            model_item = self.combo_bg.model().item(trans_idx)
            if fmt == "JPEG":
                model_item.setEnabled(False)
                if self.combo_bg.currentIndex() == trans_idx:
                    self.combo_bg.setCurrentIndex(0)
            else:
                model_item.setEnabled(True)

    def get_settings(self) -> dict:
        """Returns the chosen export settings dictionary."""
        bg_idx = self.combo_bg.currentIndex()
        bg_mode = ("dark", "white", "transparent")[bg_idx]
        return {
            "width": self.spin_width.value(),
            "height": self.spin_height.value(),
            "format": self.combo_format.currentText(),
            "quality": self.spin_quality.value(),
            "background": bg_mode,
        }
