import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QRectF
from PyQt6.QtWidgets import QApplication

from app.models.board import BoardConfig, BoardCutout
from app.models.jumper import JumperWire
from app.models.project import serialize_state
from app.models.solder import SolderManager
from app.views.canvas_view import CanvasView
from app.views.properties_widget import PropertiesWidget
from app.views.viewport_toolbar import ViewportToolbar


class TestShapePerfboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_rect_cutout_disables_only_completely_covered_holes(self):
        cfg = BoardConfig(cols=6, rows=6)
        cx1, cy1 = cfg.grid_to_board_pos(1, 1, view_side="top")
        r = cfg.hole_radius_px

        # Exact freeform rect covering hole (1, 1) completely, and only half of (2, 1)
        cx2, _ = cfg.grid_to_board_pos(2, 1, view_side="top")
        cutout = BoardCutout(
            shape="rect",
            x=cx1 - r - 1.5,
            y=cy1 - r - 1.5,
            w=(cx2 - (cx1 - r - 1.5)),  # stops right at center of hole (2, 1)
            h=2.0 * r + 3.0,
        )
        cfg.cutouts.append(cutout)

        self.assertFalse(cfg.is_valid_hole(1, 1))
        self.assertTrue(cfg.is_valid_hole(2, 1))
        self.assertTrue(cfg.is_valid_hole(0, 0))

    def test_rounded_rect_corner_keeps_uncovered_hole_valid(self):
        cfg = BoardConfig(cols=6, rows=6)
        x0, y0 = cfg.grid_to_board_pos(0, 0, view_side="top")
        x2, y2 = cfg.grid_to_board_pos(2, 2, view_side="top")
        # Big corner radius cuts off corner hole (0, 0) from the rounded rect interior
        cutout = BoardCutout(
            shape="rounded_rect",
            x=x0 - 5.0,
            y=y0 - 5.0,
            w=(x2 - x0) + 10.0,
            h=(y2 - y0) + 10.0,
            corner_radius=30.0,
        )
        cfg.cutouts.append(cutout)

        # Center hole (1, 1) is completely inside; corner hole (0, 0) is outside the rounded corner
        self.assertFalse(cfg.is_valid_hole(1, 1))
        self.assertTrue(cfg.is_valid_hole(0, 0))

    def test_oval_and_inverted_oval_cutouts(self):
        cfg = BoardConfig(cols=7, rows=7)
        cx, cy = cfg.grid_to_board_pos(3, 3, view_side="top")
        oval = BoardCutout(
            shape="oval",
            x=cx - 32.5,
            y=cy - 32.5,
            w=65.0,
            h=65.0,
        )
        cfg.cutouts = [oval]
        self.assertFalse(cfg.is_valid_hole(3, 3))
        self.assertTrue(cfg.is_valid_hole(0, 0))

        # Inverted oval keeps center hole valid and disables outer corner holes
        inv = BoardCutout(
            shape="inverted_oval",
            x=cx - 32.5,
            y=cy - 32.5,
            w=65.0,
            h=65.0,
        )
        cfg.cutouts = [inv]
        self.assertTrue(cfg.is_valid_hole(3, 3))
        self.assertFalse(cfg.is_valid_hole(0, 0))
        self.assertFalse(cfg.is_valid_hole(6, 6))

    def test_multiple_cutouts_and_serialization_roundtrip(self):
        cfg = BoardConfig(cols=10, rows=8)
        cfg.cutouts = [
            BoardCutout(shape="rect", x=20.3, y=22.7, w=45.5, h=40.2, uid="c1"),
            BoardCutout(shape="rounded_rect", x=100.1, y=50.4, w=70.0, h=60.0, corner_radius=14.5, uid="c2"),
        ]
        state = serialize_state(cfg, [], SolderManager(), [])
        self.assertEqual(len(state["board"]["cutouts"]), 2)

        cv = CanvasView(BoardConfig())
        cv.load_state(state)
        self.assertEqual(len(cv.config.cutouts), 2)
        self.assertEqual(cv.config.cutouts[0].shape, "rect")
        self.assertAlmostEqual(cv.config.cutouts[0].x, 20.3)
        self.assertEqual(cv.config.cutouts[1].shape, "rounded_rect")
        self.assertAlmostEqual(cv.config.cutouts[1].corner_radius, 14.5)

        # Backwards compatibility: old project without cutouts
        del state["board"]["cutouts"]
        cv.load_state(state)
        self.assertEqual(cv.config.cutouts, [])

    def test_bottom_view_mirroring_and_partner_sync(self):
        cfg_top = BoardConfig(cols=10, rows=8, view_side="top")
        cfg_bot = BoardConfig(cols=10, rows=8, view_side="bottom")
        top_cv = CanvasView(cfg_top)
        bot_cv = CanvasView(cfg_bot, primary_view=top_cv)
        top_cv.link_partner(bot_cv)

        cutout = BoardCutout(shape="rect", x=30.0, y=40.0, w=50.0, h=25.0, uid="m1")
        top_cv.config.cutouts.append(cutout)
        top_cv._notify_partner_sync(full=False)

        self.assertEqual(len(bot_cv.config.cutouts), 1)
        bot_rect = bot_cv._cutout_display_rect(bot_cv.config.cutouts[0])
        self.assertAlmostEqual(bot_rect.left(), cfg_bot.width_px - 80.0)
        self.assertAlmostEqual(bot_rect.width(), 50.0)

        # Editing via bottom view display rect maps back to canonical top coords
        bot_cv._set_cutout_from_display_rect(bot_cv.config.cutouts[0], QRectF(10.0, 40.0, 50.0, 25.0))
        self.assertAlmostEqual(bot_cv.config.cutouts[0].x, cfg_bot.width_px - 60.0)

    def test_mode_ui_and_undo_redo(self):
        cfg = BoardConfig(cols=10, rows=8)
        cv = CanvasView(cfg)
        tb = ViewportToolbar()
        props = PropertiesWidget(cfg)

        tb.set_mode("shape")
        cv.set_mode("shape")
        props.set_mode("shape")

        self.assertEqual(tb.current_mode, "shape")
        self.assertEqual(cv.current_mode, "shape")
        self.assertTrue(cv.board_item.shape_mode_active)

        cv.config.cutouts.append(BoardCutout(shape="oval", x=25.0, y=25.0, w=50.0, h=50.0, uid="u1"))
        cv.record_undo_snapshot()
        self.assertEqual(len(cv.config.cutouts), 1)

        cv.remove_cutout_by_uid("u1")
        self.assertEqual(len(cv.config.cutouts), 0)

        cv.undo()
        self.assertEqual(len(cv.config.cutouts), 1)
        self.assertEqual(cv.config.cutouts[0].uid, "u1")

    def test_rotation_and_inverted_custom_shape(self):
        cfg = BoardConfig(cols=9, rows=9)
        cx, cy = cfg.grid_to_board_pos(4, 4, view_side="top")
        # Thin horizontal rect rotated 90 degrees becomes vertical, covering (4, 3) and (4, 5)
        rect = BoardCutout(
            shape="rect",
            x=cx - 40.0,
            y=cy - 10.0,
            w=80.0,
            h=20.0,
            rotation=90.0,
        )
        cfg.cutouts = [rect]
        self.assertFalse(cfg.is_valid_hole(4, 4))
        self.assertFalse(cfg.is_valid_hole(4, 3))
        self.assertTrue(cfg.is_valid_hole(3, 4))

        # Custom polygon (open < 3 vertices cannot cut; closed >= 3 vertices cuts; inverted cuts outside)
        p0 = cfg.grid_to_board_pos(2, 2, view_side="top")
        p1 = cfg.grid_to_board_pos(6, 2, view_side="top")
        p2 = cfg.grid_to_board_pos(6, 6, view_side="top")
        p3 = cfg.grid_to_board_pos(2, 6, view_side="top")
        open_poly = BoardCutout(shape="custom", vertices=[p0, p1])
        cfg.cutouts = [open_poly]
        self.assertTrue(cfg.is_valid_hole(4, 4))

        closed_poly = BoardCutout(
            shape="custom",
            vertices=[(p0[0] - 8, p0[1] - 8), (p1[0] + 8, p1[1] - 8), (p2[0] + 8, p2[1] + 8), (p3[0] - 8, p3[1] + 8)],
            inverted=True,
        )
        closed_poly.recompute_custom_bounds()
        cfg.cutouts = [closed_poly]
        self.assertTrue(cfg.is_valid_hole(4, 4))
        self.assertFalse(cfg.is_valid_hole(0, 0))
        self.assertFalse(cfg.is_valid_hole(8, 8))

    def test_custom_vertex_5px_snap_and_bevel_commit_cancel(self):
        cfg = BoardConfig(cols=10, rows=10)
        cv = CanvasView(cfg)
        cv.set_mode("shape")

        # At zoom 1.0, 3.0px delta is within 5 window pixels -> snaps
        cv._zoom_factor = 1.0
        sx, sy, guides = cv._snap_custom_vertex(103.0, 52.5, [(100.0, 50.0)])
        self.assertAlmostEqual(sx, 100.0)
        self.assertAlmostEqual(sy, 50.0)
        self.assertEqual(len(guides), 2)

        # Zoomed in 4x, 3.0 board px = 12 window px > 5px -> does not snap
        cv._zoom_factor = 4.0
        sx2, sy2, guides2 = cv._snap_custom_vertex(103.0, 52.5, [(100.0, 50.0)])
        self.assertAlmostEqual(sx2, 103.0)
        self.assertAlmostEqual(sy2, 52.5)
        self.assertEqual(guides2, [])

        # Bevel: sharp (segments=0 -> 2 pts) and smooth (segments=20 -> 22 pts)
        poly = BoardCutout(
            shape="custom",
            vertices=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
            uid="p1",
        )
        poly.recompute_custom_bounds()
        cv.config.cutouts = [poly]
        cv._select_cutout("p1")
        cv._select_vertex(1)
        cv._bevel_segments = 0
        self.assertTrue(cv._start_bevel())
        cv._update_bevel_preview(20.0)
        self.assertEqual(len(poly.vertices), 5)  # 4 - 1 + 2

        # Cancel restores original 4 vertices
        cv._cancel_bevel()
        self.assertEqual(len(poly.vertices), 4)

        # Smooth superellipse bevel (20 curve points -> 22 pts) and commit
        cv._select_vertex(1)
        cv._bevel_segments = 20
        self.assertTrue(cv._start_bevel())
        cv._update_bevel_preview(20.0)
        self.assertEqual(len(poly.vertices), 25)  # 4 - 1 + 22
        cv._commit_bevel()
        self.assertFalse(cv._bevel_active)
        self.assertEqual(len(poly.vertices), 25)

        # Asymmetric bevel limit: shorter edge stops at 98%, longer edge continues up to 98%
        asym = [(0.0, 50.0), (0.0, 0.0), (200.0, 0.0), (200.0, 50.0)]
        res_mid = CanvasView._compute_bevel_vertices(asym, 1, 120.0, 0)
        # Bevel vertex 1 -> indices 1 (on edge to (0, 50)) and 2 (on edge to (200, 0))
        self.assertAlmostEqual(res_mid[1][0], 0.0, places=5)
        self.assertAlmostEqual(res_mid[1][1], 50.0 * 0.98, places=5)
        self.assertAlmostEqual(res_mid[2][0], 120.0, places=5)
        self.assertAlmostEqual(res_mid[2][1], 0.0, places=5)
        res_max = CanvasView._compute_bevel_vertices(asym, 1, 300.0, 0)
        self.assertAlmostEqual(res_max[1][1], 50.0 * 0.98, places=5)
        self.assertAlmostEqual(res_max[2][0], 200.0 * 0.98, places=5)

        # Multi-vertex selection (Shift+click toggle) and simultaneous beveling
        cv._select_vertex(0, toggle=False)
        cv._select_vertex(1, toggle=True)
        cv._select_vertex(2, toggle=True)
        cv._select_vertex(2, toggle=True)  # toggle off
        self.assertEqual(cv.selected_vertex_indices, [0, 1])

        # Rectangle: (0, 50) [v0], (0, 0) [v1], (200, 0) [v2], (200, 50) [v3]
        # Bevel v0 and v1 simultaneously at radius=120:
        # Shared edge (v0-v1, len=50): both ends stop at 49% -> (0, 50*0.51) and (0, 50*0.49)
        # Edge v0->v3 (len=200, v3 stationary): v0 advances to 120.0 (<= 200*0.98)
        # Edge v1->v2 (len=200, v2 stationary): v1 advances to 120.0 (<= 200*0.98)
        multi = CanvasView._compute_multi_bevel_vertices(asym, [0, 1], 120.0, 0)
        self.assertEqual(len(multi), 6)  # 2 bevel pts for v0 + 2 bevel pts for v1 + v2 + v3
        self.assertAlmostEqual(multi[0][0], 120.0, places=5)
        self.assertAlmostEqual(multi[0][1], 50.0, places=5)
        self.assertAlmostEqual(multi[1][0], 0.0, places=5)
        self.assertAlmostEqual(multi[1][1], 50.0 * (1.0 - 0.49), places=5)
        self.assertAlmostEqual(multi[2][0], 0.0, places=5)
        self.assertAlmostEqual(multi[2][1], 50.0 * 0.49, places=5)
        self.assertAlmostEqual(multi[3][0], 120.0, places=5)
        self.assertAlmostEqual(multi[3][1], 0.0, places=5)

    def test_click_through_hits_inverted_oval_then_shapes_behind(self):
        cfg = BoardConfig(cols=10, rows=10)
        cv = CanvasView(cfg)
        c1 = BoardCutout(shape="rect", x=40.0, y=40.0, w=80.0, h=80.0, uid="r1")
        c2 = BoardCutout(shape="oval", x=50.0, y=50.0, w=60.0, h=60.0, uid="o1")
        c3 = BoardCutout(shape="inverted_oval", x=20.0, y=20.0, w=160.0, h=140.0, uid="io1")
        cv.config.cutouts = [c1, c2, c3]

        from PyQt6.QtCore import QPointF
        hits = cv._hit_test_cutouts(QPointF(80.0, 80.0))
        self.assertEqual([c.uid for c in hits], ["io1", "o1", "r1"])


if __name__ == "__main__":
    unittest.main()
