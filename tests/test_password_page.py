import os
import string
from unittest.mock import Mock
import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication, QLineEdit
from desktop.password_page import PasswordPage, random_password


def test_character_classes_length_and_invalid_inputs():
    for symbols in (False, True):
        value = random_password(20, symbols)
        assert len(value) == 20
        assert any(c in string.ascii_lowercase for c in value)
        assert any(c in string.ascii_uppercase for c in value)
        assert any(c in string.digits for c in value)
        assert any(c in '!@#$%^&*+-_=' for c in value) == symbols
    for length in (True, 0, 129, '20'):
        with pytest.raises(ValueError):
            random_password(length)


def test_ui_secret_is_not_copied_automatically_and_other_clipboard_content_survives():
    app = QApplication.instance() or QApplication([])
    clipboard = Mock()
    clipboard.text.return_value = 'Unabhängiger Text'
    page = PasswordPage(clipboard=clipboard)
    page.generate_button.click()
    assert page.output.echoMode() == QLineEdit.EchoMode.Password
    assert page.timer.isActive()
    clipboard.setText.assert_not_called()
    page.copy_button.click()
    secret = page._value
    clipboard.setText.assert_called_once_with(secret)
    page.clear()
    clipboard.clear.assert_not_called()
    assert not page.output.text() and not page._value
    page.generate()
    page.copy()
    clipboard.text.return_value = page._value
    page.timer.timeout.emit()
    clipboard.clear.assert_called_once()
    assert not page.timer.isActive() and not page.copy_button.isEnabled()
    page.close()
    app.processEvents()
