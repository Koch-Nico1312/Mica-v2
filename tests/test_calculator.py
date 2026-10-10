import threading
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

from mica_shared.calculator import calculate, calculation_reply
from mica_shared.quick_commands import parse_quick_command
from desktop.core.native_commands import NativeCommands


@pytest.mark.parametrize('question, answer', [('Rechne 0,1 + 0,2', 'Ergebnis: 0,3'),
    ('berechne (5 + 3) * 2', 'Ergebnis: 16'), ('was ist -3 * -4', 'Ergebnis: 12'),
    ('Was sind 15 Prozent von 80', 'Ergebnis: 12'), ('20% von 250', 'Ergebnis: 50'),
    ('rechne 1 / 3', 'Ergebnis: 0,333333333333')])
def test_decimal_arithmetic_without_model(question, answer):
    command = parse_quick_command(question)
    assert command['kind'] == 'calculate'
    assert calculation_reply(command) == answer


@pytest.mark.parametrize('expression', ['__import__("os")', '2**1000000', '5 // 2', '3 % 2',
                                      '[1,2]', '1e99', '(' * 20 + '1' + ')' * 20, '1 / 0'])
def test_unsupported_or_dangerous_expressions_are_rejected(expression):
    with pytest.raises(ValueError):
        calculate(expression)


def test_actual_offline_desktop_path_without_storage_and_parameter_tampering():
    from desktop.local_main import LocalMica
    mica = LocalMica.__new__(LocalMica)
    mica._request_lock = threading.RLock()
    mica._restoring = False
    mica._offline_start = mica._offline_workspace = True
    mica.ui = SimpleNamespace(remember_conversations=False, muted=True,
                              write_log=Mock(), set_state=Mock(), show_content=Mock())
    mica.client = Mock()
    mica.native_commands = NativeCommands(mica.client, Mock())
    mica.handle_text('Was sind 15 Prozent von 80')
    mica.ui.show_content.assert_called_once_with('Mica', 'Ergebnis: 12')
    mica.client.turn.assert_not_called()
    command = parse_quick_command('rechne 1+2')
    assert 'nicht ausgeführt' in mica.native_commands.execute({**command, 'expression': '9+9'}, 'rechne 1+2')
