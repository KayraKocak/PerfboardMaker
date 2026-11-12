import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QApplication, QStyleOptionGraphicsItem

from app.components.fritzing_part import FritzingComponentDef
from app.components.registry import REGISTRY
from app.models.board import BoardConfig
from app.models.jumper import JumperWire
from app.models.placed_component import PlacedComponent
from app.models.solder import SolderManager
from app.views.component_item import ComponentItem
from app.views.jumper_item import JumperItem
from app.views.main_window import MainWindow
from app.views.solder_item import SolderItem


def render_item(item):
    image = QImage(200, 200, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    item.paint(painter, QStyleOptionGraphicsItem())
    painter.end()
    return image


class TransparencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_imported_svg_and_builtin_render_transparent(self):
        imported = FritzingComponentDef(
            "test_svg", "Test", "Test", "T", "", [],
            b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
            b'<rect width="10" height="10" fill="red"/></svg>',
            0, 0, 2.54, 2.54,
        )
        config = BoardConfig()
        item = ComponentItem(PlacedComponent("test_svg", 0, 0), imported, config)
        opaque = render_item(item)
        config.transparent_components = True
        transparent = render_item(item)
        self.assertEqual(opaque.pixelColor(10, 10).alpha(), 255)
        self.assertAlmostEqual(transparent.pixelColor(10, 10).alpha(), 128, delta=1)

        builtin = REGISTRY.get("arduino_nano")
        self.assertIsNotNone(builtin)
        item = ComponentItem(PlacedComponent("arduino_nano", 0, 0), builtin, config)
        transparent = render_item(item)
        config.transparent_components = False
        opaque = render_item(item)
        self.assertNotEqual(transparent, opaque)

    def test_solder_and_jumpers_unaffected(self):
        for side in ("top", "bottom"):
            config = BoardConfig(cols=6, view_side=side, transparent=True)
            manager = SolderManager()
            manager.connect_holes((1, 1), (3, 1))
            for item in (
                SolderItem(manager, config),
                JumperItem(JumperWire(1, 2, 3, 2, side=side), config),
            ):
                before = render_item(item)
                x = 76 if side == "top" else 100
                y = 52 if isinstance(item, SolderItem) else 76
                self.assertNotEqual(before.pixelColor(x, y).alpha(), 0)
                config.transparent_components = True
                self.assertEqual(before, render_item(item))
                config.transparent_components = False

    def test_toolbar_partner_and_rebuilt_components(self):
        with patch("app.views.main_window.QTimer.singleShot"):
            window = MainWindow()
        try:
            front, back = window.canvas, window.canvas_back
            self.assertEqual(window.btn_transparent.text(), "Transparent PCB")
            self.assertEqual(window.btn_transparent_components.text(), "Transparent Components")
            front.add_component("arduino_nano", 2, 2)
            state = front.serialize_state()
            window.btn_transparent_components.click()
            self.assertTrue(front.config.transparent_components)
            self.assertTrue(back.config.transparent_components)
            self.assertFalse(front.config.transparent)
            self.assertEqual(front.serialize_state(), state)

            window.btn_double_view.click()
            front.load_state(state)
            self.assertTrue(front.component_items[0].config.transparent_components)
            self.assertTrue(back.component_items[0].config.transparent_components)
            front.add_component("arduino_nano", 10, 10)
            self.assertTrue(front.component_items[-1].config.transparent_components)
            self.assertTrue(back.component_items[-1].config.transparent_components)

            window.btn_transparent.click()
            self.assertTrue(front.config.transparent)
            self.assertTrue(back.config.transparent)
            window.btn_transparent_components.click()
            self.assertFalse(front.config.transparent_components)
            self.assertFalse(back.config.transparent_components)
            self.assertTrue(front.config.transparent)
            window.btn_transparent.click()
            self.assertFalse(front.config.transparent)
        finally:
            window.autosave_timer.stop()
            window.deleteLater()

    def test_bottom_component_artwork_with_both_toggles(self):
        class RecordingComponent:
            def __init__(self):
                self.opacities = []

            def draw_top(self, painter, instance, pitch):
                self.opacities.append(("top", painter.opacity()))

            def draw_bottom(self, painter, instance, pitch):
                self.opacities.append(("bottom", painter.opacity()))

        config = BoardConfig(view_side="bottom", transparent=True)
        component = RecordingComponent()
        item = ComponentItem(PlacedComponent("test", 0, 0), component, config)
        render_item(item)
        self.assertEqual(component.opacities, [("top", 0.38), ("bottom", 1.0)])
        component.opacities.clear()
        config.transparent_components = True
        render_item(item)
        self.assertEqual(component.opacities, [("top", 0.19), ("bottom", 0.5)])


if __name__ == "__main__":
    unittest.main()
