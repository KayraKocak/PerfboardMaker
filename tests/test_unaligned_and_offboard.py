import os
import tempfile
import unittest
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import QApplication, QLabel

from app.components.registry import REGISTRY
from app.models.board import BoardConfig
from app.utils.fritzing_importer import import_fritzing_file
from app.views.canvas_view import CanvasView
from app.views.toolbox_widget import ComponentCard


def _make_jst_fzp() -> bytes:
    return b"""<?xml version='1.0' encoding='UTF-8'?>
<module moduleId="jst_2mm_4pin">
  <title>JST 2.0mm 4-Pin</title>
  <label>J</label>
  <views>
    <breadboardView>
      <layers image="breadboard/jst.svg">
        <layer layerId="breadboard"/>
      </layers>
    </breadboardView>
  </views>
  <connectors>
    <connector id="connector0" name="P1" type="male"><views><breadboardView><p layer="breadboard" svgId="c0"/></breadboardView></views></connector>
    <connector id="connector1" name="P2" type="male"><views><breadboardView><p layer="breadboard" svgId="c1"/></breadboardView></views></connector>
    <connector id="connector2" name="P3" type="male"><views><breadboardView><p layer="breadboard" svgId="c2"/></breadboardView></views></connector>
    <connector id="connector3" name="P4" type="male"><views><breadboardView><p layer="breadboard" svgId="c3"/></breadboardView></views></connector>
  </connectors>
</module>
"""


def _make_jst_svg() -> bytes:
    return b"""<svg xmlns="http://www.w3.org/2000/svg" width="8.0mm" height="4.0mm" viewBox="0 0 8.0 4.0">
  <g id="breadboard">
    <circle id="c0" cx="1.0" cy="2.0" r="0.3"/>
    <circle id="c1" cx="3.0" cy="2.0" r="0.3"/>
    <circle id="c2" cx="5.0" cy="2.0" r="0.3"/>
    <circle id="c3" cx="7.0" cy="2.0" r="0.3"/>
  </g>
</svg>
"""


class UnalignedAndOffboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_unaligned_2mm_part_imports_as_jumper_only_and_card_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "jst_4pin.fzpz")
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr("part.jst.fzp", _make_jst_fzp())
                zf.writestr("svg.breadboard.jst.svg", _make_jst_svg())

            comp, err = import_fritzing_file(path)
            self.assertIsNone(err)
            self.assertIsNotNone(comp)
            self.assertEqual(len(comp.pins), 0)
            self.assertEqual(len(comp.off_grid_pins), 4)

            card = ComponentCard(comp, is_online=True)
            try:
                texts = [lbl.text() for lbl in card.findChildren(QLabel)]
                self.assertTrue(any("Pins cannot align with perfboard; only connectable via jumpers" in t for t in texts))
            finally:
                card.deleteLater()

    def test_offboard_placement_movement_and_jumper_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "jst_4pin.fzpz")
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr("part.jst.fzp", _make_jst_fzp())
                zf.writestr("svg.breadboard.jst.svg", _make_jst_svg())
            comp, err = import_fritzing_file(path)
            self.assertIsNone(err)

        REGISTRY.register(comp)
        cv = CanvasView(BoardConfig(cols=16, rows=12))
        try:
            # Place completely outside perfboard (negative col)
            inst = cv.add_component(comp.type_id, -4, 3)
            self.assertEqual((inst.grid_x, inst.grid_y), (-4, 3))
            c_item = cv.component_items[-1]

            # Drag/move further off-board without clamping back into [0..cols-1]
            target_x, target_y = cv.config.grid_to_board_pos(-6, -2)
            c_item.setPos(QPointF(target_x, target_y))
            self.assertEqual((inst.grid_x, inst.grid_y), (-6, -2))

            # Connect jumper from off-board unaligned pin 1 to perfboard hole (2, 2)
            off_pins = inst.get_off_grid_pin_positions(comp)
            _, cf, rf, _ = off_pins[1]
            px, py = cv.config.grid_to_board_pos(cf, rf)
            hit = cv._find_off_grid_pin_at(QPointF(px, py))
            self.assertIsNotNone(hit)
            self.assertEqual(hit[0].uid, inst.uid)

            cv.solder_mgr.connect_holes((2, 2), (3, 2))
            cv.add_jumper(cf, rf, 2, 2, start_pin=(inst.uid, 1, off_pins[1][0]))
            trace = cv.solder_mgr.find_trace_with_hole(2, 2)
            sel = cv.build_solder_selection(trace)
            self.assertEqual(sel.direct_pins, [])
            self.assertEqual(len(sel.net_only_pins), 1)
            self.assertIn("(Jumper)", sel.net_only_pins[0].pin_name)

            # Place on the perfboard too: still zero direct perfboard pin connections
            on_inst = cv.add_component(comp.type_id, 5, 5)
            cv.solder_mgr.connect_holes((5, 5), (6, 5))
            trace2 = cv.solder_mgr.find_trace_with_hole(5, 5)
            sel2 = cv.build_solder_selection(trace2)
            self.assertEqual(sel2.direct_pins, [])
            self.assertEqual(on_inst.get_pin_positions(comp), [])
        finally:
            REGISTRY._components.pop(comp.type_id, None)
            cv.deleteLater()

    def test_bused_off_grid_pins_are_preserved(self):
        fzp = b"""<?xml version='1.0' encoding='UTF-8'?>
<module moduleId="uno_bus_test">
  <title>Uno Bus Test</title>
  <label>U</label>
  <views>
    <breadboardView>
      <layers image="breadboard/uno.svg">
        <layer layerId="breadboard"/>
      </layers>
    </breadboardView>
  </views>
  <connectors>
    <connector id="c0" name="A4" type="male"><views><breadboardView><p layer="breadboard" svgId="p0"/></breadboardView></views></connector>
    <connector id="c1" name="A5" type="male"><views><breadboardView><p layer="breadboard" svgId="p1"/></breadboardView></views></connector>
    <connector id="c2" name="GND1" type="male"><views><breadboardView><p layer="breadboard" svgId="p2"/></breadboardView></views></connector>
    <connector id="c3" name="SDA" type="male"><views><breadboardView><p layer="breadboard" svgId="p3"/></breadboardView></views></connector>
    <connector id="c4" name="SCL" type="male"><views><breadboardView><p layer="breadboard" svgId="p4"/></breadboardView></views></connector>
  </connectors>
  <buses>
    <bus id="sda"><nodeMember connectorId="c0"/><nodeMember connectorId="c3"/></bus>
    <bus id="scl"><nodeMember connectorId="c1"/><nodeMember connectorId="c4"/></bus>
  </buses>
</module>
"""
        svg = b"""<svg xmlns="http://www.w3.org/2000/svg" width="20.0mm" height="10.0mm" viewBox="0 0 20.0 10.0">
  <g id="breadboard">
    <circle id="p0" cx="2.54" cy="2.54" r="0.3"/>
    <circle id="p1" cx="5.08" cy="2.54" r="0.3"/>
    <circle id="p2" cx="7.62" cy="2.54" r="0.3"/>
    <circle id="p3" cx="3.81" cy="7.62" r="0.3"/>
    <circle id="p4" cx="6.35" cy="7.62" r="0.3"/>
  </g>
</svg>
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "uno_bus.fzpz")
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr("part.uno.fzp", fzp)
                zf.writestr("svg.breadboard.uno.svg", svg)
            comp, err = import_fritzing_file(path)

        self.assertIsNone(err)
        self.assertIsNotNone(comp)
        self.assertEqual([p.name for p in comp.pins], ["A4", "A5", "GND1"])
        self.assertEqual(sorted(p.name for p in comp.off_grid_pins), ["SCL", "SDA"])

    def test_offboard_aligned_pin_connectable_via_jumper(self):
        cv = CanvasView(BoardConfig(cols=16, rows=12))
        try:
            # Place a grid-aligned Arduino Nano outside the perfboard (col=-5, row=2)
            inst = cv.add_component("arduino_nano", -5, 2)
            pins = inst.get_pin_positions(REGISTRY.get("arduino_nano"))
            pname, pc, pr, _ = pins[0]
            self.assertFalse(cv.config.is_valid_hole(pc, pr))

            px, py = cv.config.grid_to_board_pos(pc, pr)
            snapped = cv._snap_jumper_endpoint(QPointF(px, py), pc, pr)
            self.assertEqual(snapped, (pc, pr, None))

            cv.solder_mgr.connect_holes((3, 3), (4, 3))
            cv.add_jumper(pc, pr, 3, 3)
            traces, jumpers = cv.get_conductive_net_at(pc, pr, QPointF(px, py))
            self.assertEqual(len(jumpers), 1)
            self.assertEqual(len(traces), 1)

            sel = cv.build_solder_selection(traces[0])
            self.assertEqual(sel.direct_pins, [])
            self.assertTrue(any(p.pin_name == pname and p.via_jumper for p in sel.net_only_pins))
        finally:
            cv.deleteLater()


if __name__ == "__main__":
    unittest.main()
