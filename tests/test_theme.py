import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QPushButton

from ui.theme import (
    DARK_STYLESHEET,
    PANEL_BG,
    PLOT_BG,
    SECTION_BUSINESS,
    SECTION_DATAFLOW,
    SECTION_DERIVED,
    SECTION_DEVICE,
    SECTION_SYSTEM,
    TEXT,
    WINDOW_BG,
    _hex,
    apply_dark_theme,
    contrast_ratio,
    curve_needs_outline,
    readable_curve_text_color,
    set_semantic_state,
)


class ThemeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_curve_text_is_brightened_only_when_needed(self):
        dark = (10, 20, 30)
        bright = (255, 240, 0)

        adjusted = readable_curve_text_color(dark)
        self.assertGreaterEqual(contrast_ratio(adjusted, PANEL_BG), 4.5)
        self.assertEqual(readable_curve_text_color(bright), bright)

    def test_curve_outline_threshold_uses_plot_background(self):
        self.assertTrue(curve_needs_outline(PLOT_BG))
        self.assertFalse(curve_needs_outline((255, 240, 0)))

    def test_application_palette_and_semantic_state_are_dark(self):
        apply_dark_theme(self.app)
        window_rgb = self.app.palette().window().color().getRgb()[:3]
        text_rgb = self.app.palette().windowText().color().getRgb()[:3]
        self.assertEqual(window_rgb, WINDOW_BG)
        self.assertEqual(text_rgb, TEXT)

        button = QPushButton("Connect")
        set_semantic_state(button, "warning")
        self.assertEqual(button.property("semanticState"), "warning")

    def test_section_kinds_use_full_colored_borders(self):
        for kind, color in (
            ("derived", SECTION_DERIVED),
            ("dataflow", SECTION_DATAFLOW),
            ("business", SECTION_BUSINESS),
            ("device", SECTION_DEVICE),
            ("system", SECTION_SYSTEM),
        ):
            selector = f'QGroupBox[sectionKind="{kind}"]'
            rule = f"{selector} {{ border: 2px solid {_hex(color)}; }}"
            self.assertIn(rule, DARK_STYLESHEET)
        self.assertNotIn("border-top: 3px solid", DARK_STYLESHEET)


if __name__ == "__main__":
    unittest.main()
