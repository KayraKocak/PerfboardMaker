"""
GitHub release/version checker and in-place self-updater for PerfBoardMaker.
Checks app/native/version.txt against KayraKocak/PerfboardMaker on GitHub.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from decimal import Decimal
from typing import Callable

GITHUB_OWNER = "KayraKocak"
GITHUB_REPO = "PerfboardMaker"
GITHUB_BRANCH = "main"

APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCAL_VERSION_PATH = os.path.join(APP_ROOT, "app", "native", "version.txt")

REMOTE_VERSION_URL = (
    f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/"
    f"{GITHUB_BRANCH}/app/native/version.txt"
)
REMOTE_ZIP_URL = (
    f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/archive/refs/heads/{GITHUB_BRANCH}.zip"
)

_VERSION_RE = re.compile(r"^\s*v?(\d+(?:\.\d+)*)\s*$", re.IGNORECASE)

# Directories/files in APP_ROOT that belong to the local environment/user and must not be wiped.
PRESERVED_ROOT_NAMES = frozenset({
    ".git",
    "autosaves",
    "logs",
    ".venv",
    "venv",
    "env",
    "ENV",
    "github_push.bat",
})


def normalize_version_str(raw: str | None) -> str | None:
    """Validates and normalizes a version string like '0.1', '2.72', 'v12.2' -> '12.2'."""
    if not raw:
        return None
    cleaned = raw.lstrip("\ufeff").strip()
    m = _VERSION_RE.match(cleaned)
    if not m:
        return None
    return m.group(1)


def parse_version(version_str: str | None) -> tuple[int, Decimal, tuple[int, ...]]:
    """
    Parses a dotted numeric version string as (major, Decimal('0.<minor>'), extra_ints)
    so decimal-style versions like '0.01' < '0.1' < '2.72' < '12.2' compare accurately.
    """
    norm = normalize_version_str(version_str)
    if not norm:
        return (0, Decimal("0"), ())
    parts = norm.split(".")
    major = int(parts[0])
    minor = Decimal(f"0.{parts[1]}") if len(parts) > 1 else Decimal("0")
    extra = [int(p) for p in parts[2:]]
    while extra and extra[-1] == 0:
        extra.pop()
    return (major, minor, tuple(extra))


def is_newer_version(remote_ver: str | None, local_ver: str | None) -> bool:
    """Returns True if remote_ver represents a strictly newer version than local_ver."""
    if not normalize_version_str(remote_ver):
        return False
    return parse_version(remote_ver) > parse_version(local_ver)


def get_local_version(version_path: str = LOCAL_VERSION_PATH) -> str:
    """Reads the locally installed version from app/native/version.txt, defaulting to '0.0'."""
    try:
        with open(version_path, "r", encoding="utf-8-sig") as f:
            norm = normalize_version_str(f.read())
            return norm or "0.0"
    except OSError:
        return "0.0"


def fetch_remote_version(
    url: str = REMOTE_VERSION_URL,
    timeout: float = 6.0,
) -> str | None:
    """Fetches app/native/version.txt from GitHub, bypassing CDN caches."""
    sep = "&" if "?" in url else "?"
    cache_busted_url = f"{url}{sep}t={int(time.time())}"
    req = urllib.request.Request(
        cache_busted_url,
        headers={
            "User-Agent": "PerfBoardMaker-Updater",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if getattr(resp, "status", 200) != 200:
                return None
            raw = resp.read(256).decode("utf-8-sig", errors="replace")
            return normalize_version_str(raw)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


def download_and_stage_update(
    zip_url: str = REMOTE_ZIP_URL,
    progress_cb: Callable[[int, int], None] | None = None,
    cancel_event: threading.Event | None = None,
    timeout: float = 45.0,
) -> tuple[str, str]:
    """
    Downloads the repository ZIP archive into a temporary directory and extracts it.
    Returns (staged_repo_root, temp_base_dir).
    Raises RuntimeError / InterruptedError on failure or cancellation.
    """
    temp_base_dir = tempfile.mkdtemp(prefix="perfboard_update_")
    zip_path = os.path.join(temp_base_dir, "update.zip")
    extract_dir = os.path.join(temp_base_dir, "extracted")
    os.makedirs(extract_dir, exist_ok=True)

    try:
        req = urllib.request.Request(
            zip_url,
            headers={
                "User-Agent": "PerfBoardMaker-Updater",
                "Cache-Control": "no-cache",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if getattr(resp, "status", 200) != 200:
                raise RuntimeError(f"GitHub returned HTTP {getattr(resp, 'status', 'error')}")
            total_header = resp.headers.get("Content-Length")
            total_bytes = int(total_header) if (total_header and total_header.isdigit()) else 0
            downloaded = 0
            with open(zip_path, "wb") as out_f:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise InterruptedError("Update download cancelled.")
                    chunk = resp.read(32768)
                    if not chunk:
                        break
                    out_f.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb is not None:
                        progress_cb(downloaded, total_bytes)

        extract_abs = os.path.abspath(extract_dir)
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.infolist():
                target_path = os.path.abspath(os.path.join(extract_abs, member.filename))
                if os.path.commonpath([extract_abs, target_path]) != extract_abs:
                    raise RuntimeError(f"Unsafe path in update archive: {member.filename}")
            zf.extractall(extract_abs)

        entries = [
            os.path.join(extract_abs, name)
            for name in os.listdir(extract_abs)
            if os.path.isdir(os.path.join(extract_abs, name))
        ]
        if len(entries) == 1:
            staged_repo_root = entries[0]
        else:
            staged_repo_root = extract_abs

        return staged_repo_root, temp_base_dir
    except Exception:
        shutil.rmtree(temp_base_dir, ignore_errors=True)
        raise


def sync_update_files(
    src_root: str,
    dst_root: str = APP_ROOT,
    preserve: frozenset[str] = PRESERVED_ROOT_NAMES,
) -> list[str]:
    """
    Copies updated files from src_root into dst_root, overwriting existing files while
    preserving local runtime directories and excluded scripts.
    Returns a list of destination file paths that failed with PermissionError (if any).
    """
    locked_files: list[str] = []
    src_abs = os.path.abspath(src_root)
    dst_abs = os.path.abspath(dst_root)

    for root, dirs, files in os.walk(src_abs):
        rel_dir = os.path.relpath(root, src_abs)
        is_root = rel_dir == "."

        dirs[:] = [
            d for d in dirs
            if d != "__pycache__" and not (is_root and d in preserve)
        ]

        target_dir = dst_abs if is_root else os.path.join(dst_abs, rel_dir)
        os.makedirs(target_dir, exist_ok=True)

        for fname in files:
            if fname.endswith((".pyc", ".pyo")):
                continue
            if is_root and fname in preserve:
                continue
            src_file = os.path.join(root, fname)
            dst_file = os.path.join(target_dir, fname)
            try:
                shutil.copy2(src_file, dst_file)
            except PermissionError:
                locked_files.append(dst_file)
    return locked_files


def launch_detached_updater(
    staged_repo_root: str,
    temp_base_dir: str,
    app_root: str = APP_ROOT,
    parent_pid: int | None = None,
    relaunch_app: bool = True,
) -> None:
    """
    Spawns a standalone detached helper script in temp_base_dir that waits for the
    current PerfBoardMaker process to exit (unlocking router_core.dll and assets),
    replaces files directly in app_root, cleans up staging temp files, and relaunches.
    """
    if parent_pid is None:
        parent_pid = os.getpid()

    helper_script = os.path.join(temp_base_dir, "_perfboard_apply_update.py")
    log_path = os.path.join(app_root, "logs", "updater.log")
    python_exe = sys.executable

    if getattr(sys, "frozen", False):
        relaunch_cmd = [sys.executable]
    else:
        relaunch_cmd = [python_exe, os.path.join(app_root, "run.py")]

    script_body = f'''import ctypes
import os
import shutil
import subprocess
import sys
import time

SRC_ROOT = {staged_repo_root!r}
DST_ROOT = {app_root!r}
TEMP_BASE = {temp_base_dir!r}
LOG_PATH = {log_path!r}
PARENT_PID = {int(parent_pid)}
RELAUNCH = {bool(relaunch_app)}
RELAUNCH_CMD = {relaunch_cmd!r}
PRESERVE = {sorted(PRESERVED_ROOT_NAMES)!r}


def _wait_for_pid_exit(pid: int, timeout_sec: float = 20.0) -> None:
    deadline = time.time() + timeout_sec
    if sys.platform == "win32":
        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if handle:
            try:
                ctypes.windll.kernel32.WaitForSingleObject(handle, int(timeout_sec * 1000))
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        time.sleep(0.25)
        return

    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            break
        time.sleep(0.15)
    time.sleep(0.25)


def _copy_all() -> None:
    preserve_set = set(PRESERVE)
    for root, dirs, files in os.walk(SRC_ROOT):
        rel_dir = os.path.relpath(root, SRC_ROOT)
        is_root = rel_dir == "."
        dirs[:] = [d for d in dirs if d != "__pycache__" and not (is_root and d in preserve_set)]
        target_dir = DST_ROOT if is_root else os.path.join(DST_ROOT, rel_dir)
        os.makedirs(target_dir, exist_ok=True)
        for fname in files:
            if fname.endswith((".pyc", ".pyo")):
                continue
            if is_root and fname in preserve_set:
                continue
            src_f = os.path.join(root, fname)
            dst_f = os.path.join(target_dir, fname)
            for attempt in range(8):
                try:
                    shutil.copy2(src_f, dst_f)
                    break
                except PermissionError:
                    if attempt == 7:
                        raise
                    time.sleep(0.25)


def main() -> None:
    try:
        _wait_for_pid_exit(PARENT_PID)
        _copy_all()
    except Exception as exc:
        try:
            os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
            with open(LOG_PATH, "a", encoding="utf-8") as lf:
                lf.write(f"[{{time.strftime('%Y-%m-%d %H:%M:%S')}}] Update error: {{exc}}\\n")
        except Exception:
            pass
    finally:
        try:
            # Remove extracted folder, keep helper cleanup best-effort
            shutil.rmtree(os.path.dirname(SRC_ROOT), ignore_errors=True)
        except Exception:
            pass
        zip_file = os.path.join(TEMP_BASE, "update.zip")
        if os.path.exists(zip_file):
            try:
                os.remove(zip_file)
            except Exception:
                pass

    if RELAUNCH:
        try:
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            subprocess.Popen(
                RELAUNCH_CMD,
                cwd=DST_ROOT,
                close_fds=True,
                creationflags=creation_flags,
            )
        except Exception as exc:
            try:
                os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
                with open(LOG_PATH, "a", encoding="utf-8") as lf:
                    lf.write(f"[{{time.strftime('%Y-%m-%d %H:%M:%S')}}] Relaunch error: {{exc}}\\n")
            except Exception:
                pass


if __name__ == "__main__":
    main()
'''
    with open(helper_script, "w", encoding="utf-8") as f:
        f.write(script_body)

    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
        )
    subprocess.Popen(
        [python_exe, helper_script],
        cwd=temp_base_dir,
        close_fds=True,
        creationflags=creation_flags,
    )
