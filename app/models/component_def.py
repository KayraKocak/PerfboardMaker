"""
Component definition and pin definitions.
"""
from dataclasses import dataclass, field
from typing import Callable, Any
from PyQt6.QtGui import QPainter, QPainterPath
from PyQt6.QtCore import QRectF, QPointF

@dataclass
class PinDef:
    name: str
    grid_x: int  # Relative to anchor pin (0, 0)
    grid_y: int
    description: str = ""
    pin_type: str = "io"  # "power", "ground", "io", "passive"

@dataclass
class OffGridPinDef:
    name: str
    offset_x: float  # Relative to anchor pin (0, 0) in 2.54mm hole units
    offset_y: float
    description: str = ""
    pin_type: str = "io"  # "power", "ground", "io", "passive"

@dataclass
class PropertyDef:
    id: str
    label: str
    type: str  # "str", "int", "choice"
    default: Any
    choices: list[Any] = field(default_factory=list)

class ComponentDef:
    def __init__(
        self,
        type_id: str,
        name: str,
        category: str,
        default_label: str,
        description: str,
        pins: list[PinDef],
        properties: list[PropertyDef] | None = None,
        anchor_pin_index: int = 0,
        tags: list[str] | None = None,
        off_grid_pins: list[OffGridPinDef] | None = None,
    ):
        self.type_id = type_id
        self.name = name
        self.category = category
        self.default_label = default_label
        self.description = description
        self.pins = pins
        self.off_grid_pins: list[OffGridPinDef] = off_grid_pins or []
        self.properties = properties or []
        self.anchor_pin_index = anchor_pin_index
        self.tags = tags or []

    def get_pins_for_instance(self, instance: Any) -> list[PinDef]:
        """Can be overridden by components with dynamic pins (e.g. variable capacitor pitch)."""
        return self.pins

    def get_off_grid_pins_for_instance(self, instance: Any) -> list[OffGridPinDef]:
        """Returns jumper-only pins that do not align to 2.54 mm perfboard holes."""
        return self.off_grid_pins

    def get_shape(self, instance: Any, pitch_px: float) -> QPainterPath:
        """Returns the precise interactive hitbox (in local anchor-centered coordinates)."""
        path = QPainterPath()
        pins = self.get_pins_for_instance(instance)
        pad_r = pitch_px * 0.45
        for p in pins:
            path.addEllipse(QPointF(p.grid_x * pitch_px, p.grid_y * pitch_px), pad_r, pad_r)
        for op in self.get_off_grid_pins_for_instance(instance):
            path.addEllipse(QPointF(op.offset_x * pitch_px, op.offset_y * pitch_px), pad_r, pad_r)
        return path

    def draw_top(self, painter: QPainter, instance: Any, pitch_px: float) -> None:
        """Draw component top view. Coordinate origin is at anchor pin (0, 0)."""
        raise NotImplementedError

    def draw_bottom(self, painter: QPainter, instance: Any, pitch_px: float) -> None:
        """Draw component bottom view (solder joints / ghost silhouette). Origin at anchor pin (0, 0)."""
        raise NotImplementedError
