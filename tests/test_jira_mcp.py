"""Contract and failure-path tests for the direct Atlassian connection."""
import json
from unittest.mock import patch

import pytest
import requests

from desktop.core.jira_mcp import (ENDPOINT, EMAIL_SECRET, TOKEN_SECRET,
                                   JiraError, JiraMcpClient, save_account)


class Response:
    def __init__(self, message, *, status=200, sse=False, headers=None, lines=None):
        self.status_code = status
        self.headers = {"Content-Type": "text/event-stream" if sse else "application/json", **(headers or {})}
        self.lines = lines if lines is not None else (
            [b': keepalive', b'', b'data: {"jsonrpc":"2.0","method":"notifications/message"}', b'',
             b'data: ' + json.dumps(message).encode(), b''] if sse else [json.dumps(message).encode()])

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def iter_lines(self, **_):
        return iter(self.lines)


class Session:
    def __init__(self, handler=None):
        self.headers = {}
        self.calls = []
        self.handler = handler
        self.closed = False

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs, dict(self.headers)))
        request = kwargs['json']
        if self.handler:
            return self.handler(request)
        result = {"protocolVersion": "2025-06-18", "capabilities": {}} if request['method'] == 'initialize' else {
            "content": [{"type": "text", "text": '[{"id":"site-1","name":"MICA Jira"}]'}]}
        return Response({"jsonrpc": "2.0", "id": request.get('id'), "result": result}, sse=True,
                        headers={"Mcp-Session-Id": "session-123"} if request['method'] == 'initialize' else {})

    def close(self):
        self.closed = True


def test_real_contract_initialization_headers_stream_and_search():
    session = Session()
    with JiraMcpClient('nico@example.com', 'secret', session) as client:
        assert client.resources() == [{'id': 'site-1', 'name': 'MICA Jira'}]
        client.search('site-1', 'assignee = currentUser()')
        client.issue('site-1', 'mica-123')
    assert session.auth == ('nico@example.com', 'secret')
    assert session.trust_env is False
    assert session.closed
    assert [call[1]['json']['method'] for call in session.calls] == [
        'initialize', 'notifications/initialized', 'tools/call', 'tools/call', 'tools/call']
    assert all(call[0] == ENDPOINT and call[1]['allow_redirects'] is False for call in session.calls)
    assert session.calls[1][2]['Mcp-Session-Id'] == 'session-123'
    assert session.calls[1][2]['MCP-Protocol-Version'] == '2025-06-18'
    assert 'id' not in session.calls[1][1]['json']
    assert session.calls[-2][1]['json']['params']['arguments']['maxResults'] == 20
    assert session.calls[-1][1]['json']['params']['arguments']['issueIdOrKey'] == 'MICA-123'


@pytest.mark.parametrize('status', [301, 401, 403, 429, 500])
def test_failures_never_expose_remote_body_or_credentials(status):
    session = Session(lambda _: Response({'error': 'SECRET-TOKEN'}, status=status))
    with JiraMcpClient('nico@example.com', 'SECRET-TOKEN', session) as client:
        with pytest.raises(JiraError) as error:
            client.resources()
    assert 'SECRET-TOKEN' not in str(error.value)
    assert len(session.calls) == 1


def test_write_tools_and_bad_inputs_rejected_before_network():
    session = Session()
    with JiraMcpClient('nico@example.com', 'secret', session) as client:
        for name in ['createJiraIssue', 'executeWrite', 'executeRead', 'deleteJiraIssue']:
            with pytest.raises(JiraError):
                client.call(name, {})
        with pytest.raises(JiraError):
            client.issue('site', '../../123')
        with pytest.raises(JiraError):
            client.search('', 'query')
    assert not session.calls


def test_wrong_rpc_id_unsupported_version_and_invalid_content_are_rejected():
    for response in [Response({'jsonrpc': '2.0', 'id': 'wrong', 'result': {}}),
                     Response({}, headers={'Content-Type': 'text/html'}),
                     Response({}, lines=[b'invalid json']),
                     Response({}, lines=[b'x' * (2 * 1024 * 1024)])]:
        with JiraMcpClient('nico@example.com', 'secret', Session(lambda _, r=response: r)) as client:
            with pytest.raises(JiraError):
                client.resources()
    session = Session(lambda req: Response({'jsonrpc': '2.0', 'id': req['id'],
                                           'result': {'protocolVersion': 'unknown'}}))
    with JiraMcpClient('nico@example.com', 'secret', session) as client:
        with pytest.raises(JiraError):
            client.initialize()
    assert len(session.calls) == 1


def test_transport_exception_is_redacted():
    def fail(_):
        raise requests.ConnectionError('private-token')
    with JiraMcpClient('nico@example.com', 'private-token', Session(fail)) as client:
        with pytest.raises(JiraError) as error:
            client.resources()
    assert 'private-token' not in str(error.value)


def test_account_pair_restored_when_second_write_fails():
    values = {EMAIL_SECRET: 'old@example.com', TOKEN_SECRET: 'old-token'}
    def write(name, value):
        if name == EMAIL_SECRET and value == 'new@example.com':
            raise OSError('storage failed')
        values[name] = value
    with patch('desktop.core.jira_mcp.get_secret', side_effect=values.get), \
         patch('desktop.core.jira_mcp.set_secret', side_effect=write):
        with pytest.raises(JiraError):
            save_account('new@example.com', 'new-token')
    assert values == {EMAIL_SECRET: 'old@example.com', TOKEN_SECRET: 'old-token'}


@pytest.mark.parametrize('email', ['bad', 'a\r\nb@example.com', 'a:b@example.com', 'a@b'])
def test_invalid_account_never_opens_session(email):
    with pytest.raises(JiraError):
        JiraMcpClient(email, 'secret')
