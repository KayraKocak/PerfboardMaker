"""
Perfboard data model and coordinate transformations.
"""
from dataclasses import dataclass, field
import math
from typing import Literal
import uuid

CUTOUT_SHAPES = ("rect", "rounded_rect", "oval", "inverted_oval", "custom")
_UNIT_CIRCLE_16 = tuple(
    (math.cos(2.0 * math.pi * i / 16.0), math.sin(2.0 * math.pi * i / 16.0))
    for i in range(16)
)


def col_index_to_name(col: int) -> str:
    """Converts 0-indexed column to spreadsheet-like column name (A, B, ..., Z, AA, AB, ...)."""
    name = ""
    col += 1
    while col > 0:
        col, rem = divmod(col - 1, 26)
        name = chr(65 + rem) + name
    return name


def _point_in_polygon(px: float, py: float, poly: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test."""
    n = len(poly)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi + 1e-18) + xi):
            inside = not inside
        j = i
    return inside


def _dist_point_to_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx = bx - ax
    dy = by - ay
    len_sq = dx * dx + dy * dy
    if len_sq <= 1e-18:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _min_dist_to_polygon_edges(px: float, py: float, poly: list[tuple[float, float]]) -> float:
    n = len(poly)
    if n < 2:
        return float("inf")
    min_d = float("inf")
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        d = _dist_point_to_segment(px, py, ax, ay, bx, by)
        if d < min_d:
            min_d = d
    return min_d


@dataclass
class BoardCutout:
    """A freeform cutout shape stored in canonical top-view board pixel coordinates."""
    shape: str = "rect"  # "rect", "rounded_rect", "oval", "inverted_oval", "custom"
    x: float = 0.0
    y: float = 0.0
    w: float = 60.0
    h: float = 60.0
    corner_radius: float = 12.0
    rotation: float = 0.0
    inverted: bool = False
    vertices: list[tuple[float, float]] = field(default_factory=list)
    uid: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    @property
    def is_inverted(self) -> bool:
        return bool(self.inverted or self.shape == "inverted_oval")

    def center(self) -> tuple[float, float]:
        return (self.x + self.w * 0.5, self.y + self.h * 0.5)

    def _to_local(self, px: float, py: float) -> tuple[float, float]:
        if abs(self.rotation) <= 1e-9:
            return (px, py)
        cx, cy = self.center()
        rad = math.radians(-self.rotation)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        dx = px - cx
        dy = py - cy
        return (cx + dx * cos_a - dy * sin_a, cy + dx * sin_a + dy * cos_a)

    def _to_world(self, lx: float, ly: float) -> tuple[float, float]:
        if abs(self.rotation) <= 1e-9:
            return (lx, ly)
        cx, cy = self.center()
        rad = math.radians(self.rotation)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        dx = lx - cx
        dy = ly - cy
        return (cx + dx * cos_a - dy * sin_a, cy + dx * sin_a + dy * cos_a)

    def recompute_custom_bounds(self):
        """Updates (x, y, w, h) to the axis-aligned bounding box of local vertices."""
        if not self.vertices:
            return
        xs = [v[0] for v in self.vertices]
        ys = [v[1] for v in self.vertices]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        self.x = min_x
        self.y = min_y
        self.w = max(4.0, max_x - min_x)
        self.h = max(4.0, max_y - min_y)

    def _effective_corner_radius(self) -> float:
        return max(0.0, min(self.corner_radius, self.w * 0.5, self.h * 0.5))

    def _point_in_oval_local(self, lx: float, ly: float) -> bool:
        rx = self.w * 0.5
        ry = self.h * 0.5
        if rx <= 0.0 or ry <= 0.0:
            return False
        ex = self.x + rx
        ey = self.y + ry
        return ((lx - ex) / rx) ** 2 + ((ly - ey) / ry) ** 2 <= 1.0

    def _contains_point_uninverted_local(self, lx: float, ly: float) -> bool:
        if self.shape == "custom":
            return _point_in_polygon(lx, ly, self.vertices)
        if self.w <= 0.0 or self.h <= 0.0:
            return False
        if self.shape == "rect":
            return self.x <= lx <= self.x + self.w and self.y <= ly <= self.y + self.h
        if self.shape == "rounded_rect":
            if not (self.x <= lx <= self.x + self.w and self.y <= ly <= self.y + self.h):
                return False
            cr = self._effective_corner_radius()
            if cr <= 0.0:
                return True
            dx = 0.0
            if lx < self.x + cr:
                dx = (self.x + cr) - lx
            elif lx > self.x + self.w - cr:
                dx = lx - (self.x + self.w - cr)
            dy = 0.0
            if ly < self.y + cr:
                dy = (self.y + cr) - ly
            elif ly > self.y + self.h - cr:
                dy = ly - (self.y + self.h - cr)
            if dx > 0.0 and dy > 0.0:
                return math.hypot(dx, dy) <= cr
            return True
        if self.shape in ("oval", "inverted_oval"):
            return self._point_in_oval_local(lx, ly)
        return False

    def contains_point(self, px: float, py: float) -> bool:
        """Returns True if (px, py) lies inside the active cutter region."""
        if self.shape == "custom" and len(self.vertices) < 3:
            return False
        if self.shape != "custom" and (self.w <= 0.0 or self.h <= 0.0):
            return False
        lx, ly = self._to_local(px, py)
        inside = self._contains_point_uninverted_local(lx, ly)
        return (not inside) if self.is_inverted else inside

    def _covers_circle_uninverted_local(self, cx: float, cy: float, r: float) -> bool:
        if self.shape == "custom":
            if len(self.vertices) < 3:
                return False
            if not _point_in_polygon(cx, cy, self.vertices):
                return False
            return _min_dist_to_polygon_edges(cx, cy, self.vertices) >= r
        if self.w <= 0.0 or self.h <= 0.0:
            return False
        if self.shape == "rect":
            return (
                cx - r >= self.x
                and cx + r <= self.x + self.w
                and cy - r >= self.y
                and cy + r <= self.y + self.h
            )
        if self.shape == "rounded_rect":
            if not (
                cx - r >= self.x
                and cx + r <= self.x + self.w
                and cy - r >= self.y
                and cy + r <= self.y + self.h
            ):
                return False
            cr = self._effective_corner_radius()
            if cr <= 0.0:
                return True
            dx = 0.0
            if cx < self.x + cr:
                dx = (self.x + cr) - cx
            elif cx > self.x + self.w - cr:
                dx = cx - (self.x + self.w - cr)
            dy = 0.0
            if cy < self.y + cr:
                dy = (self.y + cr) - cy
            elif cy > self.y + self.h - cr:
                dy = cy - (self.y + self.h - cr)
            if dx > 0.0 and dy > 0.0:
                return math.hypot(dx, dy) + r <= cr
            return True
        if self.shape in ("oval", "inverted_oval"):
            if self.w * 0.5 <= r or self.h * 0.5 <= r:
                return False
            if not self._point_in_oval_local(cx, cy):
                return False
            return all(
                self._point_in_oval_local(cx + r * ux, cy + r * uy)
                for ux, uy in _UNIT_CIRCLE_16
            )
        return False

    def covers_circle(self, cx: float, cy: float, r: float) -> bool:
        """Returns True if a circle of radius r at (cx, cy) is completely covered by this cutter."""
        if self.shape == "custom" and len(self.vertices) < 3:
            return False
        if self.shape != "custom" and (self.w <= 0.0 or self.h <= 0.0):
            return False
        lx, ly = self._to_local(cx, cy)
        if not self.is_inverted:
            return self._covers_circle_uninverted_local(lx, ly, r)

        # Inverted cutter: entire circle must lie outside the un-inverted shape
        if self.shape == "custom":
            if _point_in_polygon(lx, ly, self.vertices):
                return False
            return _min_dist_to_polygon_edges(lx, ly, self.vertices) >= r
        if self._contains_point_uninverted_local(lx, ly):
            return False
        return all(
            not self._contains_point_uninverted_local(lx + r * ux, ly + r * uy)
            for ux, uy in _UNIT_CIRCLE_16
        )


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
    cutouts: list[BoardCutout] = field(default_factory=list)

    @property
    def width_px(self) -> float:
        return (self.cols - 1) * self.pitch_px + 2 * self.margin_px

    @property
    def height_px(self) -> float:
        return (self.rows - 1) * self.pitch_px + 2 * self.margin_px

    def is_hole_cut(self, col: int, row: int) -> bool:
        """Returns True if the hole at (col, row) is completely covered by any cutout."""
        if not self.cutouts:
            return False
        cx, cy = self.grid_to_board_pos(col, row, view_side="top")
        r = self.hole_radius_px
        return any(cutout.covers_circle(cx, cy, r) for cutout in self.cutouts)

    def is_valid_hole(self, col: int, row: int) -> bool:
        if not (0 <= col < self.cols and 0 <= row < self.rows):
            return False
        return not self.is_hole_cut(col, row)

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
