"""Explicit window snapshot preview before its OCR text enters a conversation."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout
from desktop.ui_theme import C


class ScreenHelpDialog(QDialog):
    def __init__(self, target, image, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fensterhilfe – Aufnahme prüfen")
        self.resize(760, 560)
        self.setStyleSheet(f"QDialog {{background:{C.PANEL};}} QLabel {{color:{C.TEXT};}} QPushButton {{padding:8px;color:{C.TEXT};background:{C.PANEL2};border:1px solid {C.BORDER};border-radius:6px;}}")
        layout = QVBoxLayout(self)
        title = QLabel("Erfasstes Fenster: " + target["title"])
        title.setWordWrap(True)
        layout.addWidget(title)
        preview = QLabel()
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setPixmap(QPixmap.fromImage(image).scaled(700, 380, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(preview)
        note = QLabel("Als Kontext verwenden liest den Text lokal aus dieser einzelnen Aufnahme. Nur der erkannte Text gelangt ins Gespräch. Prüfe die Vorschau auf private Inhalte. Die Frage kannst du anschließend bearbeiten und senden.")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Als Kontext verwenden")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
