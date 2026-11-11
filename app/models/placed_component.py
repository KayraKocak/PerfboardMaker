"""
Placed component instance on the perfboard.
"""
import uuid
from dataclasses import dataclass, field
from typing import Any

def rotate_point_cw(x: int | float, y: int | float, rotation: int) -> tuple[int | float, int | float]:
    """
    Rotates relative grid coordinates clockwise by 0, 90, 180, or 270 degrees.
    Screen coordinate system: +X right, +Y down.
    """
    rot = rotation % 360
    if rot == 0:
        return (x, y)
    elif rot == 90:
        return (-y, x)
    elif rot == 180:
        return (-x, -y)
    elif rot == 270:
        return (y, -x)
    return (x, y)

@dataclass
class PlacedComponent:
    type_id: str
    grid_x: int
    grid_y: int
    uid: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    label: str = ""
    rotation: int = 0  # 0, 90, 180, 270
    custom_props: dict[str, Any] = field(default_factory=dict)

    def rotate_cw(self) -> None:
        self.rotation = (self.rotation + 90) % 360

    def rotate_ccw(self) -> None:
        self.rotation = (self.rotation - 90) % 360

    def get_pin_positions(self, comp_def) -> list[tuple[str, int, int, str]]:
        """
        Returns list of (pin_name, abs_col, abs_row, pin_type) for each perfboard-hole pin.
        """
        pins = comp_def.get_pins_for_instance(self)
        result = []
        for p in pins:
            rx, ry = rotate_point_cw(p.grid_x, p.grid_y, self.rotation)
            abs_col = self.grid_x + rx
            abs_row = self.grid_y + ry
            result.append((p.name, abs_col, abs_row, p.pin_type))
        return result

    def get_off_grid_pin_positions(self, comp_def) -> list[tuple[str, float, float, str]]:
        """
        Returns list of (pin_name, abs_col_f, abs_row_f, pin_type) for each jumper-only off-grid pin.
        """
        if not hasattr(comp_def, "get_off_grid_pins_for_instance"):
            return []
        result = []
        for p in comp_def.get_off_grid_pins_for_instance(self):
            rx, ry = rotate_point_cw(p.offset_x, p.offset_y, self.rotation)
            abs_col = float(self.grid_x) + float(rx)
            abs_row = float(self.grid_y) + float(ry)
            result.append((p.name, abs_col, abs_row, p.pin_type))
        return result
