"""Native HTTP and voice must use the same API credential boundary."""
import sys
import pytest
from types import SimpleNamespace
from unittest.mock import Mock

from desktop.core.local_core_client import LocalCoreClient, LocalCoreError
from desktop.core.local_voice import CoreVoiceSession


TOKEN = 'fake-native-client-token-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'


def test_missing_credential_store_keeps_shell_constructible_and_blocks_requests(monkeypatch):
    from desktop.core import secure_store
    monkeypatch.delenv('MICA_API_TOKEN', raising=False)
    monkeypatch.setattr(secure_store, 'get_secret', Mock(side_effect=secure_store.SecureStoreUnavailable('unavailable')))
    client = LocalCoreClient('https://127.0.0.1:8443')
    request = Mock()
    monkeypatch.setattr(client.session, 'request', request)
    with pytest.raises(LocalCoreError, match='Credential Manager'):
        client.health()
    request.assert_not_called()


def test_client_uses_credential_manager_when_environment_token_is_absent(monkeypatch):
    from desktop.core import secure_store
    monkeypatch.delenv('MICA_API_TOKEN', raising=False)
    lookup = Mock(return_value=TOKEN)
    monkeypatch.setattr(secure_store, 'get_secret', lookup)
    client = LocalCoreClient('https://127.0.0.1:8443')
    lookup.assert_called_once_with('MICA_API_TOKEN')
    assert client.session.headers['X-Mica-API-Token'] == TOKEN
    assert client.auth_headers == {'X-Mica-API-Token': TOKEN}
    assert client.session.trust_env is False


def test_voice_handshake_carries_native_api_token_before_microphone_open(monkeypatch):
    connect = Mock(side_effect=RuntimeError('stop before microphone'))
    monkeypatch.setitem(sys.modules, 'websocket', SimpleNamespace(create_connection=connect))
    monkeypatch.setitem(sys.modules, 'sounddevice', SimpleNamespace())
    client = LocalCoreClient('https://127.0.0.1:8443', api_token=TOKEN)
    session = CoreVoiceSession(client)
    session._run()
    assert connect.call_args.args == ('wss://127.0.0.1:8443/v1/voice',)
    assert connect.call_args.kwargs['header'] == {'X-Mica-API-Token': TOKEN}
    assert connect.call_args.kwargs['origin'] == client.base_url
