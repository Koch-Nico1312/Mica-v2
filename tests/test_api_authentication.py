"""Direct access must be authenticated independently of Caddy and approvals."""
from fastapi.routing import APIRoute, APIWebSocketRoute
from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from backend.services.api.app import create_app
from backend.services.api.auth import PROVIDER_INGRESS


TOKEN = 'mica-test-api-token-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
HTTP_METHODS = {'get', 'put', 'post', 'delete', 'options', 'head', 'patch'}


def _walk(routes):
    """Yield concrete routes through FastAPI's included-router wrappers.

    FastAPI >= 0.141 no longer flattens included routers into app.routes. If
    the internal shape changes again, the inventory checks below fail loudly
    instead of enumerating nothing and passing anyway.
    """
    for route in routes:
        original = getattr(route, 'original_router', None)
        if original is None:
            yield route
        else:
            yield from _walk(original.routes)


def _inventory(app) -> tuple[set[tuple[str, str]], set[str]]:
    routes = list(_walk(app.routes))
    http = {
        (method.upper(), route.path)
        for route in routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    websockets = {route.path for route in routes if isinstance(route, APIWebSocketRoute)}
    return http, websockets


def test_route_inventory_is_complete_and_matches_openapi(tmp_path):
    app = create_app(data_dir=tmp_path)
    http, websockets = _inventory(app)
    spec = {
        (method.upper(), path)
        for path, item in app.openapi()['paths'].items()
        for method in item
        if method.lower() in HTTP_METHODS
    }
    assert len(http) >= 90, 'route inventory lost coverage'
    assert http == spec, 'hidden or phantom HTTP operations detected'
    assert websockets == {'/v1/voice'}, 'WebSocket inventory changed; extend the auth tests'


def test_every_sensitive_http_route_rejects_anonymous_access(tmp_path):
    app = create_app(data_dir=tmp_path)
    operations = sorted(_inventory(app)[0])
    assert len(operations) >= 90, 'route enumeration lost coverage'
    with TestClient(app) as client:
        for method, path in operations:
            if (method, path) == ('GET', '/health') or (method, path) in PROVIDER_INGRESS:
                continue
            response = client.request(method, path)
            assert response.status_code == 401, (method, path, response.text)
        for path in ['/openapi.json', '/docs', '/redoc', '/unknown']:
            assert client.get(path).status_code == 401


@pytest.mark.parametrize('headers', [
    {}, {'X-Mica-API-Token': 'wrong'}, {'Authorization': f'Bearer {TOKEN}'},
    {'Cookie': f'mica_approval={TOKEN}'},
    [('X-Mica-API-Token', TOKEN), ('X-Mica-API-Token', TOKEN)],
])
def test_wrong_missing_or_ambiguous_credentials_are_rejected(tmp_path, headers):
    with TestClient(create_app(data_dir=tmp_path)) as client:
        assert client.get('/v1/memory/items', headers=headers).status_code == 401
        assert client.get('/v1/audit', params={'token': TOKEN}, headers=headers).status_code == 401
        if not isinstance(headers, list):
            with pytest.raises(WebSocketDisconnect) as closed:
                with client.websocket_connect('/v1/voice', headers=headers):
                    pass
            assert closed.value.code == 1008


def test_valid_token_allows_reads_but_not_action_approval(tmp_path):
    with TestClient(create_app(data_dir=tmp_path), headers={'X-Mica-API-Token': TOKEN}) as client:
        assert client.get('/v1/memory/items').status_code == 200
        assert client.get('/v1/audit').status_code == 200
        assert client.get('/v1/schedules').status_code == 200
        assert client.get('/openapi.json').status_code == 200
        assert client.get('/v1/approvals').status_code == 401


@pytest.mark.parametrize('token', ['', 'short'])
def test_missing_or_short_server_secret_fails_closed(tmp_path, monkeypatch, token):
    monkeypatch.setenv('MICA_API_TOKEN', token)
    with TestClient(create_app(data_dir=tmp_path)) as client:
        assert client.get('/health').status_code == 200
        assert client.get('/v1/memory/items', headers={'X-Mica-API-Token': TOKEN}).status_code == 503
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect('/v1/voice'):
                pass
        assert closed.value.code == 1008


def test_provider_ingress_still_requires_its_own_authentication(tmp_path, monkeypatch):
    monkeypatch.delenv('MICA_TELEGRAM_WEBHOOK_SECRET', raising=False)
    monkeypatch.delenv('MICA_WHATSAPP_APP_SECRET', raising=False)
    with TestClient(create_app(data_dir=tmp_path)) as client:
        for path in ['/v1/connectors/telegram/webhook', '/v1/connectors/whatsapp/webhook']:
            assert client.post(path, json={}).status_code in {401, 403, 409, 503}
        assert client.get('/v1/connectors/telegram/webhook').status_code == 401
        assert client.post('/v1/connectors/telegram/events', json={}).status_code == 401
