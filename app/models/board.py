"""
Perfboard data model and coordinate transformations.
"""
from dataclasses import dataclass, field
from typing import Literal

def col_index_to_name(col: int) -> str:
    """Converts 0-indexed column to spreadsheet-like column name (A, B, ..., Z, AA, AB, ...)."""
    name = ""
    col += 1
    while col > 0:
        col, rem = divmod(col - 1, 26)
        name = chr(65 + rem) + name
    return name

@dataclass
class BoardConfig:
    cols: int = 34
    rows: int = 24
    pitch_px: float = 24.0  # Pixels per 2.54mm (0.1 inch) hole
    margin_px: float = 28.0 # Margin around holes
    hole_radius_px: float = 3.8
    pad_radius_px: float = 7.6
    style: str = "green"  # "green", "brown", "blue", "black"
    view_side: Literal["top", "bottom"] = "top"
    transparent: bool = False
    transparent_components: bool = False

    @property
    def width_px(self) -> float:
        return (self.cols - 1) * self.pitch_px + 2 * self.margin_px

    @property
    def height_px(self) -> float:
        return (self.rows - 1) * self.pitch_px + 2 * self.margin_px

    def is_valid_hole(self, col: int, row: int) -> bool:
        return 0 <= col < self.cols and 0 <= row < self.rows

    def grid_to_board_pos(self, col: int, row: int, view_side: str | None = None) -> tuple[float, float]:
        """
        Converts grid (col, row) to board local coordinates (pixels).
        When view_side == "bottom", the X axis is mirrored (flipped horizontally)
        just like turning over a physical board.
        """
        side = view_side if view_side is not None else self.view_side
        if side == "bottom":
            effective_col = (self.cols - 1) - col
        else:
            effective_col = col

        x = self.margin_px + effective_col * self.pitch_px
        y = self.margin_px + row * self.pitch_px
        return (x, y)

    def board_pos_to_grid(self, x: float, y: float, view_side: str | None = None) -> tuple[int, int]:
        """
        Converts board local coordinates (pixels) to nearest grid (col, row).
        Handles mirrored X in bottom view.
        """
        side = view_side if view_side is not None else self.view_side
        rel_x = (x - self.margin_px) / self.pitch_px
        rel_y = (y - self.margin_px) / self.pitch_px
        col = int(round(rel_x))
        row = int(round(rel_y))

        if side == "bottom":
            col = (self.cols - 1) - col

        return (col, row)
