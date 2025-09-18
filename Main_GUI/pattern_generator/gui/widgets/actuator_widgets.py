import math
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QPointF, QRectF, QTimer
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QFont
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QComboBox, 
                           QPushButton, QStackedWidget, QLabel, QSizePolicy,
                           QMessageBox, QInputDialog)
from ..widgets.flexible_actuator_selector import FlexibleActuatorSelector

class NodeCanvasWidget(QWidget):
    """
    Tiny, generic canvas that draws circular 'actuator' nodes at normalized
    positions and lets you click-toggle selection.
    """
    selection_changed = pyqtSignal(list)

    def __init__(self, nodes: list[tuple[int, float, float]], parent=None):
        super().__init__(parent)
        # nodes: list of (id, x_norm, y_norm) with x,y in [0..1]
        self.nodes = nodes[:]  # copy
        self.selected: set[int] = set()
        self.active: set[int] = set()
        self.radius_px = 18
        self.margin_px = 24
        self.setMinimumHeight(320)
        self.setMouseTracking(True)
        self.setAutoFillBackground(True)
    
    def get_nodes(self) -> list[tuple[int, float, float]]:
        """Return a copy of (id, x_norm, y_norm) for background rendering."""
        return self.nodes[:]

    # ----- public API used by wrappers -----
    def get_selected_actuators(self) -> list[int]:
        return sorted(self.selected)
    def set_active(self, ids: list[int] | set[int]):
        """Visually highlight 'currently playing' actuators (preview)."""
        self.active = set(int(i) for i in ids)
        self.update()
    

    def clear_active(self):
        self.active.clear()
        self.update()

    def load_actuator_configuration(self, ids: list[int]):
        """Select only IDs that exist on this fixed node canvas."""
        valid = {nid for nid, _, _ in self.nodes}
        self.selected = {int(i) for i in ids if int(i) in valid}
        self.update()
        self.selection_changed.emit(self.get_selected_actuators())

    def select_all(self):
        self.selected = {nid for nid, _, _ in self.nodes}
        self.update()
        self.selection_changed.emit(self.get_selected_actuators())

    def select_none(self):
        self.selected.clear()
        self.update()
        self.selection_changed.emit(self.get_selected_actuators())

    def clear_canvas(self):
        # fixed canvases don’t place/delete nodes → treat as 'select none'
        self.select_none()

    # ----- painting & hit-testing -----
    def _xy_to_px(self, xn: float, yn: float) -> QPointF:
        w = self.width()
        h = self.height()
        x = self.margin_px + xn * max(1, (w - 2 * self.margin_px))
        y = self.margin_px + yn * max(1, (h - 2 * self.margin_px))
        return QPointF(x, y)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # background
        p.fillRect(self.rect(), self.palette().alternateBase())

        # draw nodes
        for nid, xn, yn in self.nodes:
            c = self._xy_to_px(xn, yn)
            r = self.radius_px
            rect = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)

            # base circle (fill + outline)
            p.setPen(QPen(QColor("#374151"), 2))
            if nid in self.selected:
                p.setBrush(QBrush(self.palette().highlight().color()))
            else:
                p.setBrush(QBrush(QColor("#E5E7EB")))
            p.drawEllipse(rect)

            # active ring (preview)
            if nid in self.active:
                ring = rect.adjusted(-3, -3, +3, +3)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(self.palette().highlight().color(), 4))
                p.drawEllipse(ring)

            # label
            p.setPen(QPen(QColor("#111827")))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(nid))

        p.end()

    def _hit(self, pos: QPointF) -> int | None:
        for nid, xn, yn in self.nodes:
            c = self._xy_to_px(xn, yn)
            if math.hypot(pos.x() - c.x(), pos.y() - c.y()) <= self.radius_px + 4:
                return nid
        return None

    def mousePressEvent(self, e):
        nid = self._hit(e.position())
        if e.button() == Qt.MouseButton.LeftButton and nid is not None:
            if nid in self.selected:
                self.selected.remove(nid)
            else:
                self.selected.add(nid)
            self.update()
            self.selection_changed.emit(self.get_selected_actuators())
        elif e.button() == Qt.MouseButton.RightButton and nid is not None:
            if nid in self.selected:
                self.selected.remove(nid)
                self.update()
                self.selection_changed.emit(self.get_selected_actuators())
        super().mousePressEvent(e)

class Grid3x3Selector(QWidget):
    """Fixed 3×3 layout (IDs 0..8)."""
    selection_changed = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        # normalized grid points ~ (0.2, 0.5, 0.8)
        xs = [0.2, 0.5, 0.8]
        ys = [0.2, 0.5, 0.8]
        nodes = []
        nid = 0
        for y in ys:
            for x in xs:
                nodes.append((nid, x, y))
                nid += 1

        self.canvas = NodeCanvasWidget(nodes)
        self.canvas.selection_changed.connect(self.selection_changed.emit)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.canvas)

    # API passthroughs
    def get_selected_actuators(self): return self.canvas.get_selected_actuators()
    def load_actuator_configuration(self, ids): self.canvas.load_actuator_configuration(ids)
    def select_all(self): self.canvas.select_all()
    def select_none(self): self.canvas.select_none()
    def clear_canvas(self): self.canvas.clear_canvas()
    def get_nodes(self): return self.canvas.get_nodes()


class CustomLayoutSelector(QWidget):
    selection_changed = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Four column anchors (left → right)
        x4 = [0.12, 0.38, 0.62, 0.88]

        # y-rows (top to bottom)
        y_top    = 0.10
        y_row1   = 0.30
        y_row2   = 0.50
        y_row3   = 0.70
        y_bottom = 0.90

        # Build nodes (id, x_norm, y_norm)
        nodes = [
            # TOP — align 0 above 4 (col 2), 1 above 3 (col 3)
            (0,  x4[1], y_top),
            (1,  x4[2], y_top),

            # Row 1
            (5,  x4[0], y_row1), (4, x4[1], y_row1), (3, x4[2], y_row1), (2, x4[3], y_row1),

            # Row 2
            (6,  x4[0], y_row2), (7, x4[1], y_row2), (8, x4[2], y_row2), (9, x4[3], y_row2),

            # Row 3
            (13, x4[0], y_row3), (12, x4[1], y_row3), (11, x4[2], y_row3), (10, x4[3], y_row3),

            # BOTTOM — align 14 under 12 (col 2), 15 under 11 (col 3)
            (14, x4[1], y_bottom),
            (15, x4[2], y_bottom),
        ]

        self.canvas = NodeCanvasWidget(nodes)
        self.canvas.selection_changed.connect(self.selection_changed.emit)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.canvas)

    # API passthroughs
    def get_selected_actuators(self): return self.canvas.get_selected_actuators()
    def load_actuator_configuration(self, ids): self.canvas.load_actuator_configuration(ids)
    def select_all(self): self.canvas.select_all()
    def select_none(self): self.canvas.select_none()
    def clear_canvas(self): self.canvas.clear_canvas()
    def get_nodes(self): return self.canvas.get_nodes()

class MultiCanvasSelector(QWidget):
    selection_changed = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(QLabel("Canvas:"))
        self.canvasCombo = QComboBox()
        self.canvasCombo.addItems(["Designer", "3×3 Grid", "Back Layout"])
        self.canvasCombo.setMinimumWidth(140)
        top.addWidget(self.canvasCombo)
        top.addStretch()

        self.btnClear = QPushButton("Clear")
        self.btnCreateChain = QPushButton("Create Chain")
        self.btnAll = QPushButton("All")
        for b in (self.btnClear, self.btnCreateChain, self.btnAll):
            b.setMinimumWidth(90)
            top.addWidget(b)

        # Stack with 3 pages
        self.stack = QStackedWidget()
        # Page 0: existing Designer
        self.designer = FlexibleActuatorSelector()
        # Try to hide internal duplicates (Clear/All/None/Create Chain) after it’s built
        QTimer.singleShot(0, self._hide_internal_designer_controls)
        self._wire_selector(self.designer)

        # Page 1: 3×3
        self.grid3 = Grid3x3Selector()
        self.grid3.selection_changed.connect(self.selection_changed.emit)

        # Page 2: custom
        self.custom = CustomLayoutSelector()
        self.custom.selection_changed.connect(self.selection_changed.emit)

        self.stack.addWidget(self.designer)
        self.stack.addWidget(self.grid3)
        self.stack.addWidget(self.custom)

        # Layout
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)   # remove extra padding around the whole selector
        root.setSpacing(4)
        root.addLayout(top)
        root.addWidget(self.stack)

        self._designer_preview_mode = False
        self._designer_prev_selection: set[int] | None = None

        # Wire top buttons
        self.canvasCombo.currentIndexChanged.connect(self._on_canvas_changed)
        self.btnClear.clicked.connect(self._act_clear)
        self.btnAll.clicked.connect(self._act_all)
        self.btnCreateChain.clicked.connect(self._act_create_chain)
        self._update_buttons_for_page(0)
    
    def get_active_canvas_widget(self):
        idx = self.stack.currentIndex()
        if idx == 0:
            return getattr(self.designer, "canvas", None)
        if idx == 1:
            return self.grid3.canvas
        if idx == 2:
            return self.custom.canvas
        return None
    
    def _designer_read_selection(self) -> set[int]:
    # essaie l’API publique du sélecteur
        try:
            return set(int(i) for i in self.designer.get_selected_actuators())
        except Exception:
            pass
        # fallback: lire depuis les objets d’actuateur du canvas s’ils existent
        try:
            acts = getattr(self.designer, "canvas", None)
            if acts and hasattr(acts, "actuators"):
                out = set()
                for a in acts.actuators:
                    if getattr(a, "is_selected", False):
                        out.add(int(getattr(a, "actuator_id", -1)))
                return out
        except Exception:
            pass
        return set()

    def _designer_apply_selection(self, ids: set[int]):
        """Applique une sélection exacte sur le canvas du Designer."""
        canvas = getattr(self.designer, "canvas", None)
        if not canvas or not hasattr(canvas, "actuators"):
            return
        for a in canvas.actuators:
            try:
                a.set_selected_state(int(getattr(a, "actuator_id", -1)) in ids)
            except Exception:
                pass
        try:
            if hasattr(canvas, "on_actuator_selection_changed"):
                canvas.on_actuator_selection_changed()
            else:
                canvas.update()
        except Exception:
            pass
    def current_nodes(self) -> list[tuple[int, float, float]]:
        """Return normalized node anchors for the CURRENT fixed canvas.
        Designer is not guaranteed; returns [] for Designer."""
        idx = self.stack.currentIndex()
        if idx == 1:  # 3x3
            try: return self.grid3.get_nodes()
            except Exception: return []
        if idx == 2:  # Custom
            try: return self.custom.get_nodes()
            except Exception: return []
        # Designer page not supported here (unknown geometry)
        return []

    def set_preview_active(self, ids: list[int] | set[int]):
        try:
            self.grid3.canvas.set_active(ids)
        except Exception:
            pass
        try:
            self.custom.canvas.set_active(ids)
        except Exception:
            pass

        try:
            if hasattr(self.designer, "set_preview_active"):
                self.designer.set_preview_active(ids)
                return
        except Exception:
            pass

        try:
            if not self._designer_preview_mode:
                self._designer_prev_selection = self._designer_read_selection()
                self._designer_preview_mode = True
            target = set(self._designer_prev_selection or set()) | {int(i) for i in ids}
            self._designer_apply_selection(target)
        except Exception:
            pass

    def clear_preview(self):
        # canvases fixes
        try:
            self.grid3.canvas.clear_active()
        except Exception:
            pass
        try:
            self.custom.canvas.clear_active()
        except Exception:
            pass

        # Designer : API native ?
        try:
            if hasattr(self.designer, "clear_preview"):
                self.designer.clear_preview()
                return
        except Exception:
            pass

        # Fallback : restaurer la sélection d’origine si on l’a modifiée
        try:
            if self._designer_preview_mode and self._designer_prev_selection is not None:
                self._designer_apply_selection(set(self._designer_prev_selection))
        except Exception:
            pass
        finally:
            self._designer_preview_mode = False
            self._designer_prev_selection = None
    # ----- internal helpers -----
    def _wire_selector(self, selector_widget):
        """Connect selection_changed if the child exposes it."""
        if hasattr(selector_widget, "selection_changed"):
            try:
                selector_widget.selection_changed.connect(self.selection_changed.emit)
            except Exception:
                pass
        
    def _load_on_designer(self, ids: list[int]):
        """
        Ensure the Designer (FlexibleActuatorSelector) has at least max(id)+1
        actuators (create a chain if needed), then apply the selection.
        """
        sel = self.designer
        if not ids:
            # clear selection across designer
            try:
                sel.select_none()
            except Exception:
                pass
            try:
                sel.canvas.on_actuator_selection_changed()
            except Exception:
                pass
            return

        max_id = max(ids)
        canvas = getattr(sel, "canvas", None)
        current = getattr(canvas, "actuators", []) if canvas else []

        # Ensure we have enough actuators to cover the highest ID
        if canvas is not None and len(current) <= max_id:
            try:
                # clean start
                if hasattr(sel, "clear_canvas"):
                    sel.clear_canvas()
                elif hasattr(canvas, "clear"):
                    canvas.clear()

                # create a chain 0..max_id (default type)
                if hasattr(sel, "create_chain"):
                    sel.create_chain(max_id + 1)
                    current = getattr(sel.canvas, "actuators", [])
            except Exception:
                # Fallback: add actuators one by one if API is available
                try:
                    needed = (max_id + 1) - len(current)
                    for _ in range(max(0, needed)):
                        if hasattr(canvas, "add_actuator"):
                            canvas.add_actuator("LRA")
                    current = getattr(canvas, "actuators", [])
                except Exception:
                    pass

        # Apply the selection
        try:
            sel.select_none()
        except Exception:
            pass

        for a in getattr(sel.canvas, "actuators", []):
            try:
                a.set_selected_state(a.actuator_id in ids)
            except Exception:
                pass

        try:
            sel.canvas.on_actuator_selection_changed()
        except Exception:
            pass

    def _hide_internal_designer_controls(self):
        """
        Hide internal Clear / All / None / Create Chain buttons inside the
        FlexibleActuatorSelector to avoid duplicates in the Designer page.
        This is a best-effort approach based on button text.
        """
        try:
            from PyQt6.QtWidgets import QPushButton
            to_hide = {"clear", "all", "none", "create chain"}
            for btn in self.designer.findChildren(QPushButton):
                if btn.text().strip().lower() in to_hide:
                    btn.setVisible(False)
        except Exception:
            # harmless if it fails; you’ll just see duplicated buttons
            pass

    def _on_canvas_changed(self, idx: int):
        self.stack.setCurrentIndex(idx)
        self._update_buttons_for_page(idx)

    def _update_buttons_for_page(self, idx: int):
        # Create Chain is only meaningful on Designer
        self.btnCreateChain.setEnabled(idx == 0)

    # ----- top button actions -----
    def _act_clear(self):
        idx = self.stack.currentIndex()
        if idx == 0 and hasattr(self.designer, "clear_canvas"):
            # Page Designer → vrai reset du canevas (supprime les nodes/actuateurs)
            try:
                self.designer.clear_canvas()
                # Optionnel: forcer une notif de sélection vide au GUI
                if hasattr(self.designer, "canvas") and hasattr(self.designer.canvas, "on_actuator_selection_changed"):
                    self.designer.canvas.on_actuator_selection_changed()
            except Exception:
                pass
            return

        # Pages fixes → clear = désélection uniquement (non destructif)
        sel = self._current_page()
        if hasattr(sel, "select_none"):
            sel.select_none()
        elif hasattr(sel, "clear_canvas"):
            sel.clear_canvas()

    def _act_all(self):
        sel = self._current_page()
        if hasattr(sel, "select_all"):
            sel.select_all()

    def _act_create_chain(self):
        # Always run on the Designer page, like the base UI
        if self.stack.currentIndex() != 0:
            self.canvasCombo.setCurrentIndex(0)
        try:
            self.designer.create_chain()  # opens the dialog and creates the branch
        except Exception as e:
            QMessageBox.critical(self, "Create Chain", f"Failed: {e}")

    def _current_page(self):
        idx = self.stack.currentIndex()
        return [self.designer, self.grid3, self.custom][idx]

    # ----- unified public API used by HapticPatternGUI -----
    def get_selected_actuators(self) -> list[int]:
        page = self._current_page()
        if hasattr(page, "get_selected_actuators"):
            return page.get_selected_actuators()
        return []

    def load_actuator_configuration(self, ids: list[int]):
        cleaned = []
        for i in ids:
            try:
                cleaned.append(int(i))
            except Exception:
                pass
        cleaned = sorted(set(cleaned))

        # Designer first (may need to create nodes)
        self._load_on_designer(cleaned)

        # Fixed canvases just select what exists
        try:
            self.grid3.load_actuator_configuration(cleaned)
        except Exception:
            pass
        try:
            self.custom.load_actuator_configuration(cleaned)
        except Exception:
            pass
