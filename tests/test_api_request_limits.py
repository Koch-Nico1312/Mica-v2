"""Transport bounds: oversized bodies and unbounded structured payloads fail early."""
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.services.api.app import create_app
from backend.services.api.schemas import (
    ServerScanRequest,
    SatelliteHeartbeatRequest,
    SatelliteRegisterRequest,
    TurnRequest,
    VisionAnalyzeRequest,
)
from backend.services.common.contracts import (
    MAX_STRUCTURED_BYTES,
    ExecutionRequest,
    bounded_mapping,
)


TOKEN = 'mica-test-api-token-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
BIG = 'x' * (MAX_STRUCTURED_BYTES + 1)


def test_structured_payloads_are_bounded_at_the_contract():
    with pytest.raises(ValidationError):
        TurnRequest(message='hi', params={'blob': BIG})
    with pytest.raises(ValidationError):
        ExecutionRequest(task_id='a' * 32, action='desktop_control', params={'blob': BIG})
    with pytest.raises(ValidationError):
        ServerScanRequest(snapshot={'blob': BIG})
    with pytest.raises(ValidationError):
        SatelliteHeartbeatRequest(telemetry={'blob': BIG})
    with pytest.raises(ValidationError):
        SatelliteRegisterRequest(
            satellite_id='sat-1', name='Sat', room='Office', capabilities=['c' * 65]
        )
    with pytest.raises(ValidationError):
        VisionAnalyzeRequest(image_base64='A' * (6_990_508 + 1))
    circular: dict = {}
    circular['self'] = circular
    with pytest.raises(ValueError):
        bounded_mapping(circular)


def test_oversized_request_body_is_rejected_with_413(tmp_path, monkeypatch):
    monkeypatch.setenv('MICA_MAX_REQUEST_BYTES', '4096')
    app = create_app(data_dir=tmp_path)
    body = json.dumps({'message': 'x' * 8192})
    with TestClient(app, headers={'X-Mica-API-Token': TOKEN}) as client:
        response = client.post(
            '/v1/turns', content=body, headers={'Content-Type': 'application/json'}
        )
        assert response.status_code == 413, response.text
        assert response.json()['detail'] == 'Request body too large'


def test_request_body_within_the_limit_still_reaches_the_app(tmp_path, monkeypatch):
    monkeypatch.setenv('MICA_MAX_REQUEST_BYTES', '4096')
    app = create_app(data_dir=tmp_path)
    with TestClient(app, headers={'X-Mica-API-Token': TOKEN}) as client:
        response = client.post('/v1/turns', json={'message': 'Hallo'})
        assert response.status_code != 413, response.text


def test_chunked_oversized_body_without_content_length_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv('MICA_MAX_REQUEST_BYTES', '4096')
    app = create_app(data_dir=tmp_path)
    chunks = iter([b'{"message": "', b'x' * 8192, b'"}'])
    with TestClient(app, headers={'X-Mica-API-Token': TOKEN}) as client:
        response = client.post(
            '/v1/turns', content=chunks, headers={'Content-Type': 'application/json'}
        )
        assert response.status_code == 413, response.text


def test_backup_restore_keeps_its_documented_larger_upload_limit(tmp_path, monkeypatch):
    monkeypatch.setenv('MICA_MAX_REQUEST_BYTES', '4096')
    app = create_app(data_dir=tmp_path)
    with TestClient(app, headers={'X-Mica-API-Token': TOKEN}) as client:
        response = client.post(
            '/v1/backups/restore',
            content=b'x' * 8192,
            headers={'Content-Type': 'application/gzip'},
        )
        # Past the transport bound, the approval confirmation still decides.
        assert response.status_code == 401, response.text
