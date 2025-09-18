
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
                           QLabel, QPushButton, QLineEdit, QListWidget,
                           QListWidgetItem, QTreeWidget, QTreeWidgetItem,
                           QMenu, QMessageBox, QAbstractItemView)
from ..core.constants import PREMADE_PATTERNS

class PatternVisualizationWidget(QWidget):
    """Clean library view with search, info panel, and primary actions."""
    pattern_selected = pyqtSignal(dict)
    pattern_deleted = pyqtSignal(str)

    def __init__(self, pattern_manager):
        super().__init__()
        self.pattern_manager = pattern_manager
        self._all: dict[str, dict] = {}
        self._by_name: dict[str, dict] = {}
        self._build_ui()
        self.refresh_patterns()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # header
        header = QHBoxLayout()
        ttl = QLabel("Your Pattern Library")
        ttl.setStyleSheet("font-weight:600;")
        header.addWidget(ttl); header.addStretch()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setMaximumWidth(90)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        # search
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter patterns…")
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)

        # list
        self.pattern_list = QListWidget()
        self.pattern_list.setUniformItemSizes(True)
        self.pattern_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.pattern_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        layout.addWidget(self.pattern_list, 1)

        # info
        self.info_label = QLabel("Select a pattern to view details")
        self.info_label.setObjectName("patternDescLabel")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        # actions
        row = QHBoxLayout()
        self.load_button = QPushButton("Load Pattern")
        self.load_button.setObjectName("loadSelectedBtn")
        self.load_button.setEnabled(False)
        self.delete_button = QPushButton("Delete")
        row.addWidget(self.load_button)
        row.addWidget(self.delete_button)
        row.addStretch()
        layout.addLayout(row)

        # wire
        self.refresh_button.clicked.connect(self.refresh_patterns)
        self.search.textChanged.connect(self._rebuild)
        self.pattern_list.itemSelectionChanged.connect(self._on_clicked)
        self.pattern_list.itemDoubleClicked.connect(lambda *_: self.load_selected_pattern())
        self.load_button.clicked.connect(self.load_selected_pattern)
        self.delete_button.clicked.connect(self._delete_current)

    # data ops
    def refresh_patterns(self):
        self._all = self.pattern_manager.get_all_patterns()
        self._by_name = {k: v for k, v in self._all.items()}
        self._rebuild()

    def _rebuild(self):
        q = self.search.text().strip().lower()
        self.pattern_list.clear()
        for name in sorted(self._by_name.keys()):
            if q and q not in name.lower():
                continue
            info = self._by_name[name]
            it = QListWidgetItem(name)
            cfg = info.get("config", {})
            it.setToolTip(f"{cfg.get('pattern_type','?')} • {len(cfg.get('actuators',[]))} actuator(s)")
            it.setSizeHint(QSize(it.sizeHint().width(), 30))
            self.pattern_list.addItem(it)
        self.info_label.setText(
            "No patterns found" if self.pattern_list.count()==0 else "Select a pattern to view details"
        )
        self.load_button.setEnabled(False)

    def _on_clicked(self):
        it = self.pattern_list.currentItem()
        if not it:
            self.load_button.setEnabled(False)
            self.info_label.setText("Select a pattern to view details")
            return
        self.load_button.setEnabled(True)
        info = self.pattern_manager.get_pattern_info(it.text())
        if not info:
            self.info_label.setText("Error loading pattern information")
            return
        cfg = info["config"]
        lines = [
            f"<b>{info.get('name', it.text())}</b>",
            f"<i>{info.get('description','')}</i>" if info.get('description') else "",
            f"<b>Type:</b> {cfg.get('pattern_type','?')}",
            f"<b>Actuators:</b> {cfg.get('actuators',[])}",
            f"<b>Intensity:</b> {cfg.get('intensity',0)}",
            f"<b>Frequency:</b> {cfg.get('frequency',0)}"
        ]
        wf = cfg.get("waveform", {})
        if wf: lines.append(f"<b>Waveform:</b> {wf.get('name','?')} ({wf.get('source','?')})")
        sp = cfg.get("specific_parameters", {})
        if sp:
            lines.append("<b>Specific Parameters:</b>")
            for k,v in sp.items(): lines.append(f"&nbsp;&nbsp;{k}: {v}")
        if info.get('timestamp'): lines.append(f"<br><small>Created: {info['timestamp']}</small>")
        self.info_label.setText("<br>".join([s for s in lines if s]))

    def load_selected_pattern(self):
        it = self.pattern_list.currentItem()
        if not it: return
        info = self.pattern_manager.get_pattern_info(it.text())
        if info:
            self.pattern_selected.emit(info)

    def _delete_current(self):
        it = self.pattern_list.currentItem()
        if not it: return
        name = it.text()
        if QMessageBox.question(self, "Delete Pattern",
                                f"Delete '{name}'?",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                               ) != QMessageBox.StandardButton.Yes:
            return
        if self.pattern_manager.delete_pattern(name):
            self.pattern_deleted.emit(name)
            self.refresh_patterns()


class PremadePatternPanel(QWidget):
    """Premade templates with search + description + primary action."""
    template_selected = pyqtSignal(dict)

    def __init__(self, presets: list[dict], parent=None):
        super().__init__(parent)
        self._all = list(presets)

        group = QGroupBox("Premade Patterns")
        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.addWidget(group)
        g = QVBoxLayout(group); g.setContentsMargins(8,6,8,8); g.setSpacing(6)

        # search
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Filter premade…")
        self.search.setClearButtonEnabled(True)
        g.addWidget(self.search)

        # list
        self.list = QListWidget(self)
        self.list.setUniformItemSizes(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        g.addWidget(self.list, 1)

        # info
        self.info = QLabel("Select a template to see details.")
        self.info.setObjectName("patternDescLabel")
        self.info.setWordWrap(True)
        g.addWidget(self.info)

        # actions
        self.btnLoad = QPushButton("Load to Waveform Lab", self)
        self.btnLoad.setObjectName("loadToWaveformBtn")
        self.btnLoad.setEnabled(False)
        g.addWidget(self.btnLoad)

        # wire
        self.search.textChanged.connect(self._rebuild)
        self.list.itemSelectionChanged.connect(self._on_sel)
        self.list.itemDoubleClicked.connect(lambda *_: self._emit_selected())
        self.btnLoad.clicked.connect(self._emit_selected)

        self._rebuild()

    def _rebuild(self):
        q = self.search.text().strip().lower()
        self.list.clear()
        for p in self._all:
            if q and q not in p["name"].lower():
                continue
            it = QListWidgetItem(p["name"])
            it.setToolTip(p.get("description",""))
            it.setSizeHint(QSize(it.sizeHint().width(), 30))
            self.list.addItem(it)
        self._on_sel()

    def _current(self) -> dict | None:
        it = self.list.currentItem()
        if not it: return None
        for p in self._all:
            if p["name"] == it.text():
                return p
        return None

    def _on_sel(self):
        p = self._current()
        self.btnLoad.setEnabled(p is not None)
        self.info.setText(
            f"<b>{p['name']}</b><br>{p.get('description','')}" if p
            else "Select a template to see details."
        )

    def _emit_selected(self):
        p = self._current()
        if p:
            self.template_selected.emit(p)


class UnifiedPatternLibraryWidget(QWidget):
    """
    Single Pattern Library view with two categories:
      - Pre-made (from PREMADE_PATTERNS)
      - Custom (from PatternLibraryManager)

    Signals (unchanged):
      - template_selected(dict)  → premade preset
      - pattern_selected(dict)   → custom pattern_info
      - pattern_deleted(str)     → emitted after successful delete of a custom pattern

    Changes:
      - Multi-select enabled (ExtendedSelection).
      - Load/Delete buttons removed; use right-click context menu.
      - Double-click loads ALL currently selected items.
    """
    template_selected = pyqtSignal(dict)
    pattern_selected = pyqtSignal(dict)
    pattern_deleted = pyqtSignal(str)

    def __init__(self, pattern_manager, premade_list: list[dict], parent=None):
        super().__init__(parent)
        self.pattern_manager = pattern_manager
        self._premade = list(premade_list)      # [{name, description, config}]
        self._custom_index: dict[str, dict] = {}  # name -> data

        layout = QVBoxLayout(self)

        # Header
        header = QHBoxLayout()
        ttl = QLabel("Pattern Library")
        ttl.setStyleSheet("font-weight:600;")
        header.addWidget(ttl)
        header.addStretch()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setMaximumWidth(90)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        # Search
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter patterns…")
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)

        # Tree (multi-select)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(18)
        self.tree.setObjectName("patternTree")
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        layout.addWidget(self.tree, 1)

        # Info (no bottom buttons anymore)
        self.info_label = QLabel("Select a pattern to view details")
        self.info_label.setObjectName("patternDescLabel")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        # Category roots
        self._premade_root = QTreeWidgetItem(self.tree, ["Pre-made"])
        self._custom_root  = QTreeWidgetItem(self.tree, ["Custom Patterns"])
        self._premade_root.setExpanded(True)
        self._custom_root.setExpanded(True)
        self._style_category_item(self._premade_root)
        self._style_category_item(self._custom_root)

        # Wiring
        self.refresh_button.clicked.connect(self.refresh_patterns)
        self.search.textChanged.connect(self._rebuild_tree)
        self.tree.itemSelectionChanged.connect(self._on_select_changed)
        self.tree.itemDoubleClicked.connect(lambda *_: self._act_load_selected())
        self.tree.customContextMenuRequested.connect(self._context_menu)

        self.refresh_patterns()

    # ---------- Public API (compat) ----------
    def refresh_patterns(self):
        """Re-scan custom patterns and rebuild the tree."""
        all_custom = self.pattern_manager.get_all_patterns()  # {name: pattern_data}
        self._custom_index = {name: data for name, data in all_custom.items()}
        self._rebuild_tree()

    # ---------- Internals ----------
    def _style_category_item(self, it: QTreeWidgetItem) -> None:
        """Bold, highlighted, non-selectable category row."""
        f = it.font(0); f.setBold(True); it.setFont(0, f)
        flags = it.flags()
        flags &= ~Qt.ItemFlag.ItemIsSelectable
        flags |= Qt.ItemFlag.ItemIsEnabled
        it.setFlags(flags)
        it.setFirstColumnSpanned(True)
        it.setSizeHint(0, QSize(0, 26))
        it.setBackground(0, QBrush(QColor("#EAF2FF")))
        it.setForeground(0, QBrush(QColor("#111827")))

    def _rebuild_tree(self):
        premade_open = self._premade_root.isExpanded()
        custom_open  = self._custom_root.isExpanded()

        self._premade_root.takeChildren()
        self._custom_root.takeChildren()

        query = (self.search.text() or "").strip().lower()

        # Premade
        for p in self._premade:
            name = p.get("name", "Preset")
            if query and query not in name.lower():
                continue
            it = QTreeWidgetItem([name])
            it.setData(0, Qt.ItemDataRole.UserRole, ("premade", p))
            self._premade_root.addChild(it)

        # Custom
        for name, info in sorted(self._custom_index.items()):
            if query and query not in name.lower():
                continue
            it = QTreeWidgetItem([name])
            it.setData(0, Qt.ItemDataRole.UserRole, ("custom", name))
            self._custom_root.addChild(it)

        self._premade_root.setExpanded(premade_open)
        self._custom_root.setExpanded(custom_open)

        total_leaves = self._premade_root.childCount() + self._custom_root.childCount()
        self.info_label.setText("No patterns found" if total_leaves == 0
                                else "Select a pattern to view details")

    def _is_leaf(self, it: QTreeWidgetItem | None) -> bool:
        return bool(it and it.parent() in (self._premade_root, self._custom_root))

    def _payload_for_item(self, it: QTreeWidgetItem):
        return it.data(0, Qt.ItemDataRole.UserRole)  # ("premade", preset) or ("custom", name)

    def _selected_leaves(self):
        out = []
        for it in self.tree.selectedItems():
            if self._is_leaf(it):
                out.append(self._payload_for_item(it))
        return out  # list of tuples

    def _on_select_changed(self):
        sels = self._selected_leaves()
        if len(sels) == 1:
            kind, payload = sels[0]
            if kind == "premade":
                p = payload; cfg = p.get("config", {})
                lines = [
                    f"<b>{p.get('name','Preset')}</b>",
                    f"<i>{p.get('description','')}</i>" if p.get("description") else "",
                    f"<b>Type:</b> {cfg.get('pattern_type','?')}",
                    f"<b>Actuators:</b> {cfg.get('actuators',[])}",
                    f"<b>Intensity:</b> {cfg.get('intensity','')}",
                    f"<b>Frequency:</b> {cfg.get('frequency','')}",
                ]
                wf = cfg.get("waveform", {})
                if wf: lines.append(f"<b>Waveform:</b> {wf.get('name','?')}")
                sp = cfg.get("specific_parameters", {})
                if sp:
                    lines.append("<b>Specific Parameters:</b>")
                    for k, v in sp.items():
                        lines.append(f"&nbsp;&nbsp;{k}: {v}")
                self.info_label.setText("<br>".join([s for s in lines if s]))
            else:  # custom
                name = payload
                info = self.pattern_manager.get_pattern_info(name) or {"config": {}}
                cfg = info.get("config", {})
                lines = [
                    f"<b>{info.get('name', name)}</b>",
                    f"<i>{info.get('description','')}</i>" if info.get("description") else "",
                    f"<b>Type:</b> {cfg.get('pattern_type','?')}",
                    f"<b>Actuators:</b> {cfg.get('actuators',[])}",
                    f"<b>Intensity:</b> {cfg.get('intensity','')}",
                    f"<b>Frequency:</b> {cfg.get('frequency','')}",
                ]
                wf = cfg.get("waveform", {})
                if wf: lines.append(f"<b>Waveform:</b> {wf.get('name','?')}")
                sp = cfg.get("specific_parameters", {})
                if sp:
                    lines.append("<b>Specific Parameters:</b>")
                    for k, v in sp.items():
                        lines.append(f"&nbsp;&nbsp;{k}: {v}")
                if info.get('timestamp'):
                    lines.append(f"<br><small>Created: {info['timestamp']}</small>")
                self.info_label.setText("<br>".join([s for s in lines if s]))
        elif len(sels) > 1:
            # Mixed selection summary
            n_premade = sum(1 for k, _ in sels if k == "premade")
            n_custom  = sum(1 for k, _ in sels if k == "custom")
            self.info_label.setText(f"{len(sels)} patterns selected "
                                    f"({n_premade} pre-made, {n_custom} custom).")
        else:
            self.info_label.setText("Select a pattern to view details")

    # ---------- Actions ----------
    def _act_load_selected(self):
        sels = self._selected_leaves()
        if not sels:
            return
        # Emit load signals for all selected
        for kind, payload in sels:
            if kind == "premade":
                self.template_selected.emit(payload)  # preset dict
            else:
                name = payload
                info = self.pattern_manager.get_pattern_info(name)
                if info:
                    self.pattern_selected.emit(info)

    def _act_delete_selected(self):
        sels = self._selected_leaves()
        # Keep only custom items
        names = [payload for kind, payload in sels if kind == "custom"]
        if not names:
            return
        if QMessageBox.question(
            self, "Delete Patterns", f"Delete {len(names)} custom pattern(s)?"
        ) != QMessageBox.StandardButton.Yes:
            return
        deleted_any = False
        for n in names:
            if self.pattern_manager.delete_pattern(n):
                self.pattern_deleted.emit(n)
                deleted_any = True
        if deleted_any:
            self.refresh_patterns()

    def _context_menu(self, pos):
        sels = self._selected_leaves()
        if not sels:
            # If no selection, try the item under the cursor (single)
            it = self.tree.itemAt(pos)
            if not self._is_leaf(it):
                return
            it.setSelected(True)
            sels = self._selected_leaves()
            if not sels:
                return

        has_custom = any(kind == "custom" for kind, _ in sels)

        menu = QMenu(self)
        act_load = menu.addAction("Load selected")
        if has_custom:
            act_del = menu.addAction("Delete selected (custom only)")
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if not chosen:
            return
        if chosen == act_load:
            self._act_load_selected()
        elif has_custom and chosen.text().startswith("Delete selected"):
            self._act_delete_selected()