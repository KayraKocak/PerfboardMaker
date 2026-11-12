import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QApplication, QGraphicsScene, QStyleOptionGraphicsItem

from app.models.board import BoardConfig
from app.models.component_def import ComponentDef, OffGridPinDef, PinDef
from app.models.placed_component import PlacedComponent
from app.views.canvas_view import CanvasView, REGISTRY
from app.views.component_item import ComponentItem


class RecordingComponent(ComponentDef):
    def __init__(self):
        super().__init__(
            "test", "Test", "Test", "", "",
            [PinDef("anchor", 0, 0), PinDef("pin", 2, 1)],
            off_grid_pins=[OffGridPinDef("off-grid", 0.5, 2)],
        )
        self.drawn = []

    def draw_top(self, painter, instance, pitch_px):
        self.drawn.append(("top", painter.worldTransform()))

    def draw_bottom(self, painter, instance, pitch_px):
        self.drawn.append(("bottom", painter.worldTransform()))


class ComponentRotationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def assert_point_close(self, actual, expected):
        self.assertAlmostEqual(actual.x(), expected[0], places=6)
        self.assertAlmostEqual(actual.y(), expected[1], places=6)

    def check_item(self, item, expected_draws):
        instance, definition, config = item.instance, item.comp_def, item.config
        image = QImage(800, 800, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        painter.translate(item.pos())
        definition.drawn.clear()
        item.paint(painter, QStyleOptionGraphicsItem())
        painter.end()
        self.assertEqual([side for side, _ in definition.drawn], expected_draws)

        pins = definition.get_pins_for_instance(instance)
        off_grid_pins = definition.get_off_grid_pins_for_instance(instance)
        positions = instance.get_pin_positions(definition) + instance.get_off_grid_pin_positions(definition)
        offsets = [(pin.grid_x, pin.grid_y) for pin in pins]
        offsets += [(pin.offset_x, pin.offset_y) for pin in off_grid_pins]
        for (_, col, row, _), (x, y) in zip(positions, offsets):
            expected = config.grid_to_board_pos(col, row)
            local = QPointF(x * config.pitch_px, y * config.pitch_px)
            for _, transform in definition.drawn:
                self.assert_point_close(transform.map(local), expected)
            hit_point = QPointF(expected[0] - item.pos().x(), expected[1] - item.pos().y())
            self.assertTrue(item.shape().contains(hit_point))
            self.assertTrue(item.boundingRect().contains(hit_point))

    def test_flip_and_double_view_match_rotated_pin_positions(self):
        definition = RecordingComponent()
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation):
                instance = PlacedComponent("test", 10, 10, rotation=rotation)
                front_config = BoardConfig(view_side="top")
                back_config = BoardConfig(view_side="bottom", transparent=True)
                front = ComponentItem(instance, definition, front_config)
                back = ComponentItem(instance, definition, back_config)
                scene = QGraphicsScene()
                scene.addItem(front)
                front.setSelected(True)
                self.check_item(front, ["top"])
                self.check_item(back, ["top", "bottom"])

                front_config.view_side = "bottom"
                front.update_position_from_grid()
                front.refresh_geometry()
                self.check_item(front, ["bottom"])

                front_config.view_side = "top"
                front.update_position_from_grid()
                front.refresh_geometry()
                self.check_item(front, ["top"])

    def test_canvas_flip_and_synchronized_double_view(self):
        definition = RecordingComponent()
        instance = PlacedComponent("test", 10, 10, rotation=90)
        front = CanvasView(BoardConfig())
        front.placed_components.append(instance)
        item = ComponentItem(instance, definition, front.config)
        front.component_items.append(item)
        front.scene.addItem(item)

        front.toggle_view_side()
        self.check_item(item, ["bottom"])
        front.toggle_view_side()
        self.check_item(item, ["top"])

        back = CanvasView(BoardConfig(view_side="bottom"), primary_view=front)
        with patch.object(REGISTRY, "get", return_value=definition):
            front.link_partner(back)
            front.set_double_view_active(True)
            back.set_double_view_active(True)
            self.check_item(back.component_items[0], ["bottom"])
            item.set_rotation(270)
            self.check_item(item, ["top"])
            self.check_item(back.component_items[0], ["bottom"])


if __name__ == "__main__":
    unittest.main()
