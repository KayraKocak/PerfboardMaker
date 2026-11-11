"""
Entry point for PerfBoardMaker.
"""
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from app.utils.logger import init_crash_handler, log_action
from app.views.main_window import MainWindow, get_app_icon


def main():
    init_crash_handler()
    log_action("App launched")
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PerfBoardMaker.App")
        except Exception:
            pass
    # Enable high DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("PerfBoardMaker")
    app.setOrganizationName("PerfBoardMaker")
    app_icon = get_app_icon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    window = MainWindow()
    window.show()

    from app.utils.logger import write_no_crash
    app.aboutToQuit.connect(write_no_crash)

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
