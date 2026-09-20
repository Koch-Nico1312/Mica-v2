import json
import urllib.error
import urllib.request

from core.intercom_mode import IntercomMode
from core.mica_3d import Mica3DIntegration


def test_mica_3d_connect_fails_closed_without_engine_adapter():
    integration = Mica3DIntegration()

    assert integration.connect("ws://localhost:9000") is False
    assert integration.connected is False


def test_mica_3d_connect_requires_positive_adapter_handshake(tmp_path, monkeypatch):
    monkeypatch.setattr("core.mica_3d.MICA_3D_CONFIG_PATH", tmp_path / "mica_3d.json")
    attempted = []
    integration = Mica3DIntegration(connector=lambda target: attempted.append(target) or True)

    assert integration.connect("ws://engine.local:9000") is True
    assert integration.connected is True
    assert attempted == ["ws://engine.local:9000"]


def _post(address, payload):
    request = urllib.request.Request(
        f"http://127.0.0.1:{address[1]}/intercom/message",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        return response.status


def test_intercom_http_receiver_accepts_targeted_message_and_stops():
    intercom = IntercomMode()
    intercom.activate("office")
    assert intercom.start_http_server("127.0.0.1", 0) is True
    address = intercom.http_server_address
    assert address is not None

    assert _post(address, {
        "from_room": "kitchen",
        "to_rooms": ["office"],
        "type": "text",
        "message": "Dinner is ready",
    }) == 202
    assert intercom.receive_message()["message"] == "Dinner is ready"

    intercom.deactivate()
    assert intercom.http_server_address is None


def test_intercom_http_receiver_rejects_wrong_target():
    intercom = IntercomMode()
    intercom.activate("office")
    assert intercom.start_http_server("127.0.0.1", 0) is True
    try:
        try:
            _post(intercom.http_server_address, {
                "from_room": "kitchen",
                "to_rooms": ["bedroom"],
                "type": "text",
                "message": "private",
            })
        except urllib.error.HTTPError as exc:
            assert exc.code == 422
        else:
            raise AssertionError("wrong-target message was accepted")
        assert intercom.receive_message() is None
    finally:
        intercom.stop_http_server()


def test_intercom_http_receiver_rejects_non_object_json():
    intercom = IntercomMode()
    intercom.activate("office")
    assert intercom.start_http_server("127.0.0.1", 0) is True
    address = intercom.http_server_address
    request = urllib.request.Request(
        f"http://127.0.0.1:{address[1]}/intercom/message",
        data=b"[]",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        try:
            urllib.request.urlopen(request, timeout=2)
        except urllib.error.HTTPError as exc:
            assert exc.code == 422
        else:
            raise AssertionError("non-object JSON was accepted")
    finally:
        intercom.stop_http_server()
