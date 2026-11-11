"""
SVG-backed Fritzing ComponentDef and local downloaded component storage.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from PyQt6.QtCore import QByteArray, QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PyQt6.QtSvg import QSvgRenderer

from app.components.draw_utils import draw_solder_joint
from app.models.component_def import ComponentDef, OffGridPinDef, PinDef

DOWNLOADED_PARTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloaded")
_INDEX_CACHE_FILENAME = ".index_cache.json"
_MM_PER_HOLE = 2.54


class FritzingComponentDef(ComponentDef):
    """ComponentDef rendered from a validated Fritzing breadboard SVG and snapped PinDefs."""

    def __init__(
        self,
        type_id: str,
        name: str,
        category: str,
        default_label: str,
        description: str,
        pins: list[PinDef],
        svg_bytes: bytes,
        anchor_x_mm: float,
        anchor_y_mm: float,
        svg_width_mm: float,
        svg_height_mm: float,
        tags: list[str] | None = None,
        source_info: dict[str, str] | None = None,
        is_remote_preview: bool = False,
        off_grid_pins: list[OffGridPinDef] | None = None,
    ):
        super().__init__(
            type_id=type_id,
            name=name,
            category=category,
            default_label=default_label,
            description=description,
            pins=pins,
            properties=[],
            anchor_pin_index=0,
            tags=tags or [],
            off_grid_pins=off_grid_pins or [],
        )
        self.svg_bytes = svg_bytes
        self.anchor_x_mm = float(anchor_x_mm)
        self.anchor_y_mm = float(anchor_y_mm)
        self.svg_width_mm = float(svg_width_mm)
        self.svg_height_mm = float(svg_height_mm)
        self.source_info = dict(source_info or {})
        self.is_remote_preview = is_remote_preview
        self._renderer: QSvgRenderer | None = None

    def _get_renderer(self) -> QSvgRenderer:
        if self._renderer is None:
            self._renderer = QSvgRenderer(QByteArray(self.svg_bytes))
        return self._renderer

    def _svg_rect(self, pitch_px: float) -> QRectF:
        px_per_mm = pitch_px / _MM_PER_HOLE
        return QRectF(
            -self.anchor_x_mm * px_per_mm,
            -self.anchor_y_mm * px_per_mm,
            self.svg_width_mm * px_per_mm,
            self.svg_height_mm * px_per_mm,
        )

    def get_shape(self, instance: Any, pitch_px: float) -> QPainterPath:
        path = QPainterPath()
        rect = self._svg_rect(pitch_px)
        if rect.width() > 0 and rect.height() > 0:
            path.addRoundedRect(rect, 3.0, 3.0)
        pad_r = pitch_px * 0.42
        for pin in self.pins:
            path.addEllipse(QPointF(pin.grid_x * pitch_px, pin.grid_y * pitch_px), pad_r, pad_r)
        for op in self.off_grid_pins:
            path.addEllipse(QPointF(op.offset_x * pitch_px, op.offset_y * pitch_px), pad_r, pad_r)
        return path

    def draw_top(self, painter: QPainter, instance: Any, pitch_px: float) -> None:
        renderer = self._get_renderer()
        if not renderer.isValid():
            return
        target = self._svg_rect(pitch_px)
        if target.width() <= 0 or target.height() <= 0:
            return
        renderer.render(painter, target)
        if self.off_grid_pins:
            painter.save()
            ring_r = max(2.8, pitch_px * 0.22)
            painter.setPen(QPen(QColor(253, 126, 20, 225), 1.6))
            painter.setBrush(QBrush(QColor(253, 126, 20, 45)))
            for op in self.off_grid_pins:
                painter.drawEllipse(QPointF(op.offset_x * pitch_px, op.offset_y * pitch_px), ring_r, ring_r)
            painter.restore()

    def draw_bottom(self, painter: QPainter, instance: Any, pitch_px: float) -> None:
        rect = self._svg_rect(pitch_px)
        if rect.width() > 0 and rect.height() > 0:
            painter.save()
            painter.setPen(QPen(QColor(180, 185, 195, 115), 1.0, Qt.PenStyle.DashLine))
            painter.setBrush(QBrush(QColor(120, 130, 145, 22)))
            painter.drawRoundedRect(rect, 3.0, 3.0)
            painter.restore()

        for pin in self.pins:
            draw_solder_joint(painter, pin.grid_x * pitch_px, pin.grid_y * pitch_px, pitch_px)

        if self.off_grid_pins:
            painter.save()
            ring_r = max(2.8, pitch_px * 0.22)
            painter.setPen(QPen(QColor(253, 126, 20, 180), 1.3, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for op in self.off_grid_pins:
                painter.drawEllipse(QPointF(op.offset_x * pitch_px, op.offset_y * pitch_px), ring_r, ring_r)
            painter.restore()

    def to_metadata_dict(self) -> dict[str, Any]:
        return {
            "type_id": self.type_id,
            "name": self.name,
            "category": self.category,
            "default_label": self.default_label,
            "description": self.description,
            "tags": list(self.tags),
            "anchor_x_mm": self.anchor_x_mm,
            "anchor_y_mm": self.anchor_y_mm,
            "svg_width_mm": self.svg_width_mm,
            "svg_height_mm": self.svg_height_mm,
            "source_info": dict(self.source_info),
            "pins": [
                {
                    "name": p.name,
                    "grid_x": p.grid_x,
                    "grid_y": p.grid_y,
                    "description": p.description,
                    "pin_type": p.pin_type,
                }
                for p in self.pins
            ],
            "off_grid_pins": [
                {
                    "name": op.name,
                    "offset_x": op.offset_x,
                    "offset_y": op.offset_y,
                    "description": op.description,
                    "pin_type": op.pin_type,
                }
                for op in self.off_grid_pins
            ],
        }


def _safe_filename(type_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", type_id)


def save_downloaded_part(
    comp_def: FritzingComponentDef,
    target_dir: str = DOWNLOADED_PARTS_DIR,
) -> str:
    """Persists a verified FritzingComponentDef (.json + .svg) into app/components/downloaded."""
    os.makedirs(target_dir, exist_ok=True)
    stem = _safe_filename(comp_def.type_id)
    svg_filename = f"{stem}.svg"
    json_filename = f"{stem}.json"

    svg_path = os.path.join(target_dir, svg_filename)
    json_path = os.path.join(target_dir, json_filename)

    with open(svg_path, "wb") as sf:
        sf.write(comp_def.svg_bytes)

    comp_def.is_remote_preview = False
    comp_def.category = "Downloaded (Fritzing)"
    meta = comp_def.to_metadata_dict()
    meta["svg_file"] = svg_filename

    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump(meta, jf, indent=2, ensure_ascii=False)

    return json_path


def load_downloaded_parts(source_dir: str = DOWNLOADED_PARTS_DIR) -> list[FritzingComponentDef]:
    """Loads all persisted downloaded Fritzing parts from app/components/downloaded."""
    if not os.path.isdir(source_dir):
        return []

    parts: list[FritzingComponentDef] = []
    for fname in sorted(os.listdir(source_dir)):
        if not fname.lower().endswith(".json") or fname == _INDEX_CACHE_FILENAME:
            continue
        json_path = os.path.join(source_dir, fname)
        try:
            with open(json_path, "r", encoding="utf-8") as jf:
                meta = json.load(jf)
            svg_rel = meta.get("svg_file") or (os.path.splitext(fname)[0] + ".svg")
            svg_path = os.path.join(source_dir, svg_rel)
            if not os.path.isfile(svg_path):
                continue
            with open(svg_path, "rb") as sf:
                svg_bytes = sf.read()
            pins = [
                PinDef(
                    name=str(p["name"]),
                    grid_x=int(p["grid_x"]),
                    grid_y=int(p["grid_y"]),
                    description=str(p.get("description", "")),
                    pin_type=str(p.get("pin_type", "io")),
                )
                for p in meta.get("pins", [])
            ]
            if not pins:
                continue
            off_grid_pins = [
                OffGridPinDef(
                    name=str(op["name"]),
                    offset_x=float(op["offset_x"]),
                    offset_y=float(op["offset_y"]),
                    description=str(op.get("description", "")),
                    pin_type=str(op.get("pin_type", "io")),
                )
                for op in meta.get("off_grid_pins", [])
            ]
            comp = FritzingComponentDef(
                type_id=str(meta["type_id"]),
                name=str(meta["name"]),
                category=str(meta.get("category") or "Downloaded (Fritzing)"),
                default_label=str(meta.get("default_label") or "U"),
                description=str(meta.get("description") or ""),
                pins=pins,
                svg_bytes=svg_bytes,
                anchor_x_mm=float(meta["anchor_x_mm"]),
                anchor_y_mm=float(meta["anchor_y_mm"]),
                svg_width_mm=float(meta["svg_width_mm"]),
                svg_height_mm=float(meta["svg_height_mm"]),
                tags=[str(t) for t in meta.get("tags", [])],
                source_info={str(k): str(v) for k, v in meta.get("source_info", {}).items()},
                is_remote_preview=False,
                off_grid_pins=off_grid_pins,
            )
            if comp._get_renderer().isValid():
                parts.append(comp)
        except Exception:
            continue
    return parts
