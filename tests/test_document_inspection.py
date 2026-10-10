import os
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication
from desktop.core.document_inspection import document_statistics, search_documents, search_text, statistics_text
from desktop.document_inspection_dialog import DocumentInspectionDialog
from desktop.core.native_commands import NativeCommands
from mica_shared.quick_commands import parse_quick_command


def test_statistics_count_selected_version_and_report_limits():
    rows = document_statistics([{'title': 'Aufsatz', 'body': 'E-Mail für Schüler 2026.\n\nZweiter Absatz.',
                                  'truncated': True, 'changed': True}])
    assert rows[0]['words'] == 6
    assert rows[0]['paragraphs'] == 2
    assert rows[0]['characters_without_spaces'] == len('E-MailfürSchüler2026.ZweiterAbsatz.')
    text = statistics_text([{'title': 'Test', 'body': 'Wort', 'truncated': True, 'changed': True}])
    assert 'Ausschnitt' in text and 'zuvor' in text
    assert '0 Wörter' in statistics_text([{'title': 'Leer', 'body': ''}])
    assert 'auswählen' in statistics_text([])


def test_literal_search_is_bounded_unicode_safe_and_never_executes_regex():
    docs = [{'title': 'A', 'body': 'Erste Zeile\nÄpfel [x].\nÄPFEL'},
            {'title': 'B', 'body': 'Noch Äpfel'}]
    result = search_documents(docs, 'äpfel', limit=2)
    assert [hit['line'] for hit in result['hits']] == [2, 3]
    assert result['more']
    assert len(search_documents(docs, '[x]')['hits']) == 1
    assert search_documents(docs, '.*')['hits'] == []
    assert 'Keine Treffer' in search_text(docs, 'Unbekannt')
    with pytest.raises(ValueError):
        search_documents(docs, ' ')
    with pytest.raises(ValueError):
        statistics_text([{'title': 'too big', 'body': 'x' * 32001}])


def test_dialog_uses_plain_text_and_needs_no_external_client():
    app = QApplication.instance() or QApplication([])
    dialog = DocumentInspectionDialog(documents=[{'title': 'Ausgewählt', 'body': '<b>Treffer</b>'}])
    assert 'Ausgewählt' in dialog.report.toPlainText()
    dialog.query.setText('Treffer')
    dialog.search()
    app.processEvents()
    assert '<b>Treffer</b>' in dialog.report.toPlainText()
    dialog.statistics()
    assert 'Zeichen' in dialog.report.toPlainText()
    dialog.close()


def test_overlay_inspection_includes_only_checked_documents():
    from desktop.attachment_overlay import AttachmentOverlay
    app = QApplication.instance() or QApplication([])
    overlay = AttachmentOverlay()
    overlay._watch_timer.stop()
    overlay.replace_documents([{'id': 'a', 'title': 'Ja', 'body': 'one', 'source': 'text'},
                               {'id': 'b', 'title': 'Nein', 'body': 'private', 'source': 'text'}])
    overlay._selected = {'a'}
    with patch('desktop.document_inspection_dialog.DocumentInspectionDialog') as dialog:
        overlay.inspect_button.click()
    assert [doc['title'] for doc in dialog.call_args.args[1]] == ['Ja']
    dialog.return_value.exec.assert_called_once()
    overlay.close()
    app.processEvents()


def test_canonical_offline_word_count_without_storage_never_contacts_core():
    from desktop.local_main import LocalMica
    mica = LocalMica.__new__(LocalMica)
    mica._request_lock = threading.RLock()
    mica._restoring = False
    mica._offline_start = mica._offline_workspace = True
    overlay = SimpleNamespace(checkpoint_documents=Mock(return_value=[{'title': 'Aufsatz', 'body': 'eins zwei drei'}]))
    mica.ui = SimpleNamespace(_win=SimpleNamespace(_attachment_overlay=overlay),
                              remember_conversations=False, muted=True, write_log=Mock(),
                              set_state=Mock(), show_content=Mock())
    mica.client = Mock()
    mica.native_commands = NativeCommands(mica.client, Mock())
    mica.native_commands.document_info_handler = mica._document_info_requested
    mica.handle_text('Mica, Wörter zählen')
    assert '3 Wörter' in mica.ui.show_content.call_args.args[1]
    mica.client.turn.assert_not_called()
    assert parse_quick_command('Wörter zählen und löschen') is None
