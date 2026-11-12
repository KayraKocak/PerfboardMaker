import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from app.views.toolbox_widget import ToolboxWidget


class ToolboxCategoriesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_categories_collapse_expand_and_search_expands_matches(self):
        toolbox = ToolboxWidget()
        try:
            self.assertGreater(len(toolbox._category_sections), 0)
            cat, section = next(iter(toolbox._category_sections.items()))
            self.assertFalse(section.is_collapsed())
            self.assertFalse(section.content.isHidden())

            # Collapse category via header button
            section.header_btn.click()
            self.assertTrue(section.is_collapsed())
            self.assertTrue(section.content.isHidden())
            self.assertIn(cat, toolbox._collapsed_categories)

            # Filtering with a matching query expands the matching category temporarily
            first_comp = next(c for c, _, sec in toolbox.cards if sec is section)
            toolbox._filter_components(first_comp.name)
            self.assertFalse(section.isHidden())
            self.assertFalse(section.is_collapsed())
            self.assertFalse(section.content.isHidden())

            # Clearing the search restores user-collapsed state
            toolbox._filter_components("")
            self.assertTrue(section.is_collapsed())
            self.assertTrue(section.content.isHidden())

            # Re-expanding via header button persists
            section.header_btn.click()
            self.assertFalse(section.is_collapsed())
            self.assertNotIn(cat, toolbox._collapsed_categories)
        finally:
            toolbox.deleteLater()


if __name__ == "__main__":
    unittest.main()
