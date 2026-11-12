"""
Left Toolbox panel showing categorized electronic components with drag-and-drop,
click-to-place, and debounced online Fritzing compatibility search.
"""
from __future__ import annotations

import os
import threading
from PyQt6.QtCore import Qt, QMimeData, QObject, QPoint, QRectF, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QDrag, QFont, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QVBoxLayout, QWidget
)

from app.components.fritzing_part import FritzingComponentDef
from app.components.registry import REGISTRY
from app.models.component_def import ComponentDef
from app.models.placed_component import PlacedComponent
from app.utils.fritzing_importer import (
    import_fritzing_file,
    import_fritzing_file_with_options,
    search_compatible_fritzing_parts,
)


class _OnlineSearchSignals(QObject):
    found_part = pyqtSignal(int, object)  # (seq, FritzingComponentDef)
    finished = pyqtSignal(int, int, str)  # (seq, count, error_msg)


class ComponentCard(QFrame):
    clicked = pyqtSignal(str)  # type_id
    delete_requested = pyqtSignal(str)  # type_id

    def __init__(self, comp_def: ComponentDef, is_online: bool = False, parent=None):
        super().__init__(parent)
        self.comp_def = comp_def
        self.is_online = is_online
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        if comp_def.description:
            self.setToolTip(comp_def.description)

        border_col = "#3d5a80" if is_online else "#383a40"
        self.setStyleSheet(f"""
            ComponentCard {{
                background-color: #2b2d31;
                border: 1px solid {border_col};
                border-radius: 6px;
                padding: 4px;
            }}
            ComponentCard:hover {{
                background-color: #35373c;
                border: 1px solid #5865f2;
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)

        # Generate thumbnail icon
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(48, 48)
        self.icon_label.setPixmap(self._render_thumbnail(48, 48))
        layout.addWidget(self.icon_label)

        # Text labels
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        info_layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel(comp_def.name)
        title.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        title.setWordWrap(True)
        title.setStyleSheet("color: #f2f3f5;")
        info_layout.addWidget(title)

        off_count = len(getattr(comp_def, "off_grid_pins", []))
        if len(comp_def.pins) == 0 and off_count > 0:
            pin_text = f"{off_count} pins • Pins cannot align with perfboard; only connectable via jumpers"
            if is_online and isinstance(comp_def, FritzingComponentDef):
                src = comp_def.source_info.get("source_name", "Fritzing")
                sub_text = f"{pin_text} • {src} • Drag to save"
                sub_color = "#f0a050"
            else:
                sub_text = pin_text
                sub_color = "#f0a050"
        else:
            pin_text = f"{len(comp_def.pins)}+{off_count} jumper pins" if off_count > 0 else f"{len(comp_def.pins)} pins"
            if is_online and isinstance(comp_def, FritzingComponentDef):
                src = comp_def.source_info.get("source_name", "Fritzing")
                sub_text = f"{pin_text} • {src} • Drag to save"
                sub_color = "#7aa2f7"
            else:
                sub_text = f"{pin_text} • {comp_def.default_label}"
                sub_color = "#949ba4"

        desc = QLabel(sub_text)
        desc.setFont(QFont("Arial", 8))
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {sub_color};")
        info_layout.addWidget(desc)

        layout.addLayout(info_layout, 1)

        if not is_online and isinstance(comp_def, FritzingComponentDef):
            btn_del = QPushButton("✕")
            btn_del.setFixedSize(18, 18)
            btn_del.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn_del.setToolTip("Delete downloaded component")
            btn_del.setStyleSheet(
                "QPushButton { background: transparent; border: none; border-radius: 3px; "
                "color: #949ba4; font-size: 11px; font-weight: bold; padding: 0px; }"
                "QPushButton:hover { background-color: #da373c; color: #ffffff; }"
            )
            btn_del.clicked.connect(lambda: self.delete_requested.emit(self.comp_def.type_id))
            layout.addWidget(btn_del, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

        self._drag_start_pos = QPoint()

    def _render_thumbnail(self, w: int, h: int) -> QPixmap:
        pix = QPixmap(w, h)
        pix.fill(QColor(24, 25, 28))

        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        temp_inst = PlacedComponent(
            type_id=self.comp_def.type_id,
            grid_x=0, grid_y=0,
            label=self.comp_def.default_label
        )

        pitch = 14.0
        try:
            bounds = self.comp_def.get_shape(temp_inst, pitch).boundingRect()
        except Exception:
            bounds = QRectF()

        if bounds.isEmpty() or bounds.width() <= 0 or bounds.height() <= 0:
            bounds = QRectF(-pitch, -pitch, pitch * 2.0, pitch * 2.0)

        pad = 8.0
        scale = min((w - pad) / bounds.width(), (h - pad) / bounds.height(), 1.1)
        scale = max(scale, 0.05)

        painter.translate(w / 2.0, h / 2.0)
        painter.scale(scale, scale)
        painter.translate(-bounds.center().x(), -bounds.center().y())

        try:
            self.comp_def.draw_top(painter, temp_inst, pitch)
        except Exception:
            pass
        painter.end()
        return pix

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            if (event.pos() - self._drag_start_pos).manhattanLength() > 5:
                drag = QDrag(self)
                mime = QMimeData()
                mime.setData("application/x-perfboard-component", self.comp_def.type_id.encode("utf-8"))
                drag.setMimeData(mime)
                drag.setPixmap(self.icon_label.pixmap())
                drag.setHotSpot(QPoint(24, 24))
                drag.exec(Qt.DropAction.CopyAction)
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.comp_def.type_id)
        super().mouseReleaseEvent(event)


class _CollapsibleCategory(QWidget):
    """Collapsible category header + card container for the component toolbox."""

    toggled = pyqtSignal(str, bool)  # (category_name, is_collapsed)

    def __init__(self, category: str, count: int, collapsed: bool = False, parent=None):
        super().__init__(parent)
        self.category = category
        self._total_count = count
        self._collapsed = collapsed

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.header_btn = QPushButton()
        self.header_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.header_btn.setFont(QFont("Arial", 9, QFont.Weight.Bold))
        self.header_btn.setStyleSheet("""
            QPushButton {
                color: #5865f2;
                background: transparent;
                border: none;
                border-bottom: 1px solid #383a40;
                padding: 6px 2px 3px 2px;
                margin-top: 4px;
                text-align: left;
            }
            QPushButton:hover {
                color: #7983f5;
            }
        """)
        self.header_btn.clicked.connect(self.toggle)
        layout.addWidget(self.header_btn)

        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(8)
        layout.addWidget(self.content)

        self._apply_state(count)

    def _apply_state(self, visible_count: int):
        arrow = "▸" if self._collapsed else "▾"
        self.header_btn.setText(f"{arrow}  {self.category.upper()} ({visible_count})")
        self.content.setVisible(not self._collapsed)

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, collapsed: bool, visible_count: int | None = None):
        self._collapsed = bool(collapsed)
        self._apply_state(self._total_count if visible_count is None else visible_count)

    def toggle(self):
        self._collapsed = not self._collapsed
        self._apply_state(self._total_count)
        self.toggled.emit(self.category, self._collapsed)


class ToolboxWidget(QWidget):
    component_selected = pyqtSignal(str)  # type_id to place

    _ONLINE_SEARCH_DELAY_MS = 2000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(260)
        self.setMaximumWidth(340)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # Header Title
        title_lbl = QLabel("COMPONENTS TOOLBOX")
        title_lbl.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color: #dbdee1; letter-spacing: 0.5px;")
        main_layout.addWidget(title_lbl)

        # Search filter (local instant + 2s delayed online Fritzing search)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍 Search local & online Fritzing...")
        self.search_box.textChanged.connect(self._on_search_text_changed)
        self.search_box.returnPressed.connect(self._on_search_return_pressed)
        main_layout.addWidget(self.search_box)

        self.import_btn = QPushButton("📂 Import Fritzing part from file...")
        self.import_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.import_btn.clicked.connect(self._on_import_file_clicked)
        main_layout.addWidget(self.import_btn)

        hint_lbl = QLabel("💡 Drag onto board or click to place. Online compatible parts appear 2s after pausing typing.")
        hint_lbl.setFont(QFont("Arial", 8))
        hint_lbl.setWordWrap(True)
        hint_lbl.setStyleSheet("color: #949ba4; padding-bottom: 4px;")
        main_layout.addWidget(hint_lbl)

        # Scroll Area for local + online component lists
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 4, 0)
        self.list_layout.setSpacing(10)

        # Local components section
        self.local_container = QWidget()
        self.local_layout = QVBoxLayout(self.local_container)
        self.local_layout.setContentsMargins(0, 0, 0, 0)
        self.local_layout.setSpacing(10)
        self.list_layout.addWidget(self.local_container)

        # Online Fritzing search results section (hidden until active search)
        self.online_section = QWidget()
        online_section_layout = QVBoxLayout(self.online_section)
        online_section_layout.setContentsMargins(0, 4, 0, 0)
        online_section_layout.setSpacing(8)

        self.online_header = QLabel("ONLINE FRITZING RESULTS")
        self.online_header.setFont(QFont("Arial", 9, QFont.Weight.Bold))
        self.online_header.setStyleSheet("""
            color: #7aa2f7;
            border-bottom: 1px solid #383a40;
            padding-top: 6px;
            padding-bottom: 3px;
            margin-top: 4px;
        """)
        online_section_layout.addWidget(self.online_header)

        self.online_status_lbl = QLabel("")
        self.online_status_lbl.setFont(QFont("Arial", 8))
        self.online_status_lbl.setWordWrap(True)
        self.online_status_lbl.setStyleSheet("color: #949ba4;")
        online_section_layout.addWidget(self.online_status_lbl)

        self.online_cards_container = QWidget()
        self.online_cards_layout = QVBoxLayout(self.online_cards_container)
        self.online_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.online_cards_layout.setSpacing(8)
        online_section_layout.addWidget(self.online_cards_container)

        self.online_section.setVisible(False)
        self.list_layout.addWidget(self.online_section)
        self.list_layout.addStretch()

        self.cards: list[tuple[ComponentDef, ComponentCard, _CollapsibleCategory]] = []
        self._category_sections: dict[str, _CollapsibleCategory] = {}
        self._collapsed_categories: set[str] = set()
        self._online_cards: list[tuple[str, ComponentCard]] = []
        self._populate_components()

        self.scroll_area.setWidget(self.list_container)
        main_layout.addWidget(self.scroll_area)

        # Online search state & 2-second debounce timer
        self._search_seq: int = 0
        self._active_cancel_event: threading.Event | None = None
        self._online_signals = _OnlineSearchSignals(self)
        self._online_signals.found_part.connect(self._on_online_part_found)
        self._online_signals.finished.connect(self._on_online_search_finished)

        self._online_debounce = QTimer(self)
        self._online_debounce.setSingleShot(True)
        self._online_debounce.setInterval(self._ONLINE_SEARCH_DELAY_MS)
        self._online_debounce.timeout.connect(self._trigger_online_search)

        REGISTRY.add_install_listener(self._on_part_permanently_installed)

    def _clear_layout(self, layout: QVBoxLayout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _populate_components(self):
        self.cards.clear()
        self._category_sections.clear()
        self._clear_layout(self.local_layout)
        categories = REGISTRY.get_categories()

        for cat in categories:
            comps = REGISTRY.get_by_category(cat)
            if not comps:
                continue

            section = _CollapsibleCategory(
                cat,
                len(comps),
                collapsed=(cat in self._collapsed_categories),
            )
            section.toggled.connect(self._on_category_toggled)
            self._category_sections[cat] = section
            self.local_layout.addWidget(section)

            for comp in comps:
                card = ComponentCard(comp, is_online=False)
                card.clicked.connect(self.component_selected.emit)
                card.delete_requested.connect(self._on_delete_downloaded_component)
                section.content_layout.addWidget(card)
                self.cards.append((comp, card, section))

    def _on_delete_downloaded_component(self, type_id: str):
        comp = REGISTRY.get(type_id)
        if comp is None:
            return
        reply = QMessageBox.question(
            self,
            "Delete Component",
            f"Do you want to delete '{comp.name}'?\n\n"
            "• If you downloaded it using the built-in search box, you can search and download it again anytime.\n\n"
            "• If you imported it from a file, you will need to import that file again to use it in the future.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if REGISTRY.uninstall_downloaded(type_id):
            self._populate_components()
            self._filter_components(self.search_box.text())

    def _on_category_toggled(self, category: str, is_collapsed: bool):
        if is_collapsed:
            self._collapsed_categories.add(category)
        else:
            self._collapsed_categories.discard(category)

    def _on_part_permanently_installed(self, type_id: str):
        # Remove from temporary online results list and rebuild local categories
        remaining: list[tuple[str, ComponentCard]] = []
        for tid, card in self._online_cards:
            if tid == type_id:
                self.online_cards_layout.removeWidget(card)
                card.deleteLater()
            else:
                remaining.append((tid, card))
        self._online_cards = remaining

        self._populate_components()
        self._filter_components(self.search_box.text())

    def _on_import_file_clicked(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import Fritzing Part", "",
            "Fritzing Parts (*.fzpz *.fzp);;All Files (*)",
        )
        if not paths:
            return
        imported: list[str] = []
        failures: list[str] = []
        for path in paths:
            orig_comp, scaled_comp, scale_factor, reason = import_fritzing_file_with_options(path)
            name = os.path.basename(path)
            if orig_comp is None:
                failures.append(f"{name}: {reason}")
                continue
            comp_def = orig_comp
            if scaled_comp is not None and scale_factor is not None:
                total_pins = len(scaled_comp.pins) + len(scaled_comp.off_grid_pins)
                box = QMessageBox(self)
                box.setWindowTitle("Scale Unaligned Part?")
                box.setIcon(QMessageBox.Icon.Question)
                box.setText(
                    f"'{orig_comp.name}' has unaligned pins at its original size "
                    f"({orig_comp.svg_width_mm:.1f} × {orig_comp.svg_height_mm:.1f} mm).\n\n"
                    f"Scaling by {scale_factor:.2f}× ({scaled_comp.svg_width_mm:.1f} × {scaled_comp.svg_height_mm:.1f} mm) "
                    f"aligns {len(scaled_comp.pins)}/{total_pins} pins to the 2.54 mm perfboard grid.\n\n"
                    "Which version would you like to import?"
                )
                btn_scaled = box.addButton(
                    f"Import Scaled ({scale_factor:.2f}×)", QMessageBox.ButtonRole.AcceptRole
                )
                btn_orig = box.addButton("Import Original Scale", QMessageBox.ButtonRole.ActionRole)
                box.addButton(QMessageBox.StandardButton.Cancel)
                box.setDefaultButton(btn_scaled)
                box.exec()
                clicked = box.clickedButton()
                if clicked == btn_scaled:
                    comp_def = scaled_comp
                elif clicked == btn_orig:
                    comp_def = orig_comp
                else:
                    continue

            if REGISTRY.is_installed(comp_def.type_id):
                failures.append(f"{name}: already imported")
            else:
                REGISTRY.register_preview(comp_def)
                REGISTRY.persist_if_remote(comp_def.type_id)
                imported.append(comp_def.name)

        if failures and imported:
            msg = "Imported:\n" + "\n".join(imported) + "\n\nFailed:\n" + "\n".join(failures)
            QMessageBox.warning(self, "Import Fritzing Part", msg)
        elif failures:
            QMessageBox.warning(self, "Import Fritzing Part", "\n".join(failures))
        elif imported:
            QMessageBox.information(
                self, "Import Fritzing Part", "Imported: " + ", ".join(imported)
            )

    def _on_search_text_changed(self, query: str):
        self._filter_components(query)
        self._cancel_online_search(hide_section=True)
        if len(query.strip()) >= 2:
            self._online_debounce.start()

    def _on_search_return_pressed(self):
        query = self.search_box.text().strip()
        if len(query) >= 2 and self._online_debounce.isActive():
            self._online_debounce.stop()
            self._trigger_online_search()

    def _cancel_online_search(self, hide_section: bool = True):
        self._online_debounce.stop()
        self._search_seq += 1
        if self._active_cancel_event is not None:
            self._active_cancel_event.set()
            self._active_cancel_event = None
        self._online_cards.clear()
        self._clear_layout(self.online_cards_layout)
        if hide_section:
            self.online_section.setVisible(False)
            self.online_status_lbl.setText("")

    def _trigger_online_search(self):
        query = self.search_box.text().strip()
        if len(query) < 2:
            return

        self._cancel_online_search(hide_section=False)
        seq = self._search_seq
        cancel_ev = threading.Event()
        self._active_cancel_event = cancel_ev

        self.online_section.setVisible(True)
        self.online_status_lbl.setText(f"🌐 Searching open-source Fritzing libraries for '{query}'...")

        exclude_ids = {c.type_id for c in REGISTRY.get_all()}

        def _worker():
            count = 0
            err_msg = ""
            try:
                def _on_match(comp_def: FritzingComponentDef):
                    nonlocal count
                    if cancel_ev.is_set():
                        return
                    count += 1
                    try:
                        self._online_signals.found_part.emit(seq, comp_def)
                    except RuntimeError:
                        pass

                search_compatible_fritzing_parts(
                    query,
                    exclude_type_ids=exclude_ids,
                    cancel_event=cancel_ev,
                    on_compatible_cb=_on_match,
                    limit_candidates=24,
                )
            except Exception as exc:
                err_msg = str(exc)

            if not cancel_ev.is_set():
                try:
                    self._online_signals.finished.emit(seq, count, err_msg)
                except RuntimeError:
                    pass

        threading.Thread(target=_worker, name="PerfBoardFritzingSearch", daemon=True).start()

    def _on_online_part_found(self, seq: int, comp_def: FritzingComponentDef):
        if seq != self._search_seq:
            return
        if not comp_def._get_renderer().isValid():
            return

        REGISTRY.register_preview(comp_def)
        card = ComponentCard(comp_def, is_online=True)
        card.clicked.connect(self.component_selected.emit)
        self.online_cards_layout.addWidget(card)
        self._online_cards.append((comp_def.type_id, card))

    def _on_online_search_finished(self, seq: int, count: int, err_msg: str):
        if seq != self._search_seq:
            return
        shown = len(self._online_cards)
        if err_msg:
            self.online_status_lbl.setText(f"⚠ Online search error: {err_msg}")
        elif shown == 0:
            self.online_status_lbl.setText("🌐 No compatible 2.54 mm online Fritzing parts found.")
        else:
            self.online_status_lbl.setText(
                f"🌐 {shown} compatible part(s) verified — drag onto board to save."
            )

    def _filter_components(self, query: str):
        query = query.strip().lower()
        visible_in_cat: dict[str, int] = {}

        for comp, card, _section in self.cards:
            matches = (
                query in comp.name.lower() or
                query in comp.category.lower() or
                query in comp.default_label.lower() or
                any(query in tag.lower() for tag in comp.tags)
            )
            card.setVisible(matches)
            if matches:
                visible_in_cat[comp.category] = visible_in_cat.get(comp.category, 0) + 1

        for cat, section in self._category_sections.items():
            vis_count = visible_in_cat.get(cat, 0)
            section.setVisible(vis_count > 0)
            if query:
                if vis_count > 0:
                    section.set_collapsed(False, visible_count=vis_count)
            else:
                section.set_collapsed(cat in self._collapsed_categories)
