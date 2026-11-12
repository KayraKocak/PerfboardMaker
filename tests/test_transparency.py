import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QImage, QPainter, QPainterPath
from PyQt6.QtWidgets import QApplication, QGraphicsScene, QStyleOptionGraphicsItem

from app.components.fritzing_part import FritzingComponentDef
from app.components.registry import REGISTRY
from app.models.board import BoardConfig
from app.models.component_def import ComponentDef, PinDef
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

    def test_bottom_component_opacity_and_selected_outline_rotation(self):
        class RecordingComponent(ComponentDef):
            def __init__(self):
                super().__init__(
                    "rec", "Rec", "Rec", "", "",
                    [PinDef("a", 0, 0), PinDef("b", 2, 1)],
                )
                self.opacities = []

            def draw_top(self, painter, instance, pitch):
                self.opacities.append(("top", painter.opacity()))

            def draw_bottom(self, painter, instance, pitch):
                self.opacities.append(("bottom", painter.opacity()))

            def get_shape(self, instance, pitch):
                path = QPainterPath()
                path.addRect(0, 0, 2 * pitch, pitch)
                return path

        config = BoardConfig(view_side="bottom", transparent=True)
        component = RecordingComponent()
        instance = PlacedComponent("rec", 10, 10, rotation=90)
        item = ComponentItem(instance, component, config)
        scene = QGraphicsScene()
        scene.addItem(item)
        item.setSelected(True)

        image = QImage(800, 800, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.translate(item.pos())
        item.paint(painter, QStyleOptionGraphicsItem())
        painter.end()

        self.assertAlmostEqual(component.opacities[0][1], 0.38, places=6)
        self.assertAlmostEqual(component.opacities[1][1], 1.0, places=6)

        component.opacities.clear()
        config.transparent_components = True
        painter = QPainter(image)
        painter.translate(item.pos())
        item.paint(painter, QStyleOptionGraphicsItem())
        painter.end()

        self.assertAlmostEqual(component.opacities[0][1], 0.19, places=6)
        self.assertAlmostEqual(component.opacities[1][1], 0.5, places=6)

        # Verify selection outline & hitbox at +90 deg in bottom view (and NOT buggy -90 deg)
        p = config.pitch_px
        edge_ok = QPointF(item.pos().x() + 0.5 * p, item.pos().y() + 2.0 * p)
        edge_wrong = QPointF(item.pos().x() - 0.5 * p, item.pos().y() - 2.0 * p)
        inside_ok = QPointF(0.5 * p, 1.0 * p)
        inside_wrong = QPointF(-0.5 * p, -1.0 * p)
        self.assertTrue(item.shape().contains(inside_ok))
        self.assertFalse(item.shape().contains(inside_wrong))
        self.assertNotEqual(image.pixelColor(int(round(edge_ok.x())), int(round(edge_ok.y()))).alpha(), 0)
        self.assertEqual(image.pixelColor(int(round(edge_wrong.x())), int(round(edge_wrong.y()))).alpha(), 0)


if __name__ == "__main__":
    unittest.main()
