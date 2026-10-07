"""Render the actual desktop controls and feature dialogs without live services."""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import Mock, patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PyQt6.QtWidgets import QApplication
from desktop.ui import MainWindow
from desktop.work_routine_dialog import WorkRoutineDialog
from desktop.workspace_dialog import WorkspaceDialog
from desktop.text_selection_dialog import TextSelectionDialog
from desktop.preference_dialog import PreferenceDialog
from desktop.core.work_routine import WorkRoutine, WorkRoutineStore
from desktop.core.workspace import WorkspaceStore
from desktop.core.attachments import extract_attachment

app = QApplication([])
directory = Path(__file__).parent
with tempfile.TemporaryDirectory(prefix='mica-render-check-') as temporary:
    data = Path(temporary)
    note = data / 'Docker.md'
    note.write_text('Compose-Konfiguration vergleichen.', encoding='utf-8')
    doc = extract_attachment(str(note))
    with patch.object(MainWindow, '_check_config', return_value=True):
        window = MainWindow('')
    window.show()
    app.processEvents()
    window.grab().save(str(directory / 'desktop-normal.png'))
    window.resize(960, 680)
    app.processEvents()
    window.grab().save(str(directory / 'desktop-minimum.png'))
    buttons = [window._attachments_button, window._routine_button, window._screen_help_button,
               window._workspace_button, window._selection_button]
    dimensions = {'width': window.width(), 'height': window.height(), 'input_width': window._input.width(),
                  'buttons_visible': all(button.isVisible() for button in buttons),
                  'buttons_fit_parent': all(button.geometry().right() <= button.parentWidget().width() for button in buttons)}
    dimensions['button_labels_fit'] = all(button.width() >= button.fontMetrics().horizontalAdvance(button.text()) + 14 for button in buttons)
    store = WorkRoutineStore(data / 'routine.json')
    store.save(WorkRoutine(True, ['firefox', 'editor'], 30, 20, [str(note)]), 'schulmodus')
    routine = WorkRoutineDialog(window, store=store)
    routine.name.setCurrentText('schulmodus')
    routine.show()
    app.processEvents()
    routine.grab().save(str(directory / 'routine-top.png'))
    from PyQt6.QtWidgets import QScrollArea
    routine.findChild(QScrollArea).verticalScrollBar().setValue(10000)
    app.processEvents()
    routine.grab().save(str(directory / 'routine-documents.png'))
    routine.close()
    checkpoint = WorkspaceStore(data / 'workspace.json')
    checkpoint.save([doc], None, 'Docker-Konfiguration vergleichen')
    workspace = WorkspaceDialog(window, Mock(), [doc], store=checkpoint, prefer_load=True)
    workspace.show()
    app.processEvents()
    workspace.grab().save(str(directory / 'workspace.png'))
    workspace.close()
    preview = TextSelectionDialog(window, 'Docker Compose startet mehrere Dienste gemeinsam.', Mock())
    preview.result.setPlainText('Docker Compose startet die konfigurierten Container eines Projekts gemeinsam.')
    preview.copy.setEnabled(True)
    preview.show()
    app.processEvents()
    preview.grab().save(str(directory / 'text-preview.png'))
    preview.close()
    preference = PreferenceDialog(window, {'key': 'Antwortlänge', 'value': 'kürzer', 'scope': 'technical'}, Mock())
    preference.show()
    app.processEvents()
    preference.grab().save(str(directory / 'preference.png'))
    preference.close()
    window.close()
    window.deleteLater()
    app.processEvents()
    (directory / 'render-check.json').write_text(json.dumps(dimensions, indent=2))
    print(json.dumps(dimensions))
    assert dimensions['buttons_visible'] and dimensions['buttons_fit_parent'] and dimensions['button_labels_fit'] and dimensions['input_width'] >= 90
