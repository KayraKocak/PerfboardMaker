"""
Application styling and dark theme stylesheets.
"""

DARK_THEME = """
QMainWindow, QWidget {
    background-color: #1e1f22;
    color: #e0e2e8;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    font-size: 12px;
}

/* Toolbar */
QToolBar {
    background-color: #2b2d31;
    border-bottom: 1px solid #383a40;
    padding: 4px 8px;
    spacing: 6px;
}

QToolButton {
    background-color: transparent;
    color: #dbdee1;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 5px 9px;
    font-weight: 500;
}

QToolButton:hover {
    background-color: #35373c;
    border: 1px solid #4e5058;
}

QToolButton:pressed, QToolButton:checked {
    background-color: #404249;
    border: 1px solid #5865f2;
    color: #ffffff;
}

/* Dock Widgets */
QDockWidget {
    color: #f2f3f5;
    font-weight: bold;
    titlebar-close-icon: url(close.png);
    titlebar-normal-icon: url(undock.png);
}

QDockWidget::title {
    background-color: #2b2d31;
    border-bottom: 1px solid #383a40;
    padding: 6px 10px;
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

/* Panels & Containers */
QScrollArea, QFrame#toolbox_container, QFrame#prop_container {
    background-color: #232428;
    border: none;
}

/* Search and Input Fields */
QLineEdit, QSpinBox, QComboBox {
    background-color: #1e1f22;
    color: #f2f3f5;
    border: 1px solid #383a40;
    border-radius: 4px;
    padding: 5px 8px;
    selection-background-color: #5865f2;
}

QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #5865f2;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
}

QComboBox QAbstractItemView {
    background-color: #2b2d31;
    color: #f2f3f5;
    selection-background-color: #404249;
    border: 1px solid #383a40;
}

/* PushButtons */
QPushButton {
    background-color: #2b2d31;
    color: #f2f3f5;
    border: 1px solid #383a40;
    border-radius: 4px;
    padding: 6px 12px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #35373c;
    border: 1px solid #4e5058;
}

QPushButton:pressed {
    background-color: #404249;
}

QPushButton#primary_btn {
    background-color: #5865f2;
    color: #ffffff;
    border: 1px solid #4752c4;
}

QPushButton#primary_btn:hover {
    background-color: #4752c4;
}

QPushButton#danger_btn {
    background-color: #da373c;
    color: #ffffff;
    border: 1px solid #a1282c;
}

QPushButton#danger_btn:hover {
    background-color: #ba2e33;
}

/* Status Bar */
QStatusBar {
    background-color: #1a1a1e;
    color: #949ba4;
    border-top: 1px solid #2b2d31;
    font-size: 11px;
}

QStatusBar QLabel {
    color: #b5bac1;
    padding: 2px 8px;
}

/* Tree / List */
QTreeWidget, QListWidget, QTableWidget {
    background-color: #232428;
    color: #dbdee1;
    border: none;
    alternate-background-color: #27292d;
}

QHeaderView::section {
    background-color: #1e1f22;
    color: #949ba4;
    border: none;
    border-bottom: 1px solid #383a40;
    padding: 4px 8px;
    font-size: 11px;
    font-weight: 600;
}

/* Scrollbars */
QScrollBar:vertical {
    background-color: #232428;
    width: 10px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background-color: #3b3d44;
    min-height: 20px;
    border-radius: 4px;
    margin: 2px;
}

QScrollBar::handle:vertical:hover {
    background-color: #4e5058;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    background-color: #232428;
    height: 10px;
    margin: 0px;
}

QScrollBar::handle:horizontal {
    background-color: #3b3d44;
    min-width: 20px;
    border-radius: 4px;
    margin: 2px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #4e5058;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* Tooltip */
QToolTip {
    background-color: #18191c;
    color: #f2f3f5;
    border: 1px solid #383a40;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 11px;
}
"""
