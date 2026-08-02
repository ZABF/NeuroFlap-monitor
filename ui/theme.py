"""Application theme and color-contrast helpers for the Monitor UI."""

import colorsys

import pyqtgraph as pg
from PyQt5.QtGui import QColor, QPalette


WINDOW_BG = (22, 24, 29)
PANEL_BG = (32, 36, 43)
INPUT_BG = (41, 46, 54)
PLOT_BG = (9, 11, 14)
BORDER = (63, 71, 82)
TEXT = (229, 231, 235)
TEXT_MUTED = (156, 163, 175)
ERROR = (255, 107, 107)
WARNING = (245, 185, 66)
SUCCESS = (88, 214, 141)
ACCENT = (78, 161, 255)
CURVE_OUTLINE = (220, 224, 230, 145)
SECTION_DERIVED = (245, 185, 66)
SECTION_DATAFLOW = (255, 107, 107)
SECTION_BUSINESS = (185, 133, 255)
SECTION_DEVICE = (88, 214, 141)
SECTION_SYSTEM = (78, 161, 255)


def _hex(rgb):
    return "#{:02X}{:02X}{:02X}".format(*rgb[:3])


WINDOW_BG_HEX = _hex(WINDOW_BG)
PANEL_BG_HEX = _hex(PANEL_BG)
INPUT_BG_HEX = _hex(INPUT_BG)
PLOT_BG_HEX = _hex(PLOT_BG)
BORDER_HEX = _hex(BORDER)
TEXT_HEX = _hex(TEXT)
TEXT_MUTED_HEX = _hex(TEXT_MUTED)
ERROR_HEX = _hex(ERROR)


def _linear_channel(value):
    value = max(0.0, min(1.0, float(value) / 255.0))
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb):
    red, green, blue = (_linear_channel(channel) for channel in rgb[:3])
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground, background):
    lighter = max(relative_luminance(foreground), relative_luminance(background))
    darker = min(relative_luminance(foreground), relative_luminance(background))
    return (lighter + 0.05) / (darker + 0.05)


def readable_curve_text_color(rgb, background=PANEL_BG, minimum_ratio=4.5):
    """Keep the curve hue while raising lightness enough for readable text."""
    rgb = tuple(max(0, min(255, int(channel))) for channel in rgb[:3])
    if contrast_ratio(rgb, background) >= minimum_ratio:
        return rgb

    hue, lightness, saturation = colorsys.rgb_to_hls(
        rgb[0] / 255.0,
        rgb[1] / 255.0,
        rgb[2] / 255.0,
    )
    for step in range(1, 101):
        candidate_lightness = lightness + (1.0 - lightness) * step / 100.0
        candidate = tuple(
            round(channel * 255.0)
            for channel in colorsys.hls_to_rgb(hue, candidate_lightness, saturation)
        )
        if contrast_ratio(candidate, background) >= minimum_ratio:
            return candidate
    return TEXT


def curve_needs_outline(rgb, background=PLOT_BG, minimum_ratio=3.0):
    return contrast_ratio(rgb, background) < minimum_ratio


def curve_label_style(rgb, selector=None):
    text_rgb = readable_curve_text_color(rgb)
    body = f"color: rgb{text_rgb};"
    return f"{selector} {{ {body} }}" if selector else body


def set_semantic_state(widget, state):
    widget.setProperty("semanticState", state or "")
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def set_section_kind(widget, kind):
    widget.setProperty("sectionKind", str(kind or "").lower())
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


DARK_STYLESHEET = f"""
QWidget {{
    background-color: {WINDOW_BG_HEX};
    color: {TEXT_HEX};
}}
QGroupBox {{
    background-color: {PANEL_BG_HEX};
    border: 1px solid {BORDER_HEX};
    margin-top: 8px;
    padding-top: 5px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 6px;
    padding: 0 3px;
    background-color: {PANEL_BG_HEX};
}}
QGroupBox[sectionKind="derived"] {{ border: 2px solid {_hex(SECTION_DERIVED)}; }}
QGroupBox[sectionKind="dataflow"] {{ border: 2px solid {_hex(SECTION_DATAFLOW)}; }}
QGroupBox[sectionKind="business"] {{ border: 2px solid {_hex(SECTION_BUSINESS)}; }}
QGroupBox[sectionKind="device"] {{ border: 2px solid {_hex(SECTION_DEVICE)}; }}
QGroupBox[sectionKind="system"] {{ border: 2px solid {_hex(SECTION_SYSTEM)}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {INPUT_BG_HEX};
    color: {TEXT_HEX};
    border: 1px solid {BORDER_HEX};
    padding: 2px 4px;
    selection-background-color: {_hex((42, 91, 139))};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {_hex(ACCENT)};
}}
QCheckBox {{ spacing: 4px; }}
QCheckBox::indicator {{ width: 14px; height: 14px; }}
QCheckBox::indicator:unchecked {{
    background-color: {INPUT_BG_HEX};
    border: 1px solid {_hex((104, 115, 130))};
    border-radius: 2px;
}}
QCheckBox::indicator:unchecked:hover {{ border-color: {_hex(ACCENT)}; }}
QComboBox QAbstractItemView, QMenu {{
    background-color: {INPUT_BG_HEX};
    color: {TEXT_HEX};
    border: 1px solid {BORDER_HEX};
    selection-background-color: {_hex((42, 91, 139))};
}}
QPushButton {{
    background-color: {_hex((52, 58, 67))};
    color: {TEXT_HEX};
    border: 1px solid {BORDER_HEX};
    padding: 4px 8px;
}}
QPushButton:hover {{ background-color: {_hex((64, 72, 83))}; }}
QPushButton:pressed {{ background-color: {_hex((43, 49, 57))}; }}
QPushButton:disabled {{ color: {_hex((108, 115, 126))}; background-color: {_hex((38, 42, 49))}; }}
QPushButton[semanticState="warning"] {{ background-color: {_hex((126, 85, 12))}; }}
QPushButton[semanticState="active"] {{ background-color: {_hex((31, 110, 74))}; }}
QPushButton[semanticState="accent"] {{ background-color: {_hex((29, 93, 115))}; }}
QPushButton[semanticState="inactive"] {{ background-color: {_hex((52, 58, 67))}; }}
QLabel[semanticState="success"] {{ color: {_hex(SUCCESS)}; }}
QLabel[semanticState="warning"] {{ color: {_hex(WARNING)}; }}
QLabel[semanticState="error"] {{ color: {_hex(ERROR)}; }}
QLabel[semanticState="muted"] {{ color: {TEXT_MUTED_HEX}; }}
QTabWidget::pane {{
    border: 1px solid {BORDER_HEX};
    background-color: {PANEL_BG_HEX};
}}
QTabBar::tab {{
    background-color: {INPUT_BG_HEX};
    color: {TEXT_MUTED_HEX};
    border: 1px solid {BORDER_HEX};
    border-bottom: 1px solid {BORDER_HEX};
    border-top-left-radius: 3px;
    border-top-right-radius: 3px;
    padding: 7px 14px;
    margin-right: 2px;
}}
QTabBar::tab:hover {{ background-color: {_hex((52, 58, 67))}; color: {TEXT_HEX}; }}
QTabBar::tab:selected {{
    background-color: {PANEL_BG_HEX};
    color: {TEXT_HEX};
    border-top: 2px solid {_hex(ACCENT)};
    border-bottom: 1px solid {PANEL_BG_HEX};
}}
QScrollArea, QScrollArea > QWidget > QWidget {{ background-color: {PANEL_BG_HEX}; }}
QHeaderView::section {{ background-color: {INPUT_BG_HEX}; color: {TEXT_HEX}; border: 1px solid {BORDER_HEX}; }}
QToolTip {{ background-color: {INPUT_BG_HEX}; color: {TEXT_HEX}; border: 1px solid {BORDER_HEX}; }}
"""


def apply_dark_theme(app):
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(*WINDOW_BG))
    palette.setColor(QPalette.WindowText, QColor(*TEXT))
    palette.setColor(QPalette.Base, QColor(*INPUT_BG))
    palette.setColor(QPalette.AlternateBase, QColor(*PANEL_BG))
    palette.setColor(QPalette.ToolTipBase, QColor(*INPUT_BG))
    palette.setColor(QPalette.ToolTipText, QColor(*TEXT))
    palette.setColor(QPalette.Text, QColor(*TEXT))
    palette.setColor(QPalette.Button, QColor(52, 58, 67))
    palette.setColor(QPalette.ButtonText, QColor(*TEXT))
    palette.setColor(QPalette.BrightText, QColor(*ERROR))
    palette.setColor(QPalette.Link, QColor(*ACCENT))
    palette.setColor(QPalette.Highlight, QColor(42, 91, 139))
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(108, 115, 126))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(108, 115, 126))
    app.setPalette(palette)
    app.setStyleSheet(DARK_STYLESHEET)
    pg.setConfigOption("background", PLOT_BG_HEX)
    pg.setConfigOption("foreground", TEXT_HEX)
