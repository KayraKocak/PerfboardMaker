"""
Centralized logging, keypress tracking, and crash handler for PerfBoardMaker.
Automatically logs:
- C++ segmentation faults / access violations via faulthandler to crash.log
- Unhandled Python exceptions to crash.log and app.log
- Key presses, user actions, component selection, rotation, and deletion to keypress.log
"""
import sys
import os
import logging
import faulthandler
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

APP_LOG_PATH = os.path.join(LOG_DIR, "app.log")
CRASH_LOG_PATH = os.path.join(LOG_DIR, "crash.log")
KEYPRESS_LOG_PATH = os.path.join(LOG_DIR, "keypress.log")

# Setup python logger
logger = logging.getLogger("PerfBoardMaker")
logger.setLevel(logging.DEBUG)

# File handler
fh = logging.FileHandler(APP_LOG_PATH, mode="a", encoding="utf-8")
fh.setLevel(logging.DEBUG)
formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
fh.setFormatter(formatter)
logger.addHandler(fh)

# Keypress log file
_key_file = open(KEYPRESS_LOG_PATH, "a", encoding="utf-8", buffering=1)
_crash_file = None

def get_crash_file():
    global _crash_file
    if _crash_file is None or _crash_file.closed:
        _crash_file = open(CRASH_LOG_PATH, "a+", encoding="utf-8", buffering=1)
    return _crash_file

def check_crash_log() -> tuple[str, str]:
    """
    Checks the crash log content at startup.
    Returns (status, content):
    - status == "clean": content.strip() == "NoCrash"
    - status == "empty": content.strip() == ""
    - status == "crash": content.strip() is non-empty and != "NoCrash"
    """
    if not os.path.isfile(CRASH_LOG_PATH):
        return ("empty", "")
    try:
        with open(CRASH_LOG_PATH, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if content == "NoCrash":
            return ("clean", content)
        elif not content:
            return ("empty", "")
        else:
            return ("crash", content)
    except Exception as e:
        logger.error(f"Error checking crash log: {e}")
        return ("empty", "")

def clear_crash_log():
    """Deletes everything in the crash log so it is empty during the session."""
    global _crash_file
    try:
        f = get_crash_file()
        f.seek(0)
        f.truncate(0)
        f.flush()
        logger.info("Crash log cleared.")
    except Exception as e:
        logger.error(f"Error clearing crash log: {e}")

def write_no_crash():
    """Writes 'NoCrash' to crash.log on normal application closure."""
    global _crash_file
    try:
        try:
            faulthandler.disable()
        except Exception:
            pass
        f = get_crash_file()
        f.seek(0)
        f.truncate(0)
        f.write("NoCrash")
        f.flush()
        logger.info("Normal shutdown: NoCrash written to crash log.")
    except Exception as e:
        logger.error(f"Error writing NoCrash: {e}")

def init_crash_handler():
    """Initializes faulthandler and sys.excepthook to capture crashes and unhandled exceptions."""
    f = get_crash_file()
    try:
        faulthandler.enable(file=f, all_threads=True)
    except Exception as e:
        logger.error(f"Failed to enable faulthandler: {e}")

    def exception_hook(exctype, value, tb):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg = f"[{timestamp}] UNHANDLED EXCEPTION:\n"
        import traceback
        tb_lines = "".join(traceback.format_exception(exctype, value, tb))
        try:
            f.write(f"\n{'='*60}\n{msg}{tb_lines}{'='*60}\n")
            f.flush()
        except Exception:
            pass
        logger.critical(f"Unhandled exception:\n{tb_lines}")
        sys.__excepthook__(exctype, value, tb)

    sys.excepthook = exception_hook
    logger.info("Crash handler and exception hooks initialized.")

def log_keypress(key_name: str, modifiers: str = "", context: str = ""):
    """Logs a keypress event with timestamp and active context."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    mod_str = f" [{modifiers}]" if modifiers else ""
    ctx_str = f" ({context})" if context else ""
    line = f"[{timestamp}] KEY: {key_name}{mod_str}{ctx_str}\n"
    _key_file.write(line)
    _key_file.flush()

def log_action(action: str, details: str = ""):
    """Logs an application event or user action."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    det_str = f" - {details}" if details else ""
    line = f"[{timestamp}] ACTION: {action}{det_str}\n"
    _key_file.write(line)
    _key_file.flush()
    logger.info(f"{action}{det_str}")
