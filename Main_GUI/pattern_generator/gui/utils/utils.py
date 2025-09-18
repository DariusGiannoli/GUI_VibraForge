from typing import Optional
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QVBoxLayout, QScrollArea, QFrame, QGroupBox, QWidget, QMessageBox


def _make_widget_scrollable_in_place(page: QWidget) -> QScrollArea:
    """
    Wrap the *current contents* of `page` in a QScrollArea without changing the
    page itself (so setCurrentWidget(page) etc. continue to work).
    """
    outer = page.layout()
    if outer is None:
        outer = QVBoxLayout(page)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

    # If we've already wrapped it, return the existing scroll area.
    for i in range(outer.count()):
        w = outer.itemAt(i).widget()
        if isinstance(w, QScrollArea):
            return w

    # Move all existing layout items into a new content widget
    content = QWidget(page)
    content.setObjectName("DrawingStudioContent")
    content_layout = QVBoxLayout(content)
    content_layout.setContentsMargins(0, 0, 0, 0)
    content_layout.setSpacing(8)

    # Take items out of the outer layout (widgets, sub-layouts, spacers)
    items = []
    while outer.count():
        items.append(outer.takeAt(0))
    for it in items:
        if it.widget() is not None:
            w = it.widget()
            w.setParent(None)
            content_layout.addWidget(w)
        elif it.layout() is not None:
            content_layout.addLayout(it.layout())
        elif it.spacerItem() is not None:
            content_layout.addSpacerItem(it.spacerItem())

    scroll = QScrollArea(page)
    scroll.setObjectName("DrawingStudioScrollArea")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setWidget(content)

    outer.addWidget(scroll)
    return scroll


def _find_drawn_stroke_group(root: QWidget) -> QGroupBox | None:
    """
    Try hard to find the existing 'Drawn Stroke Playback' group.
    Prefer an objectName if present; otherwise match by group title.
    """
    # 1) By objectName (recommended in your code)
    gb = root.findChild(QGroupBox, "DrawnStrokePlaybackGroup")
    if gb:
        return gb

    # 2) Fallback: scan all QGroupBox by title
    for g in root.findChildren(QGroupBox):
        try:
            if g.title().strip().lower().startswith("drawn stroke playback"):
                g.setObjectName("DrawnStrokePlaybackGroup")
                return g
        except Exception:
            pass
    return None


def _add_widget_to_drawing_tab_end(gui, w: QWidget) -> None:
    """
    Append `w` at the end of the Drawing tab content (inside the scroll area).
    """
    drawing_tab = getattr(gui, "drawing_tab", None)
    if drawing_tab is None:
        QMessageBox.information(gui, "Drawing Studio", "Drawing tab not found.")
        return

    scroll = _make_widget_scrollable_in_place(drawing_tab)
    content = scroll.widget()                      # QWidget
    content_layout = content.layout()              # QVBoxLayout
    # Try to put the group near the bottom, but before a trailing stretch/spacer if any
    inserted = False
    for i in reversed(range(content_layout.count())):
        item = content_layout.itemAt(i)
        if item.spacerItem() is not None:
            content_layout.insertWidget(max(0, i), w)
            inserted = True
            break
    if not inserted:
        content_layout.addWidget(w)


def centralize_drawn_stroke_playback_in_drawing(gui) -> None:
    """
    Public one-liner:
    - Make Drawing Studio scrollable (in place).
    - Move the existing 'Drawn Stroke Playback' group into Drawing Studio.
    All signal/slot connections are preserved because we re-parent the existing widget.
    """
    # Ensure the scroll wrapper exists
    drawing_tab = getattr(gui, "drawing_tab", None)
    if drawing_tab is None:
        return
    _make_widget_scrollable_in_place(drawing_tab)

    # Find the existing group anywhere in the window
    gb = _find_drawn_stroke_group(gui)
    if gb is None:
        # Nothing to move; keep silent (no breakage).
        return

    # Detach from old parent layout cleanly
    old_parent = gb.parentWidget()
    if old_parent and old_parent is not drawing_tab:
        if old_parent.layout() is not None:
            old_parent.layout().removeWidget(gb)

    gb.setParent(None)
    gb.setObjectName("DrawnStrokePlaybackGroup")  # stable for future finds
    _add_widget_to_drawing_tab_end(gui, gb)
def _sample_event_amplitude(ev: Optional['HapticEvent'], t_s: float) -> float:
    """Return amplitude in [0..1] for event at time t_s (wrap if needed)."""
    if ev is None or not getattr(ev, "waveform_data", None):
        return 1.0
    wf = ev.waveform_data
    duration = float(wf.duration or 0.0)
    if duration <= 0.0:
        return 1.0
    # wrap
    tt = t_s % duration
    pts = wf.amplitude or []
    if not pts:
        return 1.0
    # ensure sorted
    xs = [float(p["time"]) for p in pts]
    ys = [float(p["amplitude"]) for p in pts]
    if tt <= xs[0]: return max(0.0, min(1.0, ys[0]))
    if tt >= xs[-1]: return max(0.0, min(1.0, ys[-1]))
    # linear interp
    lo = 0
    hi = len(xs) - 1
    # binary search
    while hi - lo > 1:
        m = (lo + hi)//2
        if xs[m] <= tt: lo = m
        else: hi = m
    x0, x1 = xs[lo], xs[hi]
    y0, y1 = ys[lo], ys[hi]
    alpha = 0.0 if (x1 - x0) <= 1e-9 else (tt - x0) / (x1 - x0)
    val = y0 + alpha * (y1 - y0)
    return max(0.0, min(1.0, float(val)))