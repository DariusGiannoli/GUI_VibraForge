#!/usr/bin/env python3
"""
flexible_actuator_selector.py

Top palette + expanded canvas to place actuators, create chains, and edit items.
Behavior mirrors the app's ActuatorCanvas pattern:
- Drag from the mini top palette (LRA / VCA / M) onto the white canvas area to create items.
- Create a chain (branch) with a dialog: sequentially linked actuators (A.1 -> A.2 -> ...).
- Double‑click an actuator to edit its ID and type.
- Right‑click an actuator for a context menu (Edit / Delete / Clear Connections).
- Moving items updates connections live.

Exposed signals (re‑emitted by the composite widget):
    selection_changed(list[str])
    actuator_added(id: str, a_type: str, pos: QPointF)
    actuator_deleted(id: str)
    actuator_renamed(old_id: str, new_id: str)
    actuator_moved(id: str, pos: QPointF)
    open_timeline_requested(id: str)    # double‑click background → ""

PyQt: 6.x
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import (
    Qt, QRectF, QPointF, QMimeData, QSize, pyqtSignal
)
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QAction, QDrag, QPixmap, QPainterPath, QCursor
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGraphicsView, QGraphicsScene, QGraphicsItem, QGraphicsRectItem, QGraphicsLineItem,
    QFormLayout, QDialog, QDialogButtonBox, QLineEdit, QComboBox, QMenu, QMessageBox, QSpinBox,
    QApplication, QMainWindow, QStyle, QFrame, QSizePolicy
)

# ------------------------------- Constants -------------------------------- #

ACTUATOR_SIZE = QSize(42, 42)
# canvas insets
CANVAS_PADDING    = 4
CANVAS_TOP_PAD    = 0   # was 2
CANVAS_BOTTOM_PAD = 0   # was 2)
CANVAS_BG = QColor("#1E293B")  # Dark slate background to match UI
CANVAS_BORDER = QColor("#334155")  # Darker border
SELECTION_COLOR = QColor(59, 130, 246, 180)  # Blue selection (more vibrant)
HOVER_COLOR = QColor(255, 255, 255, 25)  # Light hover on dark background

BRANCH_COLORS = [
    "#ef4444", "#f59e0b", "#10b981", "#3b82f6",
    "#a855f7", "#06b6d4", "#84cc16", "#f97316",
    "#e11d48", "#22c55e", "#2563eb", "#7c3aed",
]

MIME_TYPE = "application/x-actuator-type"
CHAIN_JUMP_INDEX = 16  # A.* = 0..15, B.* = 16..31, etc.

def id_to_addr(actuator_id: str) -> Optional[int]:
    branch, idx = split_id(actuator_id)
    if not branch:
        return None
    ch = branch[0].upper()
    if not ('A' <= ch <= 'Z'):
        return None
    base = (ord(ch) - ord('A')) * CHAIN_JUMP_INDEX
    return base + max(1, int(idx)) - 1


def _qcolor(c: str) -> QColor:
    return QColor(c)


# --------------------------- Utility functions ---------------------------- #

def next_branch_letter(existing: List[str]) -> str:
    """Return next A, B, C... skipping those already used."""
    for ch in string.ascii_uppercase:
        if ch not in existing:
            return ch
    # If we run out, reuse with suffix
    idx = 1
    while True:
        for ch in string.ascii_uppercase:
            candidate = f"{ch}{idx}"
            if candidate not in existing:
                return candidate
        idx += 1


def split_id(actuator_id: str) -> Tuple[str, int]:
    """"A.1" -> ("A", 1). If no dot, assume index=1."""
    if "." in actuator_id:
        b, s = actuator_id.split(".", 1)
        try:
            return b, int(s)
        except ValueError:
            return b, 1
    return actuator_id, 1


def join_id(branch: str, index: int) -> str:
    return f"{branch}.{index}"


# --------------------------------- UI bits -------------------------------- #

class DragSourceButton(QPushButton):
    """Small button that starts a drag with MIME_TYPE and text payload."""
    def __init__(self, label: str, payload: str, *, w: int = 36, h: int = 28, radius: int = 6, parent: Optional[QWidget] = None):
        super().__init__(label, parent)
        self.payload = payload
        self.setFixedSize(w, h)
        self.setObjectName("DragSourceButton")
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._radius = radius

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(e)

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton:
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData(MIME_TYPE, self.payload.encode("utf-8"))
            drag.setMimeData(mime)

            pm = QPixmap(self.size())
            pm.fill(Qt.GlobalColor.transparent)
            drag.setPixmap(pm)
            drag.exec(Qt.DropAction.CopyAction)
        else:
            super().mouseMoveEvent(e)


class MiniPaletteBar(QWidget):
    """Minimal horizontal palette placed at the top."""
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("MiniPaletteBar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(6)

        btn_lra = DragSourceButton("LRA", "LRA", w=36, h=26, radius=6)
        btn_vca = DragSourceButton("VCA", "VCA", w=36, h=26, radius=6)
        btn_m = DragSourceButton("M", "M", w=28, h=26, radius=6)

        btn_lra.setToolTip("Linear Resonant Actuator")
        btn_vca.setToolTip("Voice‑Coil Actuator")
        btn_m.setToolTip("Misc / Motor")

        lay.addWidget(btn_lra)
        lay.addWidget(btn_vca)
        lay.addWidget(btn_m)
        lay.addStretch(1)

        self.setStyleSheet("""
            #MiniPaletteBar { border: 0; background: transparent; }
            #DragSourceButton {
                border: 1px solid #475569; 
                border-radius: 6px; 
                background: #1E293B;
                color: #F1F5F9;
            }
            #DragSourceButton:hover { background: #334155; }
            #DragSourceButton:pressed { background: #475569; }
        """)


# --------------------------------- Model ---------------------------------- #

@dataclass
class ActuatorModel:
    actuator_id: str
    actuator_type: str  # "LRA" | "VCA" | "M"
    branch: str
    index: int
    color: QColor
    predecessor: Optional[str] = None
    successor: Optional[str] = None


# ----------------------------- Graphics items ----------------------------- #

class SelectableActuator(QGraphicsItem):
    """Visual item for an actuator. Knows its model id/type and branch color."""
    def __init__(self, model: ActuatorModel, size: QSize, parent: Optional[QGraphicsItem] = None):
        super().__init__(parent)
        self.model = model
        self.size = size
        self._w = size.width()
        self._h = size.height()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self._canvas = None  # back‑reference set by ActuatorCanvas
        self.preview_active = False

    # ---- geometry ----
    def boundingRect(self) -> QRectF:
        pad = 2.0
        return QRectF(-self._w/2 - pad, -self._h/2 - pad, self._w + 2*pad, self._h + 2*pad)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        r = QRectF(-self._w/2, -self._h/2, self._w, self._h)
        if self.model.actuator_type == "LRA":
            path.addEllipse(r)
        elif self.model.actuator_type == "VCA":
            path.addRect(r)
        else:  # "M"
            path.addRoundedRect(r, 8, 8)
        return path

    def paint(self, p: QPainter, option, widget=None):
        r = QRectF(-self._w/2, -self._h/2, self._w, self._h)
        p.setRenderHints(QPainter.RenderHint.Antialiasing, True)

        # Fill: white by default; branch color when selected
        fill_color = QColor("#FFFFFF") if not self.isSelected() else self.model.color
        p.setBrush(QBrush(fill_color))
        p.setPen(Qt.PenStyle.NoPen)
        if self.model.actuator_type == "LRA":
            p.drawEllipse(r)
        elif self.model.actuator_type == "VCA":
            p.drawRect(r)
        else:
            p.drawRoundedRect(r, 8, 8)

        # Outline: branch color (thicker when selected)
        out_pen = QPen(self.model.color, 1.6 if self.isSelected() else 1.2)
        p.setPen(out_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if self.model.actuator_type == "LRA":
            p.drawEllipse(r)
        elif self.model.actuator_type == "VCA":
            p.drawRect(r)
        else:
            p.drawRoundedRect(r, 8, 8)

        # ID text: dark on white, light on colored
        text_pen = QPen(QColor("#0F172A") if not self.isSelected() else QColor("#FFFFFF"))
        p.setPen(text_pen)
        font = QFont(); font.setPointSizeF(9.5); p.setFont(font)
        branch, idx = split_id(self.model.actuator_id)
        text = branch
        metrics = p.fontMetrics()
        tw = metrics.horizontalAdvance(text)
        th = metrics.height()
        p.drawText(QPointF(-tw/2, th/4), text)
        font_small = QFont(font); font_small.setPointSizeF(7.0); p.setFont(font_small)
        idx_text = f".{idx}"
        itw = p.fontMetrics().horizontalAdvance(idx_text)
        p.drawText(QPointF(tw/2 - itw/2, th/1.2), idx_text)

        # Hover overlay
        if option.state & QStyle.StateFlag.State_MouseOver:
            p.setBrush(QBrush(HOVER_COLOR))
            p.setPen(Qt.PenStyle.NoPen)
            if self.model.actuator_type == "LRA":
                p.drawEllipse(r)
            elif self.model.actuator_type == "VCA":
                p.drawRect(r)
            else:
                p.drawRoundedRect(r, 8, 8)

        # Preview ring (Play Preview highlight)
        if getattr(self, "preview_active", False):
            ring = r.adjusted(-3, -3, +3, +3)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor("#EF4444"), 2))
            if self.model.actuator_type == "LRA":
                p.drawEllipse(ring)
            elif self.model.actuator_type == "VCA":
                p.drawRect(ring)
            else:
                p.drawRoundedRect(ring, 8, 8)

    # ---- helpers ----
    def _canvas_from_scene(self):
        sc = self.scene()
        return sc.views()[0] if sc and sc.views() else None

    def open_properties_dialog(self):
        dlg = QDialog()
        dlg.setWindowTitle("Actuator Properties")
        form = QFormLayout(dlg)

        id_edit = QLineEdit(self.model.actuator_id)
        type_combo = QComboBox()
        type_combo.addItems(["LRA", "VCA", "M"])
        type_combo.setCurrentText(self.model.actuator_type)

        form.addRow("ID", id_edit)
        form.addRow("Type", type_combo)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, parent=dlg)
        form.addRow(btns)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)

        if dlg.exec():
            new_id = id_edit.text().strip()
            new_type = type_combo.currentText()
            canvas = self._canvas or self._canvas_from_scene()
            if canvas and new_id:
                canvas.rename_and_retype_actuator(self, new_id, new_type)

    # ---- interactions ----
    def hoverEnterEvent(self, event):
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.update()
        super().hoverLeaveEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.open_properties_dialog()
        if event is not None:
            super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu()
        act_edit = QAction("Edit…", menu)
        act_delete = QAction("Delete", menu)
        act_clear = QAction("Clear Connections", menu)
        menu.addAction(act_edit)
        menu.addAction(act_delete)
        menu.addSeparator()
        menu.addAction(act_clear)

        act_edit.triggered.connect(self.open_properties_dialog)
        act_delete.triggered.connect(lambda: (self._canvas or self._canvas_from_scene()).delete_actuator(self))
        act_clear.triggered.connect(lambda: (self._canvas or self._canvas_from_scene()).clear_connections(self))

        menu.exec(QCursor.pos())  # robust across event types

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            canvas = self._canvas or self._canvas_from_scene()
            if canvas:
                canvas.rebuild_all_lines()
                canvas._emit_moved(self)
        return super().itemChange(change, value)


class ConnectionLine(QGraphicsLineItem):
    """Simple line connecting actuators (no arrowhead)."""
    def __init__(self, a: SelectableActuator, b: SelectableActuator, parent=None):
        super().__init__(parent)
        self.a = a
        self.b = b
        self.setZValue(-1)  # under nodes
        self.setPen(QPen(QColor("#64748B"), 1.2))

    def update_geometry(self):
        pa = self.a.scenePos()
        pb = self.b.scenePos()
        self.setLine(pa.x(), pa.y(), pb.x(), pb.y())


# ------------------------------ Canvas view ------------------------------- #

class ActuatorCanvas(QGraphicsView):
    """QGraphicsView-based canvas that manages actuators and their connections."""
    selection_changed = pyqtSignal(list)
    actuator_added = pyqtSignal(str, str, QPointF)      # id, type, pos
    actuator_deleted = pyqtSignal(str)
    actuator_renamed = pyqtSignal(str, str)             # old, new
    actuator_moved = pyqtSignal(str, QPointF)
    open_timeline_requested = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("ActuatorCanvas")
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)
        self.setFrameShape(QFrame.Shape.NoFrame)
        # Fill available space
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(560)  # give it headroom so it claims vertical space

        # White canvas rect to constrain drops
        self._canvas_rect_item = QGraphicsRectItem()
        self._canvas_rect_item.setBrush(QBrush(CANVAS_BG))
        self._canvas_rect_item.setPen(QPen(CANVAS_BORDER, 1.0, Qt.PenStyle.SolidLine))
        self._canvas_rect_item.setZValue(-2)
        self._scene.addItem(self._canvas_rect_item)

        self.setAcceptDrops(True)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setMouseTracking(True)

        # Model
        self.actuators: Dict[str, SelectableActuator] = {}
        self.branch_colors: Dict[str, QColor] = {}
        self.connections: List[ConnectionLine] = []
        self._branch_used_indices: Dict[str, int] = {}  # branch -> max index

        # Optional: hide scrollbars (uncomment if desired)
        # self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    # ---- sizing ----
    def resizeEvent(self, e):
        super().resizeEvent(e)
        view_rect = self.viewport().rect().adjusted(
            CANVAS_PADDING, CANVAS_TOP_PAD, -CANVAS_PADDING, -CANVAS_BOTTOM_PAD
        )
        rect = self.mapToScene(view_rect).boundingRect()
        self._canvas_rect_item.setRect(rect)

    # ---- drag & drop ----
    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME_TYPE):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(MIME_TYPE):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(MIME_TYPE):
            return super().dropEvent(event)
        pt = self.mapToScene(event.position().toPoint())
        if not self._canvas_rect_item.rect().contains(pt):
            return
        a_type = bytes(event.mimeData().data(MIME_TYPE)).decode("utf-8")
        new_id = self.generate_next_id()
        model = self._make_model_for_new_id(new_id, a_type)
        node = SelectableActuator(model, ACTUATOR_SIZE)
        node._canvas = self
        node.setPos(pt)
        self._scene.addItem(node)
        self.actuators[new_id] = node
        self._emit_added(node)
        self.rebuild_all_lines()
        event.acceptProposedAction()

    # ---- model helpers ----
    def _make_model_for_new_id(self, actuator_id: str, a_type: str) -> ActuatorModel:
        branch, idx = split_id(actuator_id)
        color = self.branch_colors.get(branch)
        if color is None:
            cidx = len(self.branch_colors) % len(BRANCH_COLORS)
            color = _qcolor(BRANCH_COLORS[cidx])
            self.branch_colors[branch] = color
        return ActuatorModel(
            actuator_id=actuator_id, actuator_type=a_type,
            branch=branch, index=idx, color=color
        )

    def generate_next_id(self) -> str:
        """Return next ID within the latest/last branch, or create new 'A' if none."""
        if not self.branch_colors:
            branch = "A"
        else:
            branch = list(self.branch_colors.keys())[-1]
        max_idx = self._branch_used_indices.get(branch, 0) + 1
        self._branch_used_indices[branch] = max_idx
        return join_id(branch, max_idx)

    # ---- editing ----
    def rename_and_retype_actuator(self, node: SelectableActuator, new_id: str, new_type: str):
        old_id = node.model.actuator_id
        if new_id != old_id:
            if new_id in self.actuators and self.actuators[new_id] is not node:
                return  # invalid rename (collision)
            self.actuators.pop(old_id, None)
            self.actuators[new_id] = node
            node.model.actuator_id = new_id
            branch, idx = split_id(new_id)
            node.model.branch = branch
            node.model.index = idx
            if branch not in self.branch_colors:
                cidx = len(self.branch_colors) % len(BRANCH_COLORS)
                self.branch_colors[branch] = _qcolor(BRANCH_COLORS[cidx])
            node.model.color = self.branch_colors[branch]
            self.actuator_renamed.emit(old_id, new_id)
        if new_type != node.model.actuator_type:
            node.model.actuator_type = new_type
        node.update()
        self.rebuild_all_lines()

    def delete_actuator(self, node: SelectableActuator):
        aid = node.model.actuator_id
        node._canvas = None  # avoid callbacks to a half‑destroyed node
        self._scene.removeItem(node)
        self.actuators.pop(aid, None)
        self.rebuild_all_lines()
        self.actuator_deleted.emit(aid)

    def clear_connections(self, node: SelectableActuator):
        node.model.predecessor = None
        node.model.successor = None
        self.rebuild_all_lines()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.position().toPoint())
            if isinstance(item, SelectableActuator):
                # Save current selection and clicked state, then let default press run
                prev = [n for n in self.actuators.values() if n.isSelected()]
                was_selected = item.isSelected()

                super().mousePressEvent(event)  # ensures movement/drag still works

                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    # Ctrl-click → toggle ONLY the clicked one, keep others as they were
                    item.setSelected(not was_selected)
                    for n in prev:
                        if n is not item:
                            n.setSelected(True)
                else:
                    # Additive click → restore previous AND ensure clicked becomes selected
                    for n in prev:
                        n.setSelected(True)
                    item.setSelected(True)

                self._emit_selection()
                return

        super().mousePressEvent(event)
        self._emit_selection()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self._emit_selection()

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if isinstance(item, SelectableActuator):
            self.open_timeline_requested.emit(item.model.actuator_id)
        else:
            self.open_timeline_requested.emit("")
        super().mouseDoubleClickEvent(event)

    def _emit_selection(self):
        ids = [n.model.actuator_id for n in self.actuators.values() if n.isSelected()]
        self.selection_changed.emit(ids)

    def _emit_added(self, node: SelectableActuator):
        self.actuator_added.emit(node.model.actuator_id, node.model.actuator_type, node.scenePos())

    def _emit_moved(self, node: SelectableActuator):
        self.actuator_moved.emit(node.model.actuator_id, node.scenePos())

    # ---- connections ----
    def rebuild_all_lines(self):
        for line in self.connections:
            self._scene.removeItem(line)
        self.connections.clear()

        by_branch: Dict[str, List[SelectableActuator]] = {}
        for node in self.actuators.values():
            by_branch.setdefault(node.model.branch, []).append(node)

        for branch, nodes in by_branch.items():
            nodes.sort(key=lambda n: n.model.index)
            for i in range(len(nodes) - 1):
                a, b = nodes[i], nodes[i+1]
                line = ConnectionLine(a, b)
                self._scene.addItem(line)
                line.update_geometry()
                self.connections.append(line)

    # ---- batch creation ----
    def create_chain(self, total: int = 6, rows: int = 1, cols: Optional[int] = None,
                     mix: Optional[Dict[str, int]] = None):
        """
        Create a new branch with `total` actuators laid out on a rows×cols grid,
        left‑to‑right, top‑to‑bottom, sequentially connected. `mix` can be
        like {"LRA": 3, "VCA": 2, "M": 1}; otherwise all LRA.
        """
        branch = next_branch_letter(list(self.branch_colors.keys()))
        cidx = len(self.branch_colors) % len(BRANCH_COLORS)
        self.branch_colors[branch] = _qcolor(BRANCH_COLORS[cidx])

        if cols is None:
            cols = total if rows <= 1 else (total + rows - 1) // rows

        types: List[str] = []
        if not mix:
            types = ["LRA"] * total
        else:
            for t, k in mix.items():
                types.extend([t] * k)
            if len(types) < total:
                types.extend(["LRA"] * (total - len(types)))
            types = types[:total]

        # Compute canvas rect from current viewport
        view_rect = self.viewport().rect().adjusted(
            CANVAS_PADDING, CANVAS_TOP_PAD, -CANVAS_PADDING, -CANVAS_BOTTOM_PAD
        )
        rect = self.mapToScene(view_rect).boundingRect()
        self._canvas_rect_item.setRect(rect)

        margin = 24
        grid_w = max(1.0, rect.width() - 2*margin)
        grid_h = max(1.0, rect.height() - 2*margin)
        step_x = grid_w / max(cols - 1, 1)
        step_y = grid_h / max(rows - 1, 1)

        created_nodes: List[SelectableActuator] = []
        created_count = 0
        for r in range(rows):
            for c in range(cols):
                if created_count >= total:
                    break
                a_type = types[created_count]
                index = created_count + 1
                aid = join_id(branch, index)
                model = ActuatorModel(
                    actuator_id=aid, actuator_type=a_type,
                    branch=branch, index=index,
                    color=self.branch_colors[branch]
                )
                node = SelectableActuator(model, ACTUATOR_SIZE)
                node._canvas = self
                x = rect.left() + margin + c * step_x
                y = rect.top() + margin + r * step_y
                node.setPos(QPointF(x, y))
                self._scene.addItem(node)
                self.actuators[aid] = node
                self._branch_used_indices[branch] = index
                self._emit_added(node)
                created_nodes.append(node)
                created_count += 1

        # Set predecessor/successor explicitly within the new branch
        for i in range(len(created_nodes) - 1):
            a = created_nodes[i]
            b = created_nodes[i + 1]
            a.model.successor = b.model.actuator_id
            b.model.predecessor = a.model.actuator_id

        self.rebuild_all_lines()

    # ---- utilities ----
    def clear_all(self):
        for n in list(self.actuators.values()):
            n._canvas = None
            self._scene.removeItem(n)
        for line in self.connections:
            self._scene.removeItem(line)
        self.actuators.clear()
        self.connections.clear()
        self.branch_colors.clear()
        self._branch_used_indices.clear()
        self.selection_changed.emit([])


# --------------------------- CreateBranchDialog ----------------------------- #

class CreateBranchDialog(QDialog):
    """Dialog to mirror the base UI: choose total, grid, and type mix."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create New Chain")
        form = QFormLayout(self)

        self.total_spin = QSpinBox(self)
        self.total_spin.setRange(1, 256)
        self.total_spin.setValue(6)

        self.rows_spin = QSpinBox(self)
        self.rows_spin.setRange(1, 32)
        self.rows_spin.setValue(1)

        self.cols_spin = QSpinBox(self)
        self.cols_spin.setRange(0, 64)  # 0 = auto
        self.cols_spin.setValue(0)
        self.cols_spin.setToolTip("0 = auto compute from total and rows")

        self.lra_spin = QSpinBox(self)
        self.lra_spin.setRange(0, 256)
        self.lra_spin.setValue(6)

        self.vca_spin = QSpinBox(self)
        self.vca_spin.setRange(0, 256)
        self.vca_spin.setValue(0)

        self.m_spin = QSpinBox(self)
        self.m_spin.setRange(0, 256)
        self.m_spin.setValue(0)

        form.addRow("Total actuators", self.total_spin)
        form.addRow("Rows", self.rows_spin)
        form.addRow("Cols (0 = auto)", self.cols_spin)
        form.addRow("LRA count", self.lra_spin)
        form.addRow("VCA count", self.vca_spin)
        form.addRow("M count", self.m_spin)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, parent=self)
        form.addRow(btns)
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)

        # Keep LRA default equal to total (so sum stays valid initially)
        self.total_spin.valueChanged.connect(self._sync_default_mix)

    def _sync_default_mix(self, n: int):
        # Keep mix sane if user hasn't changed values (simple heuristic)
        current_sum = self.lra_spin.value() + self.vca_spin.value() + self.m_spin.value()
        if current_sum == 0 or self.lra_spin.value() == current_sum:  # default state
            self.lra_spin.setValue(n)
            self.vca_spin.setValue(0)
            self.m_spin.setValue(0)

    def _on_accept(self):
        total = self.total_spin.value()
        rows = self.rows_spin.value()
        cols = self.cols_spin.value() or None
        lra = self.lra_spin.value()
        vca = self.vca_spin.value()
        m = self.m_spin.value()
        mix_sum = lra + vca + m
        if mix_sum > total:
            QMessageBox.warning(self, "Invalid mix", "LRA+VCA+M exceeds Total.")
            return
        # If sum < total, fill the remainder with LRA (mirrors base UI lenient behavior)
        if mix_sum == 0:
            mix = None
        else:
            if mix_sum < total:
                lra += (total - mix_sum)
            mix = {"LRA": lra, "VCA": vca, "M": m}
        self._result = (total, rows, cols, mix)
        self.accept()

    def values(self) -> tuple:
        return getattr(self, "_result", None)

# --------------------------- Composite widget ----------------------------- #

class FlexibleActuatorSelector(QWidget):
    """
    Composite widget:
      [ MiniPaletteBar ][ Create Chain ][ Clear All ]   (top bar)
      [ ActuatorCanvas (white rect area for drops) ]
      [ Status line ]
    """
    selection_changed = pyqtSignal(list)
    actuator_added = pyqtSignal(str, str, QPointF)
    actuator_deleted = pyqtSignal(str)
    actuator_renamed = pyqtSignal(str, str)
    actuator_moved = pyqtSignal(str, QPointF)
    open_timeline_requested = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        # Top bar
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 0, 6, 2)
        bar.setSpacing(6)
        self.palette = MiniPaletteBar()
        bar.addWidget(self.palette, 0)
        bar.addStretch(1)

        self.btn_create = QPushButton("Create Chain")
        self.btn_create.setFixedHeight(28)   # keep bar compact
        bar.addWidget(self.btn_create, 0)
        root.addLayout(bar)

        # Canvas
        self.canvas = ActuatorCanvas()
        root.addWidget(self.canvas, 1)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        # Wire signals outward
        self.canvas.selection_changed.connect(self.selection_changed)
        self.canvas.actuator_added.connect(self.actuator_added)
        self.canvas.actuator_deleted.connect(self.actuator_deleted)
        self.canvas.actuator_renamed.connect(self.actuator_renamed)
        self.canvas.actuator_moved.connect(self.actuator_moved)
        self.canvas.open_timeline_requested.connect(self.open_timeline_requested)

        # Internal handlers
        self.selection_changed.connect(self._on_selection_changed)
        self.btn_create.clicked.connect(self.create_chain)

        self.setStyleSheet("""
            QWidget#ActuatorCanvas { background: #0F172A; }
            QLabel { color: #F1F5F9; }
            QPushButton { 
                padding: 4px 8px; 
                border: 1px solid #475569; 
                border-radius: 6px; 
                background: #1E293B;
                color: #F1F5F9;
            }
            QPushButton:hover { background: #334155; }
        """)
    
    def create_chain(self, total: Optional[int] = None, rows: Optional[int] = None,
                 cols: Optional[int] = None, mix: Optional[Dict[str, int]] = None):
        if total is None and rows is None and cols is None and mix is None:
            return self._on_create_chain()
        try:
            t = int(total) if total is not None else 6
            r = int(rows)  if rows  is not None else 1
            c = None if (cols is None or int(cols) <= 0) else int(cols)
            self.canvas.create_chain(t, r, c, mix=mix)
        except Exception as e:
            try:
                QMessageBox.critical(self, "Create Chain failed", str(e))
            except Exception:
                pass

    def clear_canvas(self):
        """Compatibility helper so the parent UI can clear the designer page."""
        try:
            self.canvas.clear_all()
        except Exception:
            pass

    # ---- actions ----
    def _on_create_chain(self):
        dlg = CreateBranchDialog(self)
        if not dlg.exec():
            return
        vals = dlg.values()
        if not vals:
            return
        total, rows, cols, mix = vals
        try:
            self.canvas.create_chain(total, rows, cols, mix=mix)
        except Exception as e:
            QMessageBox.critical(self, "Create Chain failed", str(e))
        
    
    def set_preview_active(self, ids: List[int] | set[int]):
        """Highlight (ring) actuators whose ADDRESSES are in `ids`."""
        targets = {int(i) for i in ids}
        for node in self.canvas.actuators.values():
            addr = id_to_addr(node.model.actuator_id)
            node.preview_active = (addr in targets)
            node.update()

    def clear_preview(self):
        """Clear preview highlight ring on all actuators."""
        for node in self.canvas.actuators.values():
            if getattr(node, "preview_active", False):
                node.preview_active = False
                node.update()

    def _on_selection_changed(self, ids: List[str]):
        """Version avec log au lieu de status label"""
        if ids:
            print(f"Selected: {', '.join(ids)}")
        else:
            total = len(self.canvas.actuators)
            if total:
                print(f"{total} actuators — none selected")
            else:
                print("No actuators — drag from palette or click Create Chain")
    
    def get_selected_actuators(self) -> List[int]:
        """Return selected actuator ADDRESSES (0..N) so the timeline can use them."""
        out: List[int] = []
        try:
            for aid, node in self.canvas.actuators.items():
                if node.isSelected():
                    addr = id_to_addr(aid)
                    if addr is not None:
                        out.append(addr)
        except Exception:
            pass
        # unique + sorted
        return sorted(set(out))


# ------------------------------ Demo runner ------------------------------- #

if __name__ == "__main__":
    import sys
    # If you need High‑DPI policy, set it BEFORE QApplication is created:
    # from PyQt6.QtGui import QGuiApplication
    # QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    w = QMainWindow()
    w.setWindowTitle("Flexible Actuator Selector (Top Palette)")
    sel = FlexibleActuatorSelector()
    sel.selection_changed.connect(lambda ids: print("Selected:", ids))
    sel.actuator_added.connect(lambda i,t,p: print("Added", i, t, p))
    sel.open_timeline_requested.connect(lambda i: print("Open timeline for:", i or "<main>"))
    w.setCentralWidget(sel)
    w.resize(1000, 720)
    w.show()
    sys.exit(app.exec())
