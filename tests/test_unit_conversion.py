import pytest
from unittest.mock import Mock
from types import SimpleNamespace
import threading

from mica_shared.quick_commands import parse_quick_command
from mica_shared.unit_conversion import convert, conversion_reply
from desktop.core.native_commands import NativeCommands


@pytest.mark.parametrize('message, expected', [
    ('Mica, rechne 2,5 kg in gramm um', '2,5 kg = 2500 g'),
    ('bitte 12 zoll in cm', '12 in = 30,48 cm'),
    ('32 fahrenheit in celsius', '32 °F = 0 °C'),
    ('100 celsius in fahrenheit', '100 °C = 212 °F'),
    ('-40 °C in °F', '-40 °C = -40 °F'),
    ('0 kelvin in celsius', '0 K = -273,15 °C'),
    ('1 hektar in m2', '1 ha = 10000 m²'),
    ('1,5 stunden in minuten', '1,5 h = 90 min'),
    ('500 ml in liter', '500 ml = 0,5 l'),
])
def test_exact_everyday_conversions(message, expected):
    command = parse_quick_command(message)
    assert command and command['kind'] == 'unit_convert'
    assert conversion_reply(command) == expected


def test_incompatible_dimensions_and_impossible_temperature_have_clear_errors():
    assert 'unterschiedliche' in conversion_reply(parse_quick_command('1 kg in liter'))
    assert 'Nullpunkt' in conversion_reply(parse_quick_command('-1 kelvin in celsius'))
    for value in ('NaN', 'Infinity', '1e100', 'not a number'):
        with pytest.raises(ValueError):
            convert(value, 'kg', 'g')


@pytest.mark.parametrize('message', ['1 kg in g; delete files', '__import__(os) m in cm',
                                   '1 kilogram in cup', 'öffne editor', 'zeige 2 kg in g bitte'])
def test_only_bounded_exact_conversion_grammar(message):
    command = parse_quick_command(message)
    assert command is None or command['kind'] != 'unit_convert'


def test_native_conversion_needs_no_backend_or_model_and_rejects_tampering():
    client = Mock()
    native = NativeCommands(client, Mock())
    message = '2 km in m'
    command = parse_quick_command(message)
    assert native.execute(command, message) == '2 km = 2000 m'
    assert 'nicht ausgeführt' in native.execute({**command, 'value': '999'}, message)
    client.plan.assert_not_called()
    client.execute.assert_not_called()


def test_canonical_desktop_converts_even_when_started_offline_without_storage():
    from desktop.local_main import LocalMica
    mica = LocalMica.__new__(LocalMica)
    mica._request_lock = threading.RLock()
    mica._restoring = False
    mica._offline_start = True
    mica._offline_workspace = True
    mica.ui = SimpleNamespace(remember_conversations=False, muted=True,
                              write_log=Mock(), set_state=Mock(), show_content=Mock())
    mica.client = Mock()
    mica.native_commands = NativeCommands(mica.client, Mock())
    mica.handle_text('2 km in m')
    mica.ui.show_content.assert_called_once_with('Mica', '2 km = 2000 m')
    mica.client.turn.assert_not_called()
    mica.client.select_documents.assert_not_called()
