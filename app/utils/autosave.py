"""
Autosave snapshot manager for PerfBoardMaker.
Handles periodic snapshots (every 10 seconds) to the 'autosaves' directory.
Format: autosave_(projectname)_(date: dd-mm-yyyy)_(time: hh-mm).pbrd
"""
import os
import re
import json
import glob
from datetime import datetime
from typing import Any

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AUTOSAVES_DIR = os.path.join(ROOT_DIR, "autosaves")

def get_autosaves_dir() -> str:
    """Returns path to the autosaves folder, creating it if it does not exist."""
    os.makedirs(AUTOSAVES_DIR, exist_ok=True)
    return AUTOSAVES_DIR

def sanitize_filename(name: str) -> str:
    """Sanitizes project name for use in file names across Windows and POSIX."""
    if not name or not name.strip():
        return "Untitled"
    # Replace characters invalid in file paths with underscore
    clean = re.sub(r'[\\/*?:"<>|]', '_', name.strip())
    # Clean up double underscores or leading/trailing spaces/dots
    clean = clean.strip(". ")
    return clean if clean else "Untitled"

def generate_autosave_filename(project_name: str, dt: datetime | None = None) -> str:
    """
    Generates filename adhering to:
    autosave_(projectname)_(date: dd-mm-yyyy)_(time: hh-mm).pbrd
    """
    safe_name = sanitize_filename(project_name)
    if dt is None:
        dt = datetime.now()
    date_str = dt.strftime("%d-%m-%Y")
    time_str = dt.strftime("%H-%M")
    return f"autosave_{safe_name}_{date_str}_{time_str}.pbrd"

def save_autosave_snapshot(
    state_data: dict[str, Any],
    project_name: str,
    original_path: str | None = None
) -> str:
    """
    Saves a snapshot of the current state into the autosaves folder.
    Returns the absolute path to the saved autosave file.
    """
    folder = get_autosaves_dir()
    filename = generate_autosave_filename(project_name)
    filepath = os.path.join(folder, filename)

    # Attach metadata for session recovery
    payload = dict(state_data)
    payload["meta"] = {
        "project_name": sanitize_filename(project_name),
        "original_path": original_path,
        "autosave_time": datetime.now().isoformat(),
        "is_autosave": True,
    }

    # Save to file
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    return filepath

def get_latest_autosave_file() -> str | None:
    """
    Finds and returns the path to the most recent autosave file in the autosaves directory.
    Returns None if no autosaves are found.
    """
    folder = get_autosaves_dir()
    pattern = os.path.join(folder, "autosave_*.pbrd")
    files = glob.glob(pattern)
    if not files:
        return None

    # Sort by modification time, newest first
    files.sort(key=os.path.getmtime, reverse=True)
    return files[0]

def get_all_autosave_files() -> list[str]:
    """Returns all autosave file paths sorted from newest to oldest."""
    folder = get_autosaves_dir()
    pattern = os.path.join(folder, "autosave_*.pbrd")
    files = glob.glob(pattern)
    files.sort(key=os.path.getmtime, reverse=True)
    return files
