import os
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication
from desktop.cognition_panel import CognitionPage

APP = QApplication.instance() or QApplication([])


def test_panel_applies_to_active_chat_and_renders_observations():
    identifier = ['a' * 32]
    page = CognitionPage(lambda: identifier[0])
    client = Mock()
    with patch.object(page, '_run', side_effect=lambda kind, action: action(client)):
        page.profile.setCurrentIndex(0)
        page.apply()
    client.cognitive_settings.assert_called_once_with(True, 'low_vram', 'a' * 32)
    page._received('cognition', {'enabled': True, 'profile': 'low_vram', 'stance': 'careful',
                               'caution': .6, 'focus_terms': ['mikrofon'], 'turns': 1,
                               'observations': [{'kind': 'model_error', 'reply_characters': 0}]}, '')
    assert 'Besonders sorgfältig' in page.details.toPlainText()
    assert 'Modellanfrage fehlgeschlagen' in page.details.toPlainText()
    identifier[0] = 'b' * 32
    page._received('cognition', {'enabled': True, 'focus_terms': ['altes Geheimnis']}, '')
    assert not page.details.toPlainText()
    assert 'gewechselt' in page.status.text()
    with patch.object(page, '_run', side_effect=lambda kind, action: action(client)):
        page.reset()
    client.reset_cognition.assert_called_once_with('b' * 32)
    page.close()


def test_panel_failure_clears_stale_state():
    page = CognitionPage(lambda: 'a' * 32)
    page._request_session = 'a' * 32
    page.details.setPlainText('Alter Zustand')
    page._received('cognition', None, 'Core nicht erreichbar')
    assert not page.details.toPlainText()
    assert 'Core nicht erreichbar' in page.status.text()
    assert page.refresh_button.isEnabled()
    page.close()
