"""Behavioral checks for named projects, evidence, comparison and closed-app timers."""
import json
import time
from unittest.mock import Mock
from xml.etree import ElementTree as ET
import pytest
from fastapi.testclient import TestClient
from backend.services.api.app import create_app
from backend.services.common.document_sources import source_spans, resolve_citations, context_sources
from desktop.core.attachments import extract_attachment
from desktop.core.document_changes import compare_document
from desktop.core.local_state import FileLease
from desktop.core.native_commands import LocalTimers, NativeCommands
from desktop.core.timer_delivery import WindowsTimerDelivery, claim_delivery, deliver
from desktop.core.workspace import WorkspaceStore, ProjectWorkspaceStore
from mica_shared.quick_commands import parse_quick_command

SESSION = 'a' * 32


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv('MICA_API_TOKEN', 'project-test-token-xxxxxxxxxxxxxxxxx')
    monkeypatch.setenv('MICA_APPROVAL_SECRET', 'project-test-secret')
    monkeypatch.setenv('MICA_PHASE3_ENABLED', '1')
    monkeypatch.setenv('MICA_LAYA_ENABLED', '0')
    monkeypatch.setenv('MICA_HINDSIGHT_ENABLED', '0')
    app = create_app(data_dir=tmp_path)
    app.state.runtime._local_completion = Mock(return_value='Der Port ist 8443. [Q1]')
    with TestClient(app, headers={'X-Mica-API-Token': 'project-test-token-xxxxxxxxxxxxxxxxx'}) as client:
        yield client, app.state.runtime


def test_named_project_roundtrip_retains_three_real_baselines_and_legacy(tmp_path):
    file = tmp_path / 'config.md'
    file.write_text('Port: 8000', encoding='utf-8')
    document = extract_attachment(str(file))
    legacy = tmp_path / 'workspace.json'
    WorkspaceStore(legacy).save([document], SESSION, 'Alt', 'Aufgabe')
    store = ProjectWorkspaceStore(tmp_path / 'projects.json', legacy)
    assert store.names() == ['standard']
    for index in range(4):
        store.save([document], SESSION, f'Schritt {index}', 'Aufgabe', name='MICA')
    store.save([], None, 'Lernen', name='Schule')
    reopened = ProjectWorkspaceStore(store.path, legacy)
    assert reopened.names() == ['mica', 'schule', 'standard']
    assert len(reopened.all()['mica']) == 3
    assert reopened.load('mica')['next_step'] == 'Schritt 3'
    assert reopened.load('mica')['documents'][0]['loaded_at'] == document['loaded_at']
    reopened.forget('mica')
    assert reopened.names() == ['schule', 'standard']
    assert legacy.exists()
    reopened.forget('standard')
    assert reopened.names() == ['schule']  # Legacy data must not reappear.


def test_project_validation_and_simultaneous_write_preserve_state(tmp_path):
    store = ProjectWorkspaceStore(tmp_path / 'projects.json', tmp_path / 'absent')
    store.save([], None, 'Erster Schritt', name='mica')
    before = store.path.read_bytes()
    with pytest.raises(ValueError):
        store.save([], None, 'oops', name='../secrets')
    with FileLease(str(store.path) + '.lock'):
        with pytest.raises(ValueError, match='Projektstände'):
            store.save([], None, 'oops', name='mica')
    assert store.path.read_bytes() == before
    store.path.write_text('{broken', encoding='utf-8')
    with pytest.raises(ValueError):
        store.save([], None, 'oops', name='mica')
    assert store.path.read_text() == '{broken'


@pytest.mark.parametrize('message,kind', [('Wechsle zu MICA', 'project_switch'),
    ('Was weißt du über Projekt MICA?', 'memory_project'),
    ('Was hat sich seit gestern geändert?', 'document_changes'),
    ('Erklär mir diese Fehlermeldung', 'window_help'), ('Wo ändere ich diese Einstellung?', 'window_help')])
def test_new_commands_use_same_exact_grammar_for_api_and_desktop(api, message, kind):
    client, runtime = api
    result = client.post('/v1/turns', json={'session_id': SESSION, 'message': message, 'native_commands': True}).json()
    assert result['command'] == parse_quick_command(message)
    assert result['command']['kind'] == kind
    runtime._local_completion.assert_not_called()
    commands = NativeCommands(Mock(), Mock())
    handler = Mock(return_value='Fenster geöffnet')
    setattr(commands, {'project_switch': 'project_handler', 'memory_project': 'memory_handler',
        'document_changes': 'changes_handler', 'window_help': 'window_help_handler'}[kind], handler)
    assert commands.execute(result['command'], message) == 'Fenster geöffnet'
    assert handler.call_count == 1
    assert parse_quick_command(message + '; shutdown') is None
    assert 'nicht ausgeführt' in commands.execute({**result['command'], 'extra': 'execute'}, message)


def test_api_sources_resolve_exact_file_text_and_reject_model_invented_locations(api):
    client, runtime = api
    document = {'id': 'b' * 32, 'title': 'Caddy.md', 'source': 'text', 'body': 'TLS lokal\nPort: 8443\nBackend: 8000'}
    assert client.post('/v1/dialog/context', json={'session_id': SESSION, 'documents': [document]}).status_code == 200
    response = client.post('/v1/turns', json={'session_id': SESSION, 'message': 'Welcher Port ist für TLS konfiguriert?', 'remember': False}).json()
    citation = response['citations'][0]
    assert citation['quote'] == document['body'][citation['start']:citation['end']]
    assert citation['title'] == 'Caddy.md' and citation['line_start'] == 1 and citation['line_end'] == 3
    assert 'Dokumentquellen:' in response['reply']
    assert 'Port: 8443' in response['reply']
    assert 'Dokumentquellen:' not in response['spoken_reply']
    assert not runtime.brain.documents()
    runtime._local_completion.return_value = 'Die Antwort steht auf Seite 99. [Q99]'
    response = client.post('/v1/turns', json={'session_id': SESSION, 'message': 'Welcher Port?', 'remember': False}).json()
    assert response['invalid_citations'] is True and response['citations'] == []
    assert '[Q99]' not in response['reply'] and 'Quelle nicht belegt' in response['reply']


def test_cloud_without_private_opt_in_does_not_expose_passages_or_citations(api, monkeypatch):
    client, runtime = api
    monkeypatch.setattr(runtime, 'configured_cloud_provider', lambda: 'test-provider')
    monkeypatch.setattr(runtime, 'cloud_private_context_allowed', lambda: False)
    client.post('/v1/dialog/context', json={'session_id': SESSION, 'documents': [
        {'id': 'b' * 32, 'title': 'Privat', 'source': 'text', 'body': 'GEHEIM-8443'}]})
    runtime._local_completion.return_value = 'Allgemeine Antwort.'
    result = client.post('/v1/turns', json={'session_id': SESSION, 'message': 'Was ist TLS?', 'remember': False}).json()
    assert result['citations'] == []
    assert 'GEHEIM' not in runtime._local_completion.call_args.args[0]
    assert 'Privat' not in result['reply']


def test_pdf_and_duplicate_names_have_distinct_exact_citations():
    docs = [{'id': str(index) * 32, 'title': 'Dokument.pdf', 'source': 'pdf',
        'body': f'Seite 1:\nZielport: {port}'} for index, port in [(1, 8443), (2, 443)]]
    sources = source_spans(docs, 'Zielport')
    reply, citations, invalid = resolve_citations('Die Quellen widersprechen sich. [Q1] [Q2]', sources)
    assert len(citations) == 2 and not invalid
    assert citations[0]['document_id'] != citations[1]['document_id']
    assert all(item['page'] == 1 for item in citations)
    assert '8443' in reply and '443' in reply
    assert context_sources('prefix\n{"document_sources":[{"marker":"Q1"}]}') == []


def test_uncited_response_still_shows_passages_without_claiming_model_support():
    sources = source_spans([{'id': SESSION, 'title': 'Notiz.md', 'source': 'text', 'body': 'Port: 8443'}], 'Port')
    reply, citations, invalid = resolve_citations('Allgemeine Erklärung.', sources)
    assert citations == [] and not invalid
    assert 'vom Modell nicht zugeordnet' in reply
    assert 'Notiz.md' in reply and 'Port: 8443' in reply


def test_source_appendix_is_not_persisted_as_conversation(api):
    client, runtime = api
    client.post('/v1/dialog/context', json={'session_id': SESSION, 'documents': [
        {'id': 'b' * 32, 'title': 'Notiz.md', 'source': 'text', 'body': 'Port: 8443\nPRIVATE_PASSAGE_725'}]})
    response = client.post('/v1/turns', json={'session_id': SESSION, 'message': 'Welcher Port?', 'remember': True}).json()
    assert 'PRIVATE_PASSAGE_725' in response['reply']
    assert 'PRIVATE_PASSAGE_725' not in '\n'.join(doc['body'] for doc in runtime.brain.documents())


def test_pdf_cross_page_passage_reports_actual_page_range():
    sources = source_spans([{'id': SESSION, 'title': 'Notiz.pdf', 'source': 'pdf',
        'body': 'Seite 1:\nAlt\n\nSeite 2:\nNeu'}], 'Neu')
    reply, citations, _ = resolve_citations('Vergleich [Q1]', sources)
    assert citations[0]['page'] == 1 and citations[0]['page_end'] == 2
    assert 'PDF-Seite 1–2' in reply


def test_diff_reads_current_file_without_mutating_saved_selection(tmp_path):
    file = tmp_path / 'config.md'
    file.write_text('Port: 8000\nTLS: nein\n', encoding='utf-8')
    document = extract_attachment(str(file))
    original_body = document['body']
    file.write_text('Port: 8443\nTLS: ja\n', encoding='utf-8')
    diff = compare_document(document, baseline_at='2026-10-06T12:00:00+02:00')
    assert diff['changed'] and '-Port: 8000' in diff['diff'] and '+Port: 8443' in diff['diff']
    assert diff['baseline_at'] == '2026-10-06T12:00:00+02:00'
    assert document['body'] == original_body
    file.unlink()
    with pytest.raises(FileNotFoundError):
        compare_document(document)


def test_closed_timer_claim_is_exclusive_and_cancelled_or_stale_task_cannot_notify(tmp_path):
    file = tmp_path / 'timers.json'
    timer = LocalTimers(Mock(), path=file, wall_clock=lambda: 1000)
    timer.start(60)
    identifier, item = next(iter(timer._items.items()))
    with pytest.raises(ValueError, match='anderen Mica'):
        claim_delivery(file, identifier, 1060, now=lambda: 2000)
    timer.shutdown()
    assert not claim_delivery(file, identifier, 1061, now=lambda: 2000)
    assert not claim_delivery(file, identifier, 1060, now=lambda: 1000)
    notify = Mock(return_value=True)
    assert deliver(file, identifier, 1060, now=lambda: 2000, notify=notify)
    assert not deliver(file, identifier, 1060, now=lambda: 2000, notify=notify)
    notify.assert_called_once()
    assert json.loads(file.read_text())['timers'] == []


def test_timer_schedule_failure_keeps_old_correction_and_cancellation_is_authoritative(tmp_path):
    scheduler = Mock()
    file = tmp_path / 'timers.json'
    timer = LocalTimers(Mock(), path=file, delivery=scheduler)
    timer.start(600)
    before = file.read_bytes()
    scheduler.schedule.side_effect = OSError('scheduler unavailable')
    with pytest.raises(OSError):
        timer.correct_latest(700, 600)
    assert file.read_bytes() == before
    assert next(iter(timer._items.values()))['seconds'] == 600
    identifier, item = next(iter(timer._items.items()))
    timer.cancel_latest()
    timer.shutdown()
    assert not claim_delivery(file, identifier, item['deadline'], now=lambda: item['deadline'] + 1)


def test_scheduler_uses_escaped_paths_and_never_fires_before_fractional_deadline(tmp_path):
    captured = []
    def run(args, **kwargs):
        captured.append(ET.parse(args[args.index('/XML') + 1]))
        return Mock(returncode=0)
    scheduler = WindowsTimerDelivery(tmp_path / 'a & b' / 'timers.json', run=run)
    scheduler.schedule('c' * 32, 2000.75)
    root = captured[0].getroot()
    ns = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}
    assert root.find('.//t:StartBoundary', ns).text.endswith('00:33:21+00:00')
    args = root.find('.//t:Arguments', ns).text
    assert 'a & b' in args and '--id ' + 'c' * 32 in args
    assert root.find('.//t:LogonType', ns).text == 'InteractiveToken'


@pytest.fixture
def qt(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def until(qt, predicate):
    deadline = time.monotonic() + 4
    while not predicate() and time.monotonic() < deadline:
        qt.processEvents()
        time.sleep(.01)
    assert predicate()


def test_named_workspace_ui_switch_and_save_new_name(qt, tmp_path):
    from desktop.workspace_dialog import WorkspaceDialog
    store = ProjectWorkspaceStore(tmp_path / 'projects.json', tmp_path / 'absent')
    store.save([], None, 'Docker prüfen', name='mica')
    store.save([], None, 'Mathe lernen', name='schule')
    def operation(action, payload, selected_store):
        return selected_store.save(payload['documents'], None, payload['next_step'], name=payload['project'])
    dialog = WorkspaceDialog(None, operation, [], store=store, prefer_load=True, project='mica')
    assert dialog.step.toPlainText() == 'Docker prüfen'
    dialog.name.setCurrentText('schule')
    assert dialog.step.toPlainText() == 'Mathe lernen'
    dialog.name.setCurrentText('homelab')
    dialog.step.setPlainText('Backup prüfen')
    dialog.run('save')
    until(qt, lambda: dialog.name.isEnabled())
    assert store.load('homelab')['next_step'] == 'Backup prüfen'
    assert dialog.name.findText('homelab') >= 0
    dialog.close()


def test_project_memory_command_opens_existing_provenance_editor(qt):
    from types import SimpleNamespace
    from desktop.ui import MainWindow
    from desktop.control_center import BackendMemoryPage
    page = BackendMemoryPage()
    page.certainty_filter.setCurrentIndex(1)
    window = SimpleNamespace(_backend_memory_page=page, _activate_navigation=Mock())
    MainWindow._open_project_memory(window, 'mica')
    assert page.search.text() == 'mica'
    assert page.certainty_filter.currentIndex() == 0
    window._activate_navigation.assert_called_once_with('memory')
    # These remain the actual existing controls with guarded update/delete.
    assert page.correct_button is not None and page.forget_button is not None
    page._auth_timer.stop()
    page.close()


def test_project_load_uses_canonical_ui_selection_and_next_step(qt, tmp_path):
    from PyQt6.QtWidgets import QWidget, QLineEdit
    from desktop.workspace_dialog import WorkspaceDialog
    from desktop.attachment_overlay import AttachmentOverlay
    store = ProjectWorkspaceStore(tmp_path / 'projects.json', tmp_path / 'absent')
    doc = {'id': SESSION, 'title': 'Projekt.md', 'body': 'MICA Kontext', 'source': 'text'}
    store.save([doc], None, 'HTTPS prüfen', name='mica')
    parent = QWidget()
    parent._attachment_overlay = AttachmentOverlay()
    parent._open_attachments = Mock()
    parent._input = QLineEdit()
    dialog = WorkspaceDialog(parent, lambda action, payload, selected_store: selected_store.validate(payload),
        [], store=store, prefer_load=True, project='mica')
    dialog.run('load')
    until(qt, lambda: parent._input.text() == 'HTTPS prüfen')
    assert parent._attachment_overlay.snapshot() == [doc]
    parent._open_attachments.assert_called_once()
    parent._attachment_overlay.close()
    parent.close()


def test_comparison_ui_requires_real_baseline_and_explicit_explanation(qt, tmp_path):
    from desktop.document_changes_dialog import DocumentChangesDialog
    file = tmp_path / 'note.md'
    file.write_text('alt\n', encoding='utf-8')
    doc = extract_attachment(str(file))
    file.write_text('neu\n', encoding='utf-8')
    transform = Mock(return_value={'reply': 'Der Text wurde geändert.'})
    store = ProjectWorkspaceStore(tmp_path / 'projects.json', tmp_path / 'absent')
    dialog = DocumentChangesDialog(None, [doc], transform, store=store)
    transform.assert_not_called()
    dialog.run_compare()
    until(qt, lambda: dialog.compare.isEnabled())
    assert '+neu' in dialog.result.toPlainText()
    transform.assert_not_called()
    dialog.run_explain()
    until(qt, lambda: dialog.compare.isEnabled())
    assert 'Der Text wurde geändert.' in dialog.result.toPlainText()
    assert len(transform.call_args.args[0]) <= 16000
    dialog.close()


def test_window_controls_preview_and_ocr_failure_can_use_only_reviewed_labels(qt, monkeypatch):
    from PyQt6.QtGui import QImage
    from desktop.screen_help_dialog import ScreenHelpDialog
    from desktop.attachment_overlay import AttachmentOverlay
    from desktop.core.window_controls import read_window_controls
    target = {'hwnd': 123, 'pid': 99, 'title': 'Einstellungen'}
    run = Mock(return_value=Mock(returncode=0, stdout=json.dumps({'status': 'read', 'controls': [
        {'type': 'Button', 'name': 'Speichern', 'enabled': True}]})))
    controls = read_window_controls(target, run=run)
    assert controls['text'] == 'Button: Speichern'
    image = QImage(100, 100, QImage.Format.Format_RGB32)
    image.fill(0)
    dialog = ScreenHelpDialog({**target, 'controls': controls}, image)
    assert 'Speichern' in dialog.controls.toPlainText() and dialog.use_controls.isChecked()
    dialog.close()
    overlay = AttachmentOverlay()
    monkeypatch.setattr('desktop.attachment_overlay.extract_attachment', Mock(side_effect=ValueError('no OCR text')))
    overlay.add_capture(image, target['title'], controls['text'])
    until(qt, lambda: not overlay._loading)
    assert 'Button: Speichern' in overlay.snapshot()[0]['body']
    assert 'local_path' not in overlay.snapshot()[0]
    overlay.close()
