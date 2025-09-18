# widgets.py
"""
Custom widgets for the haptic waveform designer
"""

import os
import json
from PyQt6.QtCore import Qt, pyqtSignal, QByteArray, QMimeData
from PyQt6.QtGui import QDrag
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem,
    QToolButton, QSizePolicy, QFrame, QMenu, QMessageBox,
)
from PyQt6.QtWidgets import QApplication

# Import from event data model and waveform editor widget
try:
    from ..core import HapticEvent, EventCategory, WaveformData, MIME_WAVEFORM
except ImportError:
    from core.event_data_model import HapticEvent, EventCategory, WaveformData
    MIME_WAVEFORM = "application/x-waveform"

try:
    from ...waveform_widget.waveform_editor_widget import WaveformEditorWidget
except ImportError:
    try:
        from waveform_widget.waveform_editor_widget import WaveformEditorWidget
    except ImportError:
        # Fallback: create a dummy widget to prevent crashes
        from PyQt6.QtWidgets import QLabel
        class WaveformEditorWidget(QLabel):
            def __init__(self, parent=None):
                super().__init__("WaveformEditorWidget not available", parent)
            def set_event(self, event): pass

class CollapsibleSection(QWidget):
    """Header + content container. Can be collapsible or forced always-open."""
    
    def __init__(self, title: str, content_widget: QWidget, *,
                 collapsed: bool = False, always_expanded: bool = False,
                 parent: QWidget | None = None):
        super().__init__(parent)

        self._always_expanded = bool(always_expanded)

        # Toggle button
        self.toggle_btn = QToolButton(self)
        self.toggle_btn.setText(title)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(True if self._always_expanded else (not collapsed))
        self.toggle_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle_btn.setArrowType(Qt.ArrowType.DownArrow)
        self.toggle_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.toggle_btn.setStyleSheet("""
            QToolButton {
                border: none;
                font-weight: 700;
                color: #2D3748;
                padding: 6px 4px;
                text-align: left;
            }
            QToolButton:hover { color: #1A202C; }
        """)

        # Content container
        self.content_area = QFrame(self)
        self.content_area.setFrameShape(QFrame.Shape.NoFrame)
        self.content_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay_content = QVBoxLayout(self.content_area)
        lay_content.setContentsMargins(8, 4, 8, 8)
        lay_content.setSpacing(8)
        lay_content.addWidget(content_widget)

        # If always expanded, keep visible and disable toggling
        if self._always_expanded:
            self.content_area.setVisible(True)
            self.toggle_btn.setCheckable(False)  # No collapse possible
        else:
            self.content_area.setVisible(not collapsed)
            self.toggle_btn.toggled.connect(self._on_toggled)

        # Main layout
        main_lay = QVBoxLayout(self)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setSpacing(0)
        main_lay.addWidget(self.toggle_btn)
        main_lay.addWidget(self.content_area)

    def _on_toggled(self, checked: bool):
        if self._always_expanded:
            self.toggle_btn.setChecked(True)
            self.content_area.setVisible(True)
            self.toggle_btn.setArrowType(Qt.ArrowType.DownArrow)
            return
        
        self.content_area.setVisible(checked)
        self.toggle_btn.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)

class LibraryTree(QTreeWidget):
    """
    QTreeWidget that supports starting drags with a JSON payload under MIME_WAVEFORM.
    Emits no signal by itself; parent widget handles double-clicks via itemActivated.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        # Slightly larger target for better UX
        self.setIconSize(self.iconSize())

    def _payload_for_item(self, item: QTreeWidgetItem) -> dict | None:
        """Return normalized payload dict for an item."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return None
        # Normalize minimal schema
        if isinstance(data, dict):
            # Add version + type if missing
            data.setdefault("v", 1)
            if "kind" not in data:
                # Heuristic: builtin oscillators tagged via "osc_name"
                if "osc_name" in data:
                    data["kind"] = "osc"
                    data["name"] = data.pop("osc_name")
            return data
        if isinstance(data, str):
            # Back-compat: strings like "oscillator::Sine" or file path
            if data.startswith("oscillator::"):
                return {"v": 1, "kind": "osc", "name": data.split("::", 1)[1]}
            return {"v": 1, "kind": "file", "path": data}
        return None

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if not item:
            return
        payload = self._payload_for_item(item)
        if not payload:
            return

        md = QMimeData()
        md.setData(MIME_WAVEFORM, QByteArray(json.dumps(payload).encode("utf-8")))
        drag = QDrag(self)
        drag.setMimeData(md)
        drag.exec(Qt.DropAction.CopyAction, Qt.DropAction.CopyAction)


class EventLibraryManager:
    """Manages file paths and directories for the waveform library."""
    
    def __init__(self):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        main_gui = os.path.dirname(current_dir)
        project_root = os.path.dirname(main_gui)
        
        # Verify it's the project root
        indicators = ['requirements.txt', 'pyproject.toml', '.git', 'README.md']
        if not any(os.path.exists(os.path.join(project_root, i)) for i in indicators):
            print(f"Warning: Project root indicators not found in {project_root}")
        
        self.lib_root = os.path.join(project_root, "waveform_library")
        self.custom_dir = os.path.join(self.lib_root, "customized")
        self.import_dir = os.path.join(self.lib_root, "imported")
        
        # Create directories if they don't exist
        for d in (self.lib_root, self.custom_dir, self.import_dir):
            os.makedirs(d, exist_ok=True)
        
        print(f"Library root   : {self.lib_root}")
        print(f"Customized dir : {self.custom_dir}")
        print(f"Imported dir   : {self.import_dir}")
        
        # Create __init__.py if it doesn't exist
        init_file = os.path.join(self.lib_root, "__init__.py")
        if not os.path.exists(init_file):
            with open(init_file, "w", encoding="utf-8") as f:
                f.write("# Waveform Library\n")

    def get_events_directory(self, bucket: str = "customized"):
        """Get the directory path for the specified bucket."""
        if bucket == "imported": 
            return self.import_dir
        if bucket == "root": 
            return self.lib_root
        return self.custom_dir

class EventLibraryWidget(QWidget):
    """Waveform Library with 3 sections; emits payload on double-click."""
    
    event_selected = pyqtSignal(object)
    BUILTIN_OSC = ["Sine", "Square", "Saw", "Triangle", "Chirp", "FM", "PWM", "Noise"]
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = EventLibraryManager()
        self.custom_dir = self.manager.custom_dir
        self.import_dir = self.manager.import_dir
        
        # Main layout
        v = QVBoxLayout(self)
        
        # Header
        head = QHBoxLayout()
        title = QLabel("Waveform Library")
        head.addWidget(title)
        head.addStretch(1)
        v.addLayout(head)
        
        # Tree widget
        self.tree = LibraryTree(self)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_ctx_menu)
        self.tree.itemDoubleClicked.connect(self._on_double_clicked)
        v.addWidget(self.tree)

        
        self.refresh()
    
    def refresh(self):
        """Refresh the library tree contents."""
        self.tree.clear()
        
        # Oscillators section
        osc_root = QTreeWidgetItem(["Oscillators"])
        self.tree.addTopLevelItem(osc_root)
        for name in self.BUILTIN_OSC:
            child = QTreeWidgetItem([name])
            child.setData(0, Qt.ItemDataRole.UserRole, {"kind": "osc", "name": name})
            osc_root.addChild(child)
        
        # Customized signals section
        cust_root = QTreeWidgetItem(["Customized Signals"])
        self.tree.addTopLevelItem(cust_root)
        for fn in sorted(os.listdir(self.custom_dir)):
            if fn.endswith((".json", ".csv")):
                p = os.path.join(self.custom_dir, fn)
                child = QTreeWidgetItem([os.path.splitext(fn)[0]])
                child.setData(0, Qt.ItemDataRole.UserRole, {"kind": "file", "path": p})
                cust_root.addChild(child)
        
        self.tree.expandAll()
    
    def _on_double_clicked(self, item, _col):
        """Handle double-click on tree item."""
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if payload: 
            self.event_selected.emit(payload)
    
    def _on_ctx_menu(self, pos):
        """Handle context menu request."""
        item = self.tree.itemAt(pos)
        if not item or item.parent() is None: 
            return
        
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if not payload or payload.get("kind") != "file": 
            return
        
        menu = QMenu(self)
        act_del = menu.addAction("Delete")
        act = menu.exec(self.tree.viewport().mapToGlobal(pos))
        
        if act == act_del:
            try:
                os.remove(payload["path"])
                self.refresh()
            except Exception as e:
                QMessageBox.critical(self, "Delete failed", str(e))

class EditorDropProxy(QWidget):
    """Proxy widget that wraps the waveform editor and handles drag/drop."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.editor = WaveformEditorWidget(self)
        self.editor.setAcceptDrops(False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.editor)
        self._current_event: HapticEvent | None = None

    def set_event(self, evt: HapticEvent) -> None:
        self._current_event = evt
        self.editor.set_event(evt)

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME_WAVEFORM):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        if not e.mimeData().hasFormat(MIME_WAVEFORM):
            e.ignore()
            return

        try:
            raw = bytes(e.mimeData().data(MIME_WAVEFORM)).decode("utf-8")
            payload = json.loads(raw)
        except Exception:
            e.ignore()
            return

        # Modif. clavier (PyQt6: passer par QApplication)
        mods = QApplication.keyboardModifiers()
        # ✅ Par défaut on REPLACE pour que la forme corresponde au signal choisi
        drop_mod = (
            "add"       if (mods & Qt.KeyboardModifier.ShiftModifier) else
            "multiply"  if (mods & Qt.KeyboardModifier.AltModifier)   else
            "replace"
        )

        if isinstance(payload, dict):
            payload = dict(payload)
            payload["drop_mod"] = drop_mod

        # Déléguer à la fenêtre hôte (et pas au QSplitter) — et surtout UNE SEULE FOIS
        host = self.window()
        if hasattr(host, "handle_library_payload"):
            host.handle_library_payload(payload, compose=True)
            e.acceptProposedAction()
        else:
            e.ignore()


