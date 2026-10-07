"""Reviewable configuration for the exact built-in work routine."""
from PyQt6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QSpinBox, QVBoxLayout, QPushButton, QFileDialog, QListWidget, QScrollArea, QWidget
from desktop.core.work_routine import WorkRoutine, WorkRoutineStore
from mica_shared.quick_commands import APP_NAMES
from desktop.ui_theme import C


class WorkRoutineDialog(QDialog):
    def __init__(self, parent=None, *, store=None, draft=None, documents=None):
        super().__init__(parent)
        self.store = store or WorkRoutineStore()
        self.setWindowTitle("Benannte Abläufe")
        self.resize(450, 580)
        self.setStyleSheet(f"QDialog,QScrollArea,QWidget {{background:{C.PANEL};color:{C.TEXT};}} QLabel,QCheckBox {{color:{C.TEXT};}} QPushButton,QSpinBox,QComboBox,QListWidget {{padding:6px; color:{C.TEXT};background:{C.PANEL2};border:1px solid {C.BORDER};border-radius:6px;}}")
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        explanation = QLabel("Arbeitsmodus starten öffnet die ausgewählten Programme, startet danach einen Fokus-Timer und aktiviert die Mica-Ruhezeit. Jeder Programmstart benötigt weiterhin die bestehenden Freigaben. Bei einem Fehler hält der Ablauf an.")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.name = QComboBox()
        self.name.setEditable(True)
        try:
            names = list(self.store.all())
        except (ValueError, TypeError, OSError):
            names = []
        self.name.addItems(list(dict.fromkeys(['work', *names, 'schulmodus', 'programmieren', 'feierabend'])))
        self.name.setToolTip('Namen auswählen oder einen neuen Namen eingeben. Start: „Starte Ablauf Name“. work ist der bisherige Arbeitsmodus.')
        layout.addWidget(self.name)
        current = self.store.load()
        self.enabled = QCheckBox("Diesen Ablauf aktivieren")
        self.enabled.setChecked(current.enabled)
        layout.addWidget(self.enabled)
        # One label per actual application, so aliases cannot open it twice.
        seen, self.apps = set(), {}
        for label, canonical in APP_NAMES.items():
            identity = "vscode" if canonical == "visual studio code" else canonical
            if identity in seen:
                continue
            seen.add(identity)
            checkbox = QCheckBox(label.capitalize())
            checkbox.setChecked(any(APP_NAMES[item] == canonical for item in current.apps))
            self.apps[label] = checkbox
            layout.addWidget(checkbox)
        form = QFormLayout()
        self.focus, self.quiet, self.pause = QSpinBox(), QSpinBox(), QSpinBox()
        for field in (self.focus, self.quiet):
            field.setRange(1, 1440)
            field.setSuffix(" Minuten")
        self.focus.setValue(current.focus_minutes)
        self.quiet.setValue(current.quiet_minutes)
        self.pause.setRange(0, 1440)
        self.pause.setSuffix(' Minuten')
        self.pause.setValue(current.pause_minutes)
        form.addRow("Fokus-Timer", self.focus)
        form.addRow("Mica-Ruhezeit", self.quiet)
        form.addRow('Pause nach Fokus (0 = keine)', self.pause)
        layout.addLayout(form)
        self.documents = QListWidget()
        self.documents.addItems(current.documents)
        self.documents.setMaximumHeight(90)
        layout.addWidget(QLabel('Dokumente für diesen Ablauf (werden beim Start neu gelesen)'))
        layout.addWidget(self.documents)
        add_document = QPushButton('Dateien auswählen')
        add_document.clicked.connect(self.add_documents)
        layout.addWidget(add_document)
        remove_document = QPushButton('Markierte Datei aus Ablauf entfernen')
        remove_document.clicked.connect(lambda: self.documents.takeItem(self.documents.currentRow()))
        layout.addWidget(remove_document)
        note = QLabel("Während der Ruhezeit hört Mica nicht auf das Aktivierungswort und zeigt keine Timer-Popups. Timerabläufe bleiben im Verlauf sichtbar. Text und die Sprechtaste funktionieren weiter. Die Ruhezeit endet automatisch oder mit „Ruhemodus beenden“.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        delete = QPushButton('Ausgewählten Ablauf löschen')
        delete.clicked.connect(self.delete)
        layout.addWidget(delete)
        self.name.currentTextChanged.connect(self.load_name)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Speichern")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        if draft:
            self.name.setCurrentText(draft['name'])
            self.enabled.setChecked(True)
            self.focus.setValue(draft['focus_minutes'])
            self.quiet.setValue(draft['focus_minutes'])
            self.pause.setValue(draft['pause_minutes'])
            import re
            for label, checkbox in self.apps.items():
                if re.search(r'\b' + re.escape(label) + r' öffnen\b', draft['request'], re.I):
                    checkbox.setChecked(True)
            if draft['selected_documents']:
                self.documents.clear()
                self.documents.addItems([doc['local_path'] for doc in documents or [] if doc.get('local_path')])
            self.status.setText('Deine Anfrage: ' + draft['request'] + '\nBitte alle Schritte prüfen. Programme kannst du unten auswählen. Speichern startet den Ablauf noch nicht.' + ('\nOhne genannte Pausendauer sind 5 Minuten vorgeschlagen.' if draft['pause_minutes'] == 5 else ''))

    def save(self):
        try:
            self.store.save(WorkRoutine(self.enabled.isChecked(), [label for label, checkbox in self.apps.items() if checkbox.isChecked()], self.focus.value(), self.quiet.value(),
                [self.documents.item(index).text() for index in range(self.documents.count())], self.pause.value()), self.name.currentText())
        except (ValueError, OSError) as error:
            self.status.setText(str(error))
            return
        self.accept()

    def load_name(self, name):
        current = self.store.load(name)
        self.enabled.setChecked(current.enabled)
        for label, checkbox in self.apps.items():
            checkbox.setChecked(any(APP_NAMES[item] == APP_NAMES[label] for item in current.apps))
        self.focus.setValue(current.focus_minutes)
        self.quiet.setValue(current.quiet_minutes)
        self.pause.setValue(current.pause_minutes)
        self.documents.clear()
        self.documents.addItems(current.documents)

    def add_documents(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Dokumente für Ablauf auswählen', '', 'Dokumente (*.txt *.md *.pdf *.csv *.log *.json *.py *.yaml *.yml *.png *.jpg *.jpeg *.webp *.bmp)')
        existing = {self.documents.item(index).text() for index in range(self.documents.count())}
        for path in paths:
            if path not in existing:
                if len(existing) >= 8:
                    self.status.setText('Höchstens acht Dateien pro Ablauf.')
                    break
                self.documents.addItem(path)
                existing.add(path)

    def delete(self):
        from PyQt6.QtWidgets import QMessageBox
        if QMessageBox.question(self, 'Ablauf löschen', f'„{self.name.currentText()}“ löschen?') != QMessageBox.StandardButton.Yes:
            return
        try:
            self.store.delete(self.name.currentText())
            self.load_name(self.name.currentText())
            self.status.setText('Ablauf gelöscht.')
        except (ValueError, OSError, TypeError) as error:
            self.status.setText(str(error))
