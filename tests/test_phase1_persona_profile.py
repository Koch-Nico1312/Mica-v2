from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1] / "mica_core"
sys.path.insert(0, str(ROOT))

from services.common.contracts import VoiceControl
from services.common.persona import load_persona, normalize_conversation_mode, persona_prompt
from services.common.profile import LocalProfileStore, PersonalProfile, PersonalProfileUpdate, profile_prompt


class PersonaAndProfileUnitTests(unittest.TestCase):
    def test_persona_is_versioned_and_invalid_configuration_falls_back(self) -> None:
        persona = load_persona()
        self.assertEqual(persona.schema_version, 1)
        self.assertEqual(persona.name, "MICA")
        self.assertIn("weibliche", persona.identity)

        with tempfile.TemporaryDirectory() as temporary:
            invalid = Path(temporary) / "persona.json"
            invalid.write_text('{"schema_version":2,"name":"Other"}', encoding="utf-8")
            fallback = load_persona(invalid)
        self.assertEqual(fallback, load_persona(Path("missing-persona.json")))
        self.assertEqual(normalize_conversation_mode("unknown"), "personal")

    def test_modes_change_focus_but_not_identity(self) -> None:
        prompts = {mode: persona_prompt(mode) for mode in ("personal", "technical", "monitoring")}
        for prompt in prompts.values():
            self.assertIn("Du bist MICA", prompt)
            self.assertIn("weibliche lokale Assistentin", prompt)
            self.assertIn("warm, direkt, hilfreich, leicht humorvoll", prompt)
        self.assertIn("umsetzbaren Schritten", prompts["technical"])
        self.assertIn("fasse dich sehr kurz", prompts["monitoring"])

    def test_profile_is_local_allowlisted_and_mode_relevant(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = LocalProfileStore(Path(temporary) / "profile.json")
            updated = store.update(PersonalProfileUpdate(
                preferred_address="Leo",
                communication_preferences=["Ein Schritt auf einmal"],
                important_topics=["Homelab"],
                relationship_context="Langjaehrige Zusammenarbeit",
            ))
            self.assertEqual(store.read(), updated)
            stored = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertEqual(set(stored), {
                "preferred_address", "communication_preferences", "important_topics", "relationship_context",
            })
        self.assertIn("Beziehungskontext", profile_prompt(updated, "personal"))
        self.assertNotIn("Beziehungskontext", profile_prompt(updated, "technical"))
        with self.assertRaises(ValidationError):
            PersonalProfile.model_validate({"secret": "must not be stored"})

    def test_persona_and_profile_survive_new_runtime_instances(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile_path = Path(temporary) / "profile.json"
            LocalProfileStore(profile_path).update(PersonalProfileUpdate(
                preferred_address="Leo",
                communication_preferences=["Kurz und direkt"],
            ))

            restarted_store = LocalProfileStore(profile_path)
            self.assertEqual(restarted_store.read().preferred_address, "Leo")
            self.assertEqual(restarted_store.read().communication_preferences, ["Kurz und direkt"])
            self.assertEqual(load_persona(), load_persona())

    def test_voice_control_keeps_mode_and_falls_back_safely(self) -> None:
        base = {"command": "start", "input_mode": "push_to_talk", "state": "listening"}
        self.assertEqual(VoiceControl(**base, conversation_mode="technical").conversation_mode, "technical")
        self.assertEqual(VoiceControl(**base, conversation_mode="invalid").conversation_mode, "personal")


class Phase1ApiTests(unittest.TestCase):
    def _environment(self, temporary: str) -> dict[str, str]:
        root = Path(temporary)
        return {
            "BRAIN_DIR": str(root / "brain"),
            "INDEX_PATH": str(root / "index.sqlite3"),
            "AUDIT_PATH": str(root / "audit.jsonl"),
            "APPROVAL_DB": str(root / "approvals.sqlite3"),
            "SCHEDULE_DB": str(root / "schedules.sqlite3"),
            "IMPROVEMENT_DB": str(root / "improvements.sqlite3"),
            "IMPROVEMENT_WORKSPACE": str(root / "improvements"),
            "CONNECTOR_DB": str(root / "connectors.sqlite3"),
            "MICA_PROFILE_PATH": str(root / "profile.json"),
            "MICA_APPROVAL_SECRET": "phase1-test-secret",
        }

    def test_profile_endpoint_only_updates_allowlisted_fields_and_audit_hides_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, self._environment(temporary), clear=False,
        ):
            module = importlib.reload(importlib.import_module("services.api.app"))
            with TestClient(module.app) as client:
                response = client.patch("/v1/profile", json={
                    "preferred_address": "Private Anrede", "important_topics": ["Privates Thema"],
                })
                self.assertEqual(response.status_code, 200)
                self.assertEqual(client.get("/v1/profile").json()["profile"]["preferred_address"], "Private Anrede")
                self.assertEqual(client.patch("/v1/profile", json={"secret": "no"}).status_code, 422)
            audit_text = Path(os.environ["AUDIT_PATH"]).read_text(encoding="utf-8")
            self.assertIn("preferred_address", audit_text)
            self.assertNotIn("Private Anrede", audit_text)
            self.assertNotIn("Privates Thema", audit_text)

    def test_chat_and_turn_use_normalized_mode_persona_and_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, self._environment(temporary), clear=False,
        ):
            module = importlib.reload(importlib.import_module("services.api.app"))
            module.profile_store.update(module.PersonalProfileUpdate(
                preferred_address="Leo", relationship_context="Nur im persoenlichen Modus",
            ))
            captured: dict[str, object] = {}

            def completion(prompt: str, tokens: int, temperature: float, *, system_prompt: str) -> str:
                captured.update(prompt=prompt, tokens=tokens, temperature=temperature, system_prompt=system_prompt)
                return "Antwort"

            with (
                patch.object(module.brain, "search", return_value=[]),
                patch.object(module.brain, "write", return_value={"id": "1"}),
                patch.object(module, "_local_completion", side_effect=completion),
            ):
                result = module.turn(module.TurnRequest(message="Status?", conversation_mode="monitoring"))
            self.assertEqual(result["conversation_mode"], "monitoring")
            self.assertEqual(captured["tokens"], 192)
            self.assertIn("Du bist MICA", str(captured["system_prompt"]))
            self.assertIn("fasse dich sehr kurz", str(captured["system_prompt"]))
            self.assertIn("Bevorzugte Anrede: Leo", str(captured["prompt"]))
            self.assertNotIn("Nur im persoenlichen Modus", str(captured["prompt"]))

            with (
                patch.object(module.brain, "search", return_value=[]),
                patch.object(module.brain, "write", return_value={"id": "2"}),
                patch.object(module, "_local_completion", return_value="Antwort"),
            ):
                fallback = module.chat(module.ChatRequest(message="Hallo", conversation_mode="invalid"))
            self.assertEqual(fallback["conversation_mode"], "personal")

    def test_voice_start_keeps_conversation_mode_for_the_session_turn(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, self._environment(temporary), clear=False,
        ):
            module = importlib.reload(importlib.import_module("services.api.app"))

            class Response:
                def __init__(self, *, data=None, content=b""):
                    self._data = data or {}
                    self.content = content

                def raise_for_status(self) -> None:
                    return None

                def json(self):
                    return self._data

            class AsyncClient:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_args):
                    return None

                async def post(self, url, **_kwargs):
                    if url.endswith("/v1/transcribe"):
                        return Response(data={"text": "Bitte technisch"})
                    return Response(content=b"RIFF-test")

            planned_turn = Mock(return_value={
                "schema_version": 1, "turn_id": "1" * 32,
                "state": "completed", "reply": "Technische Antwort",
            })
            with (
                patch.object(module.httpx, "AsyncClient", return_value=AsyncClient()),
                patch.object(module, "turn", planned_turn),
                TestClient(module.app) as client,
                client.websocket_connect("/v1/voice", headers={"origin": "http://localhost:8088"}) as websocket,
            ):
                self.assertEqual(websocket.receive_json()["conversation_mode"], "personal")
                websocket.send_json({
                    "schema_version": 1, "command": "start", "input_mode": "push_to_talk",
                    "state": "listening", "conversation_mode": "technical",
                })
                self.assertEqual(websocket.receive_json()["conversation_mode"], "technical")
                websocket.send_bytes(b"\x00\x00" * 16)
                websocket.receive_json()
                websocket.send_json({
                    "schema_version": 1, "command": "finalize",
                    "input_mode": "push_to_talk", "state": "transcribing",
                })
                for _ in range(5):
                    websocket.receive_json()
                websocket.receive_bytes()
            request = planned_turn.call_args.args[0]
            self.assertEqual(request.client, "voice")
            self.assertEqual(request.conversation_mode, "technical")


if __name__ == "__main__":
    unittest.main(verbosity=2)
