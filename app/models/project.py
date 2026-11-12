"""
Project serialization and deserialization for PerfBoardMaker (.pbrd files).
Handles saving and loading the complete perfboard state including:
- Board dimensions, theme, and view side
- Placed components with positions, rotations, labels, and custom properties
- Solder bridge traces and connectivity
- Jumper wires with endpoints, bend waypoints, colors, and sides
"""
import json
import os
from typing import Any
from app.models.board import BoardConfig
from app.models.placed_component import PlacedComponent
from app.models.solder import SolderManager, SolderTrace
from app.models.jumper import JumperWire

PROJECT_FILE_EXTENSION = ".pbrd"
PROJECT_FILE_FILTER = "PerfBoard Project (*.pbrd);;All Files (*.*)"
FORMAT_IDENTIFIER = "PerfBoardMaker"
FORMAT_VERSION = "1.0"

def serialize_state(
    config: BoardConfig,
    components: list[PlacedComponent],
    solder_mgr: SolderManager,
    jumpers: list[JumperWire]
) -> dict[str, Any]:
    """Serializes the current board state into a plain Python dictionary."""
    return {
        "format": FORMAT_IDENTIFIER,
        "version": FORMAT_VERSION,
        "board": {
            "cols": config.cols,
            "rows": config.rows,
            "pitch_px": config.pitch_px,
            "style": config.style,
            "view_side": config.view_side,
            "cutouts": [
                {
                    "shape": c.shape,
                    "x": c.x,
                    "y": c.y,
                    "w": c.w,
                    "h": c.h,
                    "corner_radius": c.corner_radius,
                    "rotation": c.rotation,
                    "inverted": c.inverted,
                    "vertices": [list(v) for v in c.vertices],
                    "uid": c.uid,
                }
                for c in getattr(config, "cutouts", [])
            ],
        },
        "components": [
            {
                "type_id": c.type_id,
                "grid_x": c.grid_x,
                "grid_y": c.grid_y,
                "rotation": c.rotation,
                "label": c.label,
                "custom_props": dict(c.custom_props),
                "uid": c.uid,
            }
            for c in components
        ],
        "solder_traces": [
            {
                "id": t.id,
                "holes": [list(h) for h in t.holes],
                "segments": [[list(s[0]), list(s[1])] for s in t.segments],
            }
            for t in solder_mgr.traces
        ],
        "jumpers": [
            {
                "start_col": j.start_col,
                "start_row": j.start_row,
                "end_col": j.end_col,
                "end_row": j.end_row,
                "bends": [list(b) for b in j.bends],
                "color": j.color,
                "side": j.side,
                "uid": j.uid,
                "start_pin": list(j.start_pin) if j.start_pin is not None else None,
                "end_pin": list(j.end_pin) if j.end_pin is not None else None,
            }
            for j in jumpers
        ],
    }

def save_project_file(filepath: str, state_data: dict[str, Any]) -> None:
    """Saves state dictionary to a .pbrd JSON file."""
    if not filepath.lower().endswith(PROJECT_FILE_EXTENSION):
        filepath += PROJECT_FILE_EXTENSION

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(state_data, f, indent=2, ensure_ascii=False)

def load_project_file(filepath: str) -> dict[str, Any]:
    """Loads and validates a .pbrd project file, returning state dictionary."""
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("Invalid project file: root must be a JSON object.")

    if data.get("format") != FORMAT_IDENTIFIER:
        raise ValueError(f"Unknown or incompatible file format: {data.get('format')}")

    return data
