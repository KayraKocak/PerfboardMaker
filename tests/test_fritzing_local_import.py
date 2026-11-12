import os
import tempfile
import unittest
import zipfile
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from app.components.registry import REGISTRY
from app.utils.fritzing_importer import _MAX_LOCAL_FILE_BYTES, import_fritzing_file
from app.views.toolbox_widget import ToolboxWidget


def _make_fzp(title: str, image_attr: str) -> bytes:
    return f"""<?xml version='1.0' encoding='UTF-8'?>
<module moduleId="{title}_id">
  <title>{title}</title>
  <label>U</label>
  <author>Test Author</author>
  <views>
    <breadboardView>
      <layers image="{image_attr}">
        <layer layerId="breadboard"/>
      </layers>
    </breadboardView>
  </views>
  <connectors>
    <connector id="connector0" name="P1" type="male">
      <views>
        <breadboardView>
          <p layer="breadboard" svgId="connector0pin"/>
        </breadboardView>
      </views>
    </connector>
    <connector id="connector1" name="P2" type="male">
      <views>
        <breadboardView>
          <p layer="breadboard" svgId="connector1pin"/>
        </breadboardView>
      </views>
    </connector>
  </connectors>
</module>
""".encode("utf-8")


def _make_svg() -> bytes:
    return b"""<svg xmlns="http://www.w3.org/2000/svg" width="5.08mm" height="2.54mm" viewBox="0 0 5.08 2.54">
  <g id="breadboard">
    <circle id="connector0pin" cx="1.27" cy="1.27" r="0.4"/>
    <circle id="connector1pin" cx="3.81" cy="1.27" r="0.4"/>
  </g>
</svg>
"""


class FritzingLocalImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_import_fzpz_valid_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            fzpz_path = os.path.join(tmp, "TwoPinPart.fzpz")
            with zipfile.ZipFile(fzpz_path, "w") as zf:
                zf.writestr("part.two_pin.fzp", _make_fzp("Two Pin Part", "breadboard/two_pin.svg"))
                zf.writestr("svg.breadboard.two_pin.svg", _make_svg())

            comp, err = import_fritzing_file(fzpz_path)
            self.assertIsNone(err)
            self.assertIsNotNone(comp)
            self.assertEqual(comp.name, "Two Pin Part")
            self.assertEqual(len(comp.pins), 2)
            self.assertEqual(comp.source_info["source_name"], "Local")
            self.assertEqual(comp.source_info["license"], "Unknown")
            self.assertEqual(comp.source_info["url"], "")

    def test_import_loose_fzp_in_nested_pdb_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            fzp_dir = os.path.join(tmp, "pdb", "core")
            svg_dir = os.path.join(tmp, "svg", "core", "breadboard")
            os.makedirs(fzp_dir)
            os.makedirs(svg_dir)

            fzp_path = os.path.join(fzp_dir, "nested_part.fzp")
            svg_path = os.path.join(svg_dir, "nested_part.svg")
            with open(fzp_path, "wb") as f:
                f.write(_make_fzp("Nested Part", "breadboard/nested_part.svg"))
            with open(svg_path, "wb") as f:
                f.write(_make_svg())

            comp, err = import_fritzing_file(fzp_path)
            self.assertIsNone(err)
            self.assertIsNotNone(comp)
            self.assertEqual(comp.name, "Nested Part")

    def test_rejects_path_traversal_and_bad_extensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad_ext = os.path.join(tmp, "part.txt")
            with open(bad_ext, "wb") as f:
                f.write(b"hello")
            comp, err = import_fritzing_file(bad_ext)
            self.assertIsNone(comp)
            self.assertIn("Unsupported file type", err)

            secret_svg = os.path.join(tmp, "secret.svg")
            with open(secret_svg, "wb") as f:
                f.write(_make_svg())
            sub = os.path.join(tmp, "parts")
            os.makedirs(sub)
            fzp_path = os.path.join(sub, "evil.fzp")
            with open(fzp_path, "wb") as f:
                f.write(_make_fzp("Evil", "../secret.svg"))
            comp, err = import_fritzing_file(fzp_path)
            self.assertIsNone(comp)
            self.assertIn("Unsafe breadboard SVG path", err)

    def test_rejects_oversized_zip_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            fzpz_path = os.path.join(tmp, "big.fzpz")
            with zipfile.ZipFile(fzpz_path, "w") as zf:
                zf.writestr("part.big.fzp", _make_fzp("Big", "breadboard/big.svg"))
                zf.writestr("svg.breadboard.big.svg", _make_svg())

            with patch("app.utils.fritzing_importer._MAX_LOCAL_FILE_BYTES", 10):
                comp, err = import_fritzing_file(fzpz_path)
            self.assertIsNone(comp)
            self.assertIn("too large", err)

    def test_toolbox_partial_import_reports_both_success_and_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            good_path = os.path.join(tmp, "GoodPart.fzpz")
            with zipfile.ZipFile(good_path, "w") as zf:
                zf.writestr("part.good.fzp", _make_fzp("Good Part", "breadboard/good.svg"))
                zf.writestr("svg.breadboard.good.svg", _make_svg())
            bad_path = os.path.join(tmp, "bad.txt")
            with open(bad_path, "wb") as f:
                f.write(b"not a part")

            toolbox = ToolboxWidget()
            saved_calls = []

            def fake_persist(type_id):
                comp = REGISTRY._previews.get(type_id)
                if comp:
                    REGISTRY.register(comp)
                    saved_calls.append(type_id)
                    return True
                return False

            try:
                with (
                    patch("app.views.toolbox_widget.QFileDialog.getOpenFileNames", return_value=([good_path, bad_path], "")),
                    patch.object(REGISTRY, "persist_if_remote", side_effect=fake_persist),
                    patch("app.views.toolbox_widget.QMessageBox.warning") as mock_warn,
                    patch("app.views.toolbox_widget.QMessageBox.information") as mock_info,
                ):
                    toolbox._on_import_file_clicked()

                self.assertEqual(len(saved_calls), 1)
                self.assertEqual(mock_info.call_count, 0)
                self.assertEqual(mock_warn.call_count, 1)
                msg = mock_warn.call_args.args[2]
                self.assertIn("Imported:\nGood Part", msg)
                self.assertIn("Failed:\nbad.txt:", msg)
            finally:
                for tid in saved_calls:
                    REGISTRY._components.pop(tid, None)
                    REGISTRY._previews.pop(tid, None)
                toolbox.deleteLater()


if __name__ == "__main__":
    unittest.main()
