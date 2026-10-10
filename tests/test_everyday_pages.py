"""Integrated navigation, privacy callback and transient secret lifecycle."""
import os
from unittest.mock import Mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication
from desktop.control_center import ControlCenter
from desktop.core.checklists import ChecklistStore
from desktop.core.quick_notes import QuickNotesStore


def test_local_pages_follow_dynamic_privacy_and_clear_password_when_leaving(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    store = ChecklistStore(tmp_path / 'lists.json')
    notes_store = QuickNotesStore(tmp_path / 'notes.json')
    monkeypatch.setattr('desktop.checklists_page.ChecklistStore', lambda: store)
    monkeypatch.setattr('desktop.quick_notes_page.QuickNotesStore', lambda: notes_store)
    clipboard = Mock()
    clipboard.text.return_value = ''
    monkeypatch.setattr('desktop.password_page.QApplication.clipboard', lambda: clipboard)
    privacy = {'save': False}
    client_factory = Mock(side_effect=AssertionError('Local pages must not contact backend'))
    page = ControlCenter(can_save=lambda: privacy['save'], client_factory=client_factory)
    page.timer.stop()
    page.resize(1000, 760)
    page.show()
    app.processEvents()
    try:
        lists = page.checklists_page
        page.tabs.setCurrentWidget(lists)
        lists.name.setText('Packliste')
        lists.create_button.click()
        assert not store.path.exists() and 'Speicherung' in lists.status.text()
        privacy['save'] = True
        lists.create_button.click()
        assert store.read()['lists'][0]['name'] == 'Packliste'
        privacy['save'] = False
        lists.entry.setText('Reisepass')
        lists.add_button.click()
        assert store.read()['lists'][0]['items'] == []

        notes = page.quick_notes_page
        page.tabs.setCurrentWidget(notes)
        notes.title.setText('Idee')
        notes.body.setPlainText('Lokal behalten')
        notes.save_button.click()
        assert not notes_store.path.exists() and notes.dirty()
        page._refresh_visible()
        client_factory.assert_not_called()
        privacy['save'] = True
        notes.save_button.click()
        assert notes_store.read()['notes'][0]['body'] == 'Lokal behalten'

        password = page.password_page
        page.tabs.setCurrentWidget(password)
        app.processEvents()
        password.generate_button.click()
        assert password.output.text() and password.timer.isActive()
        clipboard.setText.assert_not_called()
        password.copy_button.click()
        clipboard.text.return_value = password._value
        page.tabs.setCurrentWidget(page.folder_analysis_page)
        app.processEvents()
        assert not password.output.text() and not password.timer.isActive()
        clipboard.clear.assert_called_once()
        assert page.folder_analysis_page.isVisible()
        page._refresh_visible()
        client_factory.assert_not_called()
    finally:
        page.close()
        page.deleteLater()
        app.processEvents()
