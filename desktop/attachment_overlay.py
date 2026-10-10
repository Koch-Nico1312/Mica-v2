"""Visible document selection with local extraction and removable context."""
from __future__ import annotations
import threading
import tempfile
from pathlib import Path
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget
from desktop.ui_settings import _HudOverlay
from desktop.core.attachments import extract_attachment, attachment_changed
from desktop.ui_theme import C, ensure_ui_font


class AttachmentOverlay(_HudOverlay):
    changed = pyqtSignal(list)
    new_conversation = pyqtSignal()
    _extracted = pyqtSignal(dict, str, int)
    _changes_checked = pyqtSignal(list, int)
    modified = pyqtSignal(list)
    capture_ready = pyqtSignal(str)
    compare_requested = pyqtSignal()
    tasks_requested = pyqtSignal()
    cards_requested = pyqtSignal()
    review_requested = pyqtSignal()
    _OW, _OH = 620, 500

    def __init__(self, parent=None):
        super().__init__(parent)
        ensure_ui_font()
        self.setFont(QFont("Segoe UI", 9))
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            AttachmentOverlay {{background:{C.PANEL}; border:1px solid {C.BORDER}; border-radius:18px;}}
            QLabel,QCheckBox {{color:{C.TEXT}; background:transparent;}}
            QScrollArea {{background:{C.PANEL}; border:none;}}
            QPushButton {{background:{C.PANEL2}; color:{C.TEXT}; border:1px solid {C.BORDER}; border-radius:8px; padding:8px;}}
            QPushButton:hover {{background:{C.PRI_GHO};}}
        """)
        self.setFixedSize(self._OW, self._OH)
        self._documents, self._selected, self._lock = {}, set(), threading.RLock()
        self._loading = False
        self._generation = 0
        self._checking = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        title = QLabel("Dateien im Gespräch")
        title.setStyleSheet("font-size:20px; font-weight:600;")
        layout.addWidget(title)
        note = QLabel("Nur angehakte Dateien werden für Text und Sprache verwendet. PDF und Text werden lokal gelesen; bei Screenshots wird der sichtbare Text lokal erkannt. Inhalte bleiben im Arbeitsspeicher.")
        note.setWordWrap(True)
        layout.addWidget(note)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setStyleSheet(f"background:{C.PANEL};")
        self.rows = QVBoxLayout(content)
        self.rows.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self.status = QLabel("Ziehe eine Datei auf das Eingabefeld.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        for title, signal in [('Aufgaben erstellen', self.tasks_requested), ('Lernkarten erstellen', self.cards_requested), ('Karten wiederholen', self.review_requested)]:
            button = QPushButton(title)
            button.clicked.connect(signal.emit)
            actions.addWidget(button)
        layout.addLayout(actions)
        buttons = QHBoxLayout()
        self.inspect_button = QPushButton('Infos / Suche')
        self.inspect_button.clicked.connect(self.inspect_documents)
        buttons.addWidget(self.inspect_button)
        compare = QPushButton('Änderungen')
        compare.clicked.connect(self.compare_requested.emit)
        buttons.addWidget(compare)
        reset = QPushButton("Neues Gespräch")
        reset.clicked.connect(self.new_conversation.emit)
        buttons.addWidget(reset)
        clear = QPushButton("Alle Dateien entfernen")
        clear.clicked.connect(self.clear)
        buttons.addWidget(clear)
        close = QPushButton("Schließen")
        close.clicked.connect(self.hide)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self._extracted.connect(self._ready)
        self._changes_checked.connect(self._changed_files)
        self._watch_timer = QTimer(self)
        self._watch_timer.timeout.connect(self.check_changes)
        self._watch_timer.start(3000)

    def check_changes(self):
        if self._checking:
            return
        with self._lock:
            docs = [dict(doc) for key, doc in self._documents.items() if key in self._selected and not doc.get("changed")]
        if not docs:
            return
        self._checking = True
        generation = self._generation
        def worker():
            changed = [doc["id"] for doc in docs if attachment_changed(doc)]
            self._changes_checked.emit(changed, generation)
        threading.Thread(target=worker, name="mica-document-watch", daemon=True).start()

    def inspect_documents(self):
        from desktop.document_inspection_dialog import DocumentInspectionDialog
        DocumentInspectionDialog(self, self.checkpoint_documents()).exec()

    def _changed_files(self, identifiers, generation):
        self._checking = False
        if generation != self._generation:
            return
        for identifier in identifiers:
            if identifier in self._documents:
                self._documents[identifier]["changed"] = True
        if identifiers:
            self.status.setText("Ausgewählte Datei geändert oder nicht mehr erreichbar. Der bisherige Inhalt bleibt ausgewählt. Neu einlesen übernimmt die aktuelle Version.")
            self._render()
            self.modified.emit(self.changed_titles())

    def changed_titles(self):
        with self._lock:
            return [doc["title"] for identifier, doc in self._documents.items() if identifier in self._selected and doc.get("changed")]

    def reload_file(self, identifier):
        if self._loading or identifier not in self._documents:
            return
        path = self._documents[identifier].get("local_path")
        if not path:
            return
        self._loading = True
        generation = self._generation
        self.status.setText("Aktuelle Datei wird lokal gelesen …")
        def worker():
            try:
                doc, error = extract_attachment(path), ""
                doc["id"], doc["_replace"] = identifier, True
            except Exception as exc:
                doc, error = {}, str(exc)
            self._extracted.emit(doc, error, generation)
        threading.Thread(target=worker, name="mica-document-reload", daemon=True).start()

    def snapshot(self):
        with self._lock:
            return [{key: doc[key] for key in ("id", "title", "body", "source")}
                    for identifier, doc in self._documents.items() if identifier in self._selected]

    def checkpoint_documents(self):
        with self._lock:
            return [dict(doc) for identifier, doc in self._documents.items() if identifier in self._selected]

    def replace_documents(self, documents):
        self.clear()
        with self._lock:
            self._documents = {doc['id']: dict(doc) for doc in documents}
            self._selected = set(self._documents)
        self._render()
        self.changed.emit(self.snapshot())

    def add_file(self, path):
        if self._loading:
            self.status.setText("Eine Datei wird bereits gelesen. Bitte kurz warten.")
            return
        if len(self._documents) >= 8:
            self.status.setText("Höchstens acht Dateien; entferne zuerst eine Datei.")
            return
        self._loading = True
        generation = self._generation
        self.status.setText("Datei wird lokal gelesen …")
        def worker():
            try:
                doc, error = extract_attachment(path), ""
            except Exception as exc:
                doc, error = {}, str(exc)
            self._extracted.emit(doc, error, generation)
        threading.Thread(target=worker, name="mica-document-reader", daemon=True).start()

    def add_capture(self, image, title, controls=''):
        if self._loading or len(self._documents) >= 8:
            self.status.setText("Bitte die laufende Datei abwarten oder zuerst eine Datei entfernen.")
            return
        self._loading = True
        generation = self._generation
        self.status.setText("Fenstertext wird lokal erkannt …")
        def worker():
            try:
                with tempfile.TemporaryDirectory(prefix="mica-window-") as directory:
                    path = Path(directory) / "window.png"
                    if not image.save(str(path), "PNG"):
                        raise ValueError("Fensteraufnahme konnte nicht gelesen werden.")
                    try:
                        doc = extract_attachment(str(path))
                    except ValueError:
                        if not controls:
                            raise
                        import uuid
                        doc = {'id': uuid.uuid4().hex, 'body': '', 'source': 'screenshot'}
                if controls:
                    doc['body'] = ('Bedienelemente (sichtbare Beschriftungen):\n' + controls + '\n\nFenstertext (OCR):\n' + doc['body'])[:32000]
                doc.pop("local_path", None)
                doc.pop("fingerprint", None)
                doc["title"] = ("Fenster: " + title)[:160]
                doc["_capture_prompt"] = True
                error = ""
            except Exception as exc:
                doc, error = {}, str(exc)
            self._extracted.emit(doc, error, generation)
        threading.Thread(target=worker, name="mica-window-ocr", daemon=True).start()

    def _ready(self, doc, error, generation=None):
        if generation is not None and generation != self._generation:
            return
        self._loading = False
        if error:
            self.status.setText("Datei nicht hinzugefügt: " + error)
            return
        replacing = doc.pop("_replace", False)
        capture_prompt = doc.pop("_capture_prompt", False)
        if replacing and doc["id"] not in self._documents:
            return
        with self._lock:
            was_selected = doc["id"] in self._selected
            if replacing:
                self._selected.discard(doc["id"])
            self._documents[doc["id"]] = doc
            if (not replacing or was_selected) and sum(len(item["body"]) for item in self.snapshot()) + len(doc["body"]) <= 64000:
                self._selected.add(doc["id"])
        self._render()
        self.status.setText(("Datei neu eingelesen." if replacing else "Datei hinzugefügt.") + (" Es werden die ersten 32.000 Zeichen verwendet." if doc.get("truncated") else ""))
        self.changed.emit(self.snapshot())
        if capture_prompt and doc["id"] in self._selected:
            self.capture_ready.emit(doc["title"])

    def _toggle(self, identifier, checked):
        with self._lock:
            if checked:
                total = sum(len(doc["body"]) for doc in self.snapshot())
                if total + len(self._documents[identifier]["body"]) > 64000:
                    self.status.setText("Die Auswahl darf zusammen höchstens 64.000 Zeichen enthalten.")
                    self._render()
                    return
                self._selected.add(identifier)
            else:
                self._selected.discard(identifier)
        self._render()
        self.changed.emit(self.snapshot())

    def remove(self, identifier):
        with self._lock:
            self._documents.pop(identifier, None)
            self._selected.discard(identifier)
        self._render()
        self.changed.emit(self.snapshot())

    def clear(self):
        with self._lock:
            self._generation += 1
            self._loading = False
            self._documents.clear()
            self._selected.clear()
        self._render()
        self.changed.emit([])

    def _render(self):
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        for identifier, doc in self._documents.items():
            row = QWidget()
            layout = QHBoxLayout(row)
            box = QCheckBox(doc["title"] + (" · Geändert" if doc.get("changed") else ""))
            box.setChecked(identifier in self._selected)
            box.setToolTip(f"{doc['source']} · {len(doc['body'])} Zeichen")
            box.toggled.connect(lambda checked, key=identifier: self._toggle(key, checked))
            layout.addWidget(box, 1)
            if doc.get("changed"):
                reload = QPushButton("Neu einlesen")
                reload.clicked.connect(lambda checked=False, key=identifier: self.reload_file(key))
                layout.addWidget(reload)
            remove = QPushButton("Entfernen")
            remove.clicked.connect(lambda checked=False, key=identifier: self.remove(key))
            layout.addWidget(remove)
            self.rows.addWidget(row)
