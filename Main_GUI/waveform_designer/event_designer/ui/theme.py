# theme.py
"""
Modern, minimal theme + QSS for the Haptic Waveform Designer.
Hover states now use soft gray instead of blue.
"""

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPalette, QColor

# Palette tokens
_ACCENT   = "#3B82F6"  # blue-500 (kept for focus/selection)
_ACCENT_D = "#1D4ED8"  # blue-700
_TEXT     = "#0F172A"  # slate-900
_SUBTEXT  = "#475569"  # slate-600
_BORDER   = "#E2E8F0"  # slate-200
_PANEL    = "#FFFFFF"
_CANVAS   = "#FAFBFC"
_ALT      = "#F8FAFC"
_PLACE    = "#94A3B8"
_DANGER   = "#EF4444"

# New: neutral hover tones
_HOVER_BG = "#F1F5F9"  # light gray hover
_HOVER_BG_D = "#E5E7EB"  # pressed/active gray
_HOVER_BORDER = "#CBD5E1"  # slightly darker border on hover

def apply_ultra_clean_theme(app: QApplication) -> None:
    try: app.setStyle("Fusion")
    except Exception: pass

    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,        QColor(_CANVAS))
    pal.setColor(QPalette.ColorRole.Base,          QColor(_PANEL))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(_ALT))
    pal.setColor(QPalette.ColorRole.Text,          QColor(_TEXT))
    pal.setColor(QPalette.ColorRole.WindowText,    QColor(_TEXT))
    pal.setColor(QPalette.ColorRole.ButtonText,    QColor(_TEXT))
    pal.setColor(QPalette.ColorRole.ToolTipText,   QColor(_PANEL))
    pal.setColor(QPalette.ColorRole.Button,        QColor(_PANEL))
    pal.setColor(QPalette.ColorRole.Highlight,     QColor(_ACCENT))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(_PLACE))
    pal.setColor(QPalette.ColorRole.BrightText,    QColor(_DANGER))
    app.setPalette(pal)

def load_ultra_clean_qss(app: QApplication) -> None:
    qss = f"""
    /* ---- Base ---- */
    * {{ outline: 0; }}
    QWidget {{
        background: {_CANVAS};
        color: {_TEXT};
        font-size: 13px;
        font-family: -apple-system, "SF Pro Text", "Segoe UI Variable", "Segoe UI",
                     Roboto, Inter, "Helvetica Neue", Arial, sans-serif;
    }}
    QLabel {{ color: {_SUBTEXT}; font-weight: 500; }}

    /* ---- Cards ---- */
    QGroupBox {{
        background: {_PANEL};
        border: 1px solid {_BORDER};
        border-radius: 10px;
        margin-top: 12px;
        padding: 10px 12px 12px 12px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 6px;
        color: {_TEXT};
        background: {_PANEL};
        font-weight: 700;
    }}

    /* ---- Inputs & Buttons ---- */
    QPushButton, QToolButton,
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit {{
        height: 28px;
        border: 1px solid {_BORDER};
        border-radius: 8px;
        background: #FFFFFF;
        padding: 0 10px;
        selection-background-color: {_ACCENT};
        selection-color: #FFFFFF;
    }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ color: {_TEXT}; }}

    /* Focus (keep accent for accessibility) */
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
    QDateEdit:focus, QTimeEdit:focus {{
        border: 2px solid {_ACCENT};
        padding: 0 9px;
    }}

    /* Buttons — neutral hover */
    QPushButton {{ font-weight: 600; color: {_TEXT}; }}
    QPushButton:hover {{ background: {_HOVER_BG}; border-color: {_HOVER_BORDER}; }}
    QPushButton:pressed {{ background: {_HOVER_BG_D}; }}
    QPushButton:disabled {{ color: {_PLACE}; border-color: {_BORDER}; background: #FFFFFF; }}

    /* Primary button (opt-in via objectName) */
    QPushButton#primaryButton {{
        background: {_ACCENT};
        border: 1px solid {_ACCENT};
        color: #FFFFFF;
    }}
    QPushButton#primaryButton:hover  {{ background: {_ACCENT_D}; border-color: {_ACCENT_D}; }}
    QPushButton#primaryButton:pressed{{ background: {_ACCENT_D}; }}

    /* Tool buttons — neutral hover */
    QToolButton {{ padding: 0 6px; border-radius: 6px; }}
    QToolButton:hover {{ background: {_HOVER_BG}; }}

    /* Combo popup */
    QComboBox::drop-down {{ border: 0; width: 18px; }}
    QComboBox QAbstractItemView {{
        background: #FFFFFF;
        border: 1px solid {_BORDER};
        border-radius: 8px;
        padding: 4px 0;
        selection-background-color: {_ACCENT}; /* selection remains accent */
        selection-color: #FFFFFF;
    }}
    /* Neutral hover rows in popups */
    QComboBox QAbstractItemView::item:hover {{
        background: {_HOVER_BG};
        color: {_TEXT};
    }}

    /* Spin arrows */
    QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
        width: 16px; border: 0; margin: 0;
    }}

    /* ---- Tabs ---- */
    QTabWidget::pane {{
        border: 1px solid {_BORDER};
        border-radius: 10px;
        background: #FFFFFF;
    }}
    QTabBar::tab {{
        border: 1px solid {_BORDER};
        border-bottom: none;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
        padding: 7px 14px;
        margin-right: 2px;
        background: #F8FAFC;
        color: {_SUBTEXT};
        font-weight: 600;
    }}
    QTabBar::tab:selected {{
        background: #FFFFFF;
        color: {_TEXT};
    }}
    /* Neutral tab hover */
    QTabBar::tab:hover {{
        background: {_HOVER_BG};
        color: {_TEXT};
    }}

    /* ---- Lists / Trees / Text ---- */
    QListWidget, QTreeWidget, QTextEdit, QPlainTextEdit {{
        background: #FFFFFF;
        border: 1px solid {_BORDER};
        border-radius: 8px;
        padding: 8px;
    }}
    /* Neutral row hover */
    QListView::item:hover, QTreeView::item:hover, QTableView::item:hover {{
        background: {_HOVER_BG};
        color: {_TEXT};
    }}

    /* ---- Tables ---- */
    QTableView {{
        background: #FFFFFF;
        border: 1px solid {_BORDER};
        border-radius: 8px;
        gridline-color: {_BORDER};
        selection-background-color: {_ACCENT};
        selection-color: #FFFFFF;
    }}
    QHeaderView::section {{
        background: #F8FAFC;
        color: {_SUBTEXT};
        border: 1px solid {_BORDER};
        padding: 6px 8px;
        font-weight: 600;
    }}

    /* ---- Sliders ---- */
    QSlider::groove:horizontal {{
        height: 4px; background: {_BORDER}; border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        width: 16px; height: 16px; margin: -6px 0;
        border-radius: 8px; background: {_ACCENT};
    }}
    QSlider::handle:horizontal:hover {{ background: {_ACCENT}; }}  /* no color jump on hover */

    /* ---- Checks / Radios ---- */
    QCheckBox, QRadioButton {{ spacing: 8px; }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 16px; height: 16px; border: 1px solid {_BORDER};
        border-radius: 3px; background: #FFFFFF;
    }}
    QRadioButton::indicator {{ border-radius: 8px; }}
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
        border-color: {_ACCENT}; background: {_ACCENT};
    }}

    /* ---- Splitter ---- */
    QSplitter::handle {{ background: {_BORDER}; width: 4px; height: 4px; border-radius: 2px; }}
    QSplitter::handle:hover {{ background: {_HOVER_BG}; }}

    /* ---- Scrollbars ---- */
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: #CBD5E1; border-radius: 5px; min-height: 28px; }}
    QScrollBar::handle:vertical:hover {{ background: #A7B4C6; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: #CBD5E1; border-radius: 5px; min-width: 28px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}

    /* ---- Menus ---- */
    QMenu {{
        background: #FFFFFF;
        border: 1px solid {_BORDER};
        border-radius: 8px;
        padding: 6px 0;
    }}
    QMenu::item {{
        padding: 6px 12px;
        border-radius: 6px;
        color: {_TEXT};
    }}
    /* Neutral hover/selection in menus */
    QMenu::item:selected {{
        background: {_HOVER_BG};
        color: {_TEXT};
    }}

    /* ---- Tooltips / Status ---- */
    QToolTip {{
        background: {_TEXT};
        color: #FFFFFF;
        border: 0;
        padding: 6px 8px;
        border-radius: 6px;
        opacity: 220;
    }}
    QStatusBar {{
        background: {_PANEL};
        border: 1px solid {_BORDER};
        border-radius: 8px;
        padding: 4px 8px;
    }}

    /* ---- Progress ---- */
    QProgressBar {{
        border: 1px solid {_BORDER};
        border-radius: 8px;
        background: #FFFFFF;
        padding: 2px;
        text-align: center;
    }}
    QProgressBar::chunk {{
        background-color: {_ACCENT};
        border-radius: 6px;
    }}
    """
    app.setStyleSheet(qss)
