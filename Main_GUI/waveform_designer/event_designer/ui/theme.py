# theme.py
"""
Dark theme matching the main interface colors.
Deep slate colors with blue accents.
"""

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPalette, QColor

# Dark theme palette tokens
_APP_BG      = "#0D1117"  # Main app background
_SURFACE     = "#121826"  # Panel/card background
_SURFACE_ALT = "#151B24"  # Alternative surface
_TEXT        = "#E5E7EB"  # Normal text
_TEXT_MUTED  = "#A7B0C0"  # Muted text
_BORDER      = "#2B3446"  # Normal borders
_BORDER_HOVER= "#3A455A"  # Hover borders
_PRIMARY     = "#1E3A8A"  # Primary blue
_PRIMARY_HOVER="#1D4ED8"  # Primary hover
_FOCUS       = "#2563EB"  # Focus ring
_HOVER_BG    = "#1B2331"  # Hover background
_SELECTION   = "#1F2F4D"  # Selection background
_DANGER      = "#DC2626"  # Danger/error
_SUCCESS     = "#16A34A"  # Success
_WARNING     = "#D97706"  # Warning

def apply_ultra_clean_theme(app: QApplication) -> None:
    try: app.setStyle("Fusion")
    except Exception: pass

    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,        QColor(_APP_BG))
    pal.setColor(QPalette.ColorRole.Base,          QColor(_SURFACE))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(_SURFACE_ALT))
    pal.setColor(QPalette.ColorRole.Text,          QColor(_TEXT))
    pal.setColor(QPalette.ColorRole.WindowText,    QColor(_TEXT))
    pal.setColor(QPalette.ColorRole.ButtonText,    QColor(_TEXT))
    pal.setColor(QPalette.ColorRole.ToolTipText,   QColor(_TEXT))
    pal.setColor(QPalette.ColorRole.Button,        QColor(_SURFACE))
    pal.setColor(QPalette.ColorRole.Highlight,     QColor(_PRIMARY))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(_TEXT_MUTED))
    pal.setColor(QPalette.ColorRole.BrightText,    QColor(_DANGER))
    app.setPalette(pal)

def load_ultra_clean_qss(app: QApplication) -> None:
    qss = f"""
    /* ---- Base ---- */
    * {{ outline: 0; }}
    QWidget {{
        background: {_APP_BG};
        color: {_TEXT};
        font-size: 13px;
        font-family: -apple-system, "SF Pro Text", "Segoe UI Variable", "Segoe UI",
                     Roboto, Inter, "Helvetica Neue", Arial, sans-serif;
    }}
    QLabel {{ color: {_TEXT}; font-weight: 500; }}

    /* ---- Cards ---- */
    QGroupBox {{
        background: {_SURFACE};
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
        background: {_SURFACE};
        font-weight: 700;
    }}

    /* ---- Inputs & Buttons ---- */
    QPushButton, QToolButton,
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit {{
        height: 28px;
        border: 1px solid {_BORDER_HOVER};
        border-radius: 8px;
        background: {_SURFACE_ALT};
        padding: 0 10px;
        color: {_TEXT};
        selection-background-color: {_SELECTION};
        selection-color: {_TEXT};
    }}

    /* Focus */
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
    QDateEdit:focus, QTimeEdit:focus {{
        border: 2px solid {_FOCUS};
        padding: 0 9px;
    }}

    /* Buttons */
    QPushButton {{ font-weight: 600; color: {_TEXT}; background: {_SURFACE}; }}
    QPushButton:hover {{ background: {_HOVER_BG}; border-color: {_BORDER_HOVER}; }}
    QPushButton:pressed {{ background: {_SURFACE_ALT}; }}
    QPushButton:disabled {{ color: {_TEXT_MUTED}; border-color: {_BORDER}; background: {_SURFACE}; }}

    /* Primary button */
    QPushButton#primaryButton {{
        background: {_PRIMARY};
        border: 1px solid {_PRIMARY};
        color: #FFFFFF;
    }}
    QPushButton#primaryButton:hover  {{ background: {_PRIMARY_HOVER}; border-color: {_PRIMARY_HOVER}; }}
    QPushButton#primaryButton:pressed{{ background: {_PRIMARY_HOVER}; }}

    /* Tool buttons */
    QToolButton {{ padding: 0 6px; border-radius: 6px; background: {_SURFACE}; }}
    QToolButton:hover {{ background: {_HOVER_BG}; }}
    QToolButton:checked {{ background: {_SELECTION}; border-color: {_FOCUS}; }}

    /* Combo popup */
    QComboBox::drop-down {{ border: 0; width: 18px; background: {_SURFACE}; }}
    QComboBox QAbstractItemView {{
        background: {_SURFACE_ALT};
        border: 1px solid {_BORDER};
        border-radius: 8px;
        padding: 4px 0;
        selection-background-color: {_SELECTION};
        selection-color: {_TEXT};
    }}
    QComboBox QAbstractItemView::item:hover {{
        background: {_HOVER_BG};
        color: {_TEXT};
    }}

    /* Spin arrows */
    QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
        width: 16px; border: 0; margin: 0; background: {_SURFACE};
    }}
    QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{
        background: {_HOVER_BG};
    }}

    /* ---- Tabs ---- */
    QTabWidget::pane {{
        border: 1px solid {_BORDER};
        border-radius: 10px;
        background: {_SURFACE};
    }}
    QTabBar::tab {{
        border: 1px solid {_BORDER};
        border-bottom: none;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
        padding: 7px 14px;
        margin-right: 2px;
        background: {_SURFACE_ALT};
        color: {_TEXT_MUTED};
        font-weight: 600;
    }}
    QTabBar::tab:selected {{
        background: {_SURFACE};
        color: {_TEXT};
        border-bottom: 1px solid {_SURFACE};
    }}
    QTabBar::tab:hover {{
        background: {_HOVER_BG};
        color: {_TEXT};
    }}

    /* ---- Lists / Trees / Text ---- */
    QListWidget, QTreeWidget, QTextEdit, QPlainTextEdit {{
        background: {_SURFACE_ALT};
        border: 1px solid {_BORDER};
        border-radius: 8px;
        padding: 8px;
        color: {_TEXT};
    }}
    QListView::item:hover, QTreeView::item:hover, QTableView::item:hover {{
        background: {_HOVER_BG};
        color: {_TEXT};
    }}
    QListView::item:selected, QTreeView::item:selected {{
        background: {_SELECTION};
        color: {_TEXT};
    }}

    /* ---- Tables ---- */
    QTableView {{
        background: {_SURFACE_ALT};
        border: 1px solid {_BORDER};
        border-radius: 8px;
        gridline-color: {_BORDER};
        selection-background-color: {_SELECTION};
        selection-color: {_TEXT};
        alternate-background-color: {_SURFACE};
    }}
    QHeaderView::section {{
        background: {_SURFACE};
        color: {_TEXT_MUTED};
        border: 1px solid {_BORDER};
        padding: 6px 8px;
        font-weight: 600;
    }}

    /* ---- Sliders ---- */
    QSlider::groove:horizontal {{
        height: 8px; background: {_BORDER}; border-radius: 4px;
    }}
    QSlider::handle:horizontal {{
        width: 20px; height: 20px; margin: -6px 0;
        border-radius: 10px; background: {_PRIMARY};
        border: 2px solid {_APP_BG};
    }}
    QSlider::handle:horizontal:hover {{ background: {_PRIMARY_HOVER}; }}

    /* ---- Checks / Radios ---- */
    QCheckBox, QRadioButton {{ spacing: 8px; color: {_TEXT}; }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 16px; height: 16px; border: 1px solid {_BORDER_HOVER};
        border-radius: 4px; background: {_SURFACE_ALT};
    }}
    QRadioButton::indicator {{ border-radius: 8px; }}
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
        border-color: {_PRIMARY}; background: {_PRIMARY};
    }}
    QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
        background: {_HOVER_BG};
    }}

    /* ---- Splitter ---- */
    QSplitter::handle {{ background: {_BORDER}; width: 6px; height: 6px; border-radius: 3px; }}
    QSplitter::handle:hover {{ background: {_BORDER_HOVER}; }}

    /* ---- Scrollbars ---- */
    QScrollBar:vertical {{ background: {_SURFACE}; width: 12px; margin: 2px; border-radius: 6px; }}
    QScrollBar::handle:vertical {{ background: {_BORDER_HOVER}; border-radius: 6px; min-height: 28px; }}
    QScrollBar::handle:vertical:hover {{ background: {_TEXT_MUTED}; }}
    QScrollBar:horizontal {{ background: {_SURFACE}; height: 12px; margin: 2px; border-radius: 6px; }}
    QScrollBar::handle:horizontal {{ background: {_BORDER_HOVER}; border-radius: 6px; min-width: 28px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}

    /* ---- Menus ---- */
    QMenu {{
        background: {_SURFACE_ALT};
        border: 1px solid {_BORDER};
        border-radius: 8px;
        padding: 6px 0;
    }}
    QMenu::item {{
        padding: 6px 12px;
        border-radius: 6px;
        color: {_TEXT};
    }}
    QMenu::item:selected {{
        background: {_SELECTION};
        color: {_TEXT};
    }}

    /* ---- Tooltips / Status ---- */
    QToolTip {{
        background: {_SURFACE_ALT};
        color: {_TEXT};
        border: 1px solid {_BORDER};
        padding: 6px 8px;
        border-radius: 6px;
    }}
    QStatusBar {{
        background: {_SURFACE};
        border-top: 1px solid {_BORDER};
        padding: 4px 8px;
        color: {_TEXT_MUTED};
    }}

    /* ---- Progress ---- */
    QProgressBar {{
        border: 1px solid {_BORDER};
        border-radius: 8px;
        background: {_SURFACE_ALT};
        padding: 2px;
        text-align: center;
        color: {_TEXT};
    }}
    QProgressBar::chunk {{
        background-color: {_PRIMARY};
        border-radius: 6px;
    }}

    /* ---- Graphics View ---- */
    QGraphicsView {{
        border: none;
        background: {_APP_BG};
    }}

    /* ---- Canvas specific ---- */
    QWidget#ActuatorCanvas {{
        background: {_APP_BG};
    }}
    """
    app.setStyleSheet(qss)