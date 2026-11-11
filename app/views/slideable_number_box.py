"""
Slideable numeric input widget for PerfBoardMaker.
Inspired by CAD/3D software (Blender, Unreal Engine):
- Horizontal dragging scrubs the value up and down in real-time.
- Mouse cursor stays in place and is hidden during drag.
- Single click without dragging opens manual text entry.
"""
from PyQt6.QtWidgets import (
    QWidget, QLabel, QLineEdit, QStackedWidget, QVBoxLayout, QApplication
)
from PyQt6.QtCore import Qt, QPoint, pyqtSignal
from PyQt6.QtGui import QCursor, QMouseEvent, QKeyEvent, QFocusEvent


class _CustomLineEdit(QLineEdit):
    """Internal line edit that intercepts Escape and focus loss."""
    escape_pressed = pyqtSignal()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.escape_pressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class SlideableNumberBox(QWidget):
    """
    A compact numeric input that supports:
    1. Click-and-drag horizontal scrubbing with hidden stationary cursor.
    2. Single click manual numeric typing.
    3. Direct valueChanged emission on every step change.
    """
    valueChanged = pyqtSignal(int)

    def __init__(
        self,
        value: int = 10,
        min_val: int = 0,
        max_val: int = 1000,
        suffix: str = "",
        parent=None
    ):
        super().__init__(parent)
        self._value = int(value)
        self._min_val = int(min_val)
        self._max_val = int(max_val)
        self._suffix = suffix

        # Scrub drag state
        self._press_pos = QPoint()
        self._start_val = self._value
        self._is_dragging = False
        self._accumulated_dx = 0.0
        self._ignore_warp = False

        self.setFixedHeight(28)
        self.setMinimumWidth(65)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.stack = QStackedWidget(self)
        layout.addWidget(self.stack)

        # Page 0: Label Display
        self.lbl_display = QLabel(self._format_text(self._value), self)
        self.lbl_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_display.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.lbl_display.setStyleSheet("""
            QLabel {
                background-color: #1e1f22;
                color: #f2f3f5;
                font-weight: 700;
                font-size: 12px;
                border: 1px solid #3f4147;
                border-radius: 4px;
                padding: 2px 6px;
            }
            QLabel:hover {
                border: 1px solid #5865f2;
                background-color: #2b2d31;
                color: #5865f2;
            }
        """)
        self.stack.addWidget(self.lbl_display)

        # Page 1: LineEdit Manual Entry
        self.line_edit = _CustomLineEdit(self)
        self.line_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.line_edit.setStyleSheet("""
            QLineEdit {
                background-color: #111214;
                color: #00e6ff;
                font-weight: 700;
                font-size: 12px;
                border: 1px solid #00e6ff;
                border-radius: 4px;
                padding: 2px 4px;
                selection-background-color: #5865f2;
            }
        """)
        self.line_edit.returnPressed.connect(self._commit_text_edit)
        self.line_edit.editingFinished.connect(self._commit_text_edit)
        self.line_edit.escape_pressed.connect(self._cancel_text_edit)
        self.stack.addWidget(self.line_edit)

        self.stack.setCurrentIndex(0)

    def _format_text(self, val: int) -> str:
        if self._suffix:
            return f"{val} {self._suffix}"
        return str(val)

    def value(self) -> int:
        return self._value

    def setValue(self, val: int):
        val = max(self._min_val, min(self._max_val, int(val)))
        if self._value != val:
            self._value = val
            self.lbl_display.setText(self._format_text(self._value))
            self.line_edit.setText(str(self._value))
            self.valueChanged.emit(self._value)

    def setRange(self, min_val: int, max_val: int):
        self._min_val = int(min_val)
        self._max_val = int(max_val)
        if self._value < self._min_val or self._value > self._max_val:
            self.setValue(self._value)

    # --- Mouse Events for Scrubbing & Editing ---

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.stack.currentIndex() == 0:
                self._press_pos = event.globalPosition().toPoint()
                self._last_cursor_pos = event.globalPosition().toPoint()
                self._start_val = self._value
                self._is_dragging = False
                self._cursor_hidden = False
                self._accumulated_dx = 0.0
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() & Qt.MouseButton.LeftButton:
            if self.stack.currentIndex() == 0:
                curr_pos = event.globalPosition().toPoint()
                dx = curr_pos.x() - self._last_cursor_pos.x()
                if dx == 0:
                    event.accept()
                    return

                self._last_cursor_pos = curr_pos

                self._accumulated_dx += dx
                if not self._is_dragging:
                    if abs(self._accumulated_dx) >= 3:
                        self._is_dragging = True
                        if not self._cursor_hidden:
                            self._cursor_hidden = True
                            QApplication.setOverrideCursor(Qt.CursorShape.BlankCursor)

                if self._is_dragging:
                    # For every 15px horizontal mouse movement, increment/decrement 1 unit
                    step = int(self._accumulated_dx / 15.0)
                    new_val = max(self._min_val, min(self._max_val, self._start_val + step))
                    if new_val != self._value:
                        self.setValue(new_val)

                    # Reset cursor to mouseDown location every few pixels (>= 5px)
                    # This prevents the invisible cursor from hitting window/monitor boundaries
                    if abs(curr_pos.x() - self._press_pos.x()) >= 5:
                        self._last_cursor_pos = self._press_pos
                        QCursor.setPos(self._press_pos)

                    event.accept()
                    return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.stack.currentIndex() == 0:
                if self._is_dragging:
                    self._is_dragging = False
                    if self._cursor_hidden:
                        self._cursor_hidden = False
                        while QApplication.overrideCursor() is not None:
                            QApplication.restoreOverrideCursor()
                    QCursor.setPos(self._press_pos)
                else:
                    # User clicked without dragging -> activate manual typing
                    self._start_text_edit()
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def hideEvent(self, event):
        self._restore_cursor()
        super().hideEvent(event)

    def changeEvent(self, event):
        if getattr(self, "_cursor_hidden", False) and not self.isActiveWindow():
            self._restore_cursor()
        super().changeEvent(event)

    def _restore_cursor(self):
        if getattr(self, "_cursor_hidden", False):
            self._cursor_hidden = False
            while QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()

    def __del__(self):
        try:
            while QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()
        except Exception:
            pass

    def _start_text_edit(self):
        self.line_edit.setText(str(self._value))
        self.stack.setCurrentIndex(1)
        self.line_edit.selectAll()
        self.line_edit.setFocus()

    def _commit_text_edit(self):
        if self.stack.currentIndex() == 1:
            txt = self.line_edit.text().strip()
            try:
                val = int(txt)
                val = max(self._min_val, min(self._max_val, val))
                if val != self._value:
                    self.setValue(val)
            except ValueError:
                pass
            self.lbl_display.setText(self._format_text(self._value))
            self.stack.setCurrentIndex(0)

    def _cancel_text_edit(self):
        if self.stack.currentIndex() == 1:
            self.line_edit.setText(str(self._value))
            self.stack.setCurrentIndex(0)
