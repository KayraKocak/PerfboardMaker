"""
Jumper wire model and color presets with straight segments and interactive bend points.
"""
import math
import uuid
from dataclasses import dataclass, field
from typing import Literal

JUMPER_COLORS = [
    ("#e03131", "Red"),
    ("#1c7ed6", "Blue"),
    ("#2f9e44", "Green"),
    ("#fcc419", "Yellow"),
    ("#fd7e14", "Orange"),
    ("#ae3ec9", "Purple"),
    ("#212529", "Black"),
    ("#f8f9fa", "White"),
    ("#862e9c", "Violet"),
    ("#1098ad", "Cyan"),
    ("#8d6e63", "Brown")
]

DEFAULT_JUMPER_COLOR = "#e03131" # Red

@dataclass(eq=False)
class JumperWire:
    start_col: int | float
    start_row: int | float
    end_col: int | float
    end_row: int | float
    bends: list[tuple[int, int]] = field(default_factory=list) # List of (col, row) bend waypoints
    color: str = DEFAULT_JUMPER_COLOR
    side: Literal["top", "bottom"] = "top"
    uid: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    start_pin: tuple[str, int, str] | None = None  # (comp_uid, off_grid_pin_idx, pin_name)
    end_pin: tuple[str, int, str] | None = None    # (comp_uid, off_grid_pin_idx, pin_name)

    def __hash__(self):
        return hash(self.uid)

    def __eq__(self, other):
        return isinstance(other, JumperWire) and self.uid == other.uid

    def start_hole(self) -> tuple[int, int] | None:
        if self.start_pin is not None:
            return None
        return (int(round(self.start_col)), int(round(self.start_row)))

    def end_hole(self) -> tuple[int, int] | None:
        if self.end_pin is not None:
            return None
        return (int(round(self.end_col)), int(round(self.end_row)))

    def start_node(self) -> tuple:
        if self.start_pin is not None:
            return ("pin", self.start_pin[0], self.start_pin[1])
        return ("hole", int(round(self.start_col)), int(round(self.start_row)))

    def end_node(self) -> tuple:
        if self.end_pin is not None:
            return ("pin", self.end_pin[0], self.end_pin[1])
        return ("hole", int(round(self.end_col)), int(round(self.end_row)))

    def all_points(self) -> list[tuple[int | float, int | float]]:
        """Returns sequence of (col, row) from start, through all bends, to end."""
        return [(self.start_col, self.start_row)] + list(self.bends) + [(self.end_col, self.end_row)]

    def all_segments(self) -> list[tuple[tuple[int | float, int | float], tuple[int | float, int | float]]]:
        pts = self.all_points()
        return [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]

    @property
    def length_holes(self) -> float:
        pts = self.all_points()
        total = 0.0
        for i in range(len(pts) - 1):
            p1, p2 = pts[i], pts[i + 1]
            total += math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        return total

    @property
    def length_mm(self) -> float:
        return self.length_holes * 2.54

    def insert_bend_at_segment(self, col: int, row: int, seg_idx: int) -> int:
        """Inserts a bend point after start or previous bends. Returns bend index."""
        # seg_idx: 0 means between start and bend[0] (or start and end if no bends)
        self.bends.insert(seg_idx, (col, row))
        return seg_idx

    def move_point(
        self,
        pt_idx: int,
        col: int | float,
        row: int | float,
        pin_ref: tuple[str, int, str] | None = None,
    ):
        """
        Moves point by index in all_points():
        0 = start, 1..N-2 = bends, N-1 = end.
        """
        if pt_idx == 0:
            self.start_col = col
            self.start_row = row
            self.start_pin = pin_ref
        elif pt_idx == len(self.bends) + 1:
            self.end_col = col
            self.end_row = row
            self.end_pin = pin_ref
        else:
            bend_idx = pt_idx - 1
            if 0 <= bend_idx < len(self.bends):
                self.bends[bend_idx] = (int(round(col)), int(round(row)))

    def remove_bend(self, bend_idx: int):
        if 0 <= bend_idx < len(self.bends):
            self.bends.pop(bend_idx)
