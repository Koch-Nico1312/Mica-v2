from __future__ import annotations
from typing import Any
from backend.services.api.schemas import TurnRequest
import asyncio
import os
from fastapi import HTTPException, WebSocketDisconnect
from fastapi import WebSocket


class VoiceRoutes:
    async def voice(self, websocket: WebSocket) -> None:
        """Local browser audio transport. It neither uploads audio nor persists it."""
        origin = (websocket.headers.get("origin") or "").rstrip("/")
        if origin not in self.ALLOWED_VOICE_ORIGINS:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        session_mode = self.normalize_conversation_mode("personal")
        session_remember = True
        session_key = id(websocket)
        with self._VOICE_LOCK:
            self._VOICE_SESSIONS[session_key] = (asyncio.get_running_loop(), websocket)
        self._voice_presence("listening")
        await websocket.send_json(
            {
                "type": "state",
                "schema_version": 1,
                "state": "listening",
                "sample_rate": 16000,
                "storage": "none",
                "conversation_mode": session_mode,
            }
        )
        recorded = bytearray()

        async def finalise() -> None:
            if not recorded:
                self._voice_presence("error")
                await websocket.send_json(
                    {"type": "state", "schema_version": 1, "state": "failed"}
                )
                await websocket.send_json(
                    {"type": "error", "message": "Kein Audio empfangen."}
                )
                return
            timeout = self.httpx.Timeout(120.0, connect=10.0)
            try:
                self._voice_presence("thinking")
                await websocket.send_json(
                    {"type": "state", "schema_version": 1, "state": "transcribing"}
                )
                async with self.httpx.AsyncClient(timeout=timeout) as client:
                    transcript_response = await client.post(
                        os.getenv("STT_URL", "http://stt:8091") + "/v1/transcribe",
                        content=bytes(recorded),
                    )
                    transcript_response.raise_for_status()
                    transcript = str(transcript_response.json().get("text", "")).strip()
                    if not transcript:
                        raise ValueError("Leeres Transkript")
                    if self._is_emergency_phrase(transcript):
                        stopped = self._activate_emergency_stop(
                            "voice", exclude_voice=websocket
                        )
                        await websocket.send_json(
                            {"type": "transcript", "text": transcript}
                        )
                        await websocket.send_json(
                            {
                                "type": "response",
                                "text": "Not-Aus ist aktiv.",
                                "emergency_stop": stopped,
                            }
                        )
                        await websocket.send_json(
                            {"type": "state", "schema_version": 1, "state": "cancelled"}
                        )
                        await websocket.close(code=1001, reason="emergency_stop")
                        return
                    await websocket.send_json(
                        {"type": "state", "schema_version": 1, "state": "planning"}
                    )
                    turn_result = await asyncio.to_thread(
                        self._voice_turn,
                        self.TurnRequest(
                            message=transcript,
                            client="voice",
                            conversation_mode=session_mode,
                            remember=session_remember,
                        ),
                    )
                    if turn_result.get("state") == "planned":
                        plan = turn_result["plan"]
                        permission = plan.get("permission", {})
                        if permission.get("requires_approval"):
                            self._voice_presence("approval_required")
                            await websocket.send_json(
                                {
                                    "type": "state",
                                    "schema_version": 1,
                                    "state": "approval_required",
                                    "task_id": plan.get("task_id"),
                                }
                            )
                            reply = f"Aktion {plan.get('action', 'unbekannt')} ist geplant und wartet auf die lokale Freigabe."
                        else:
                            reply = f"Aktion {plan.get('action', 'unbekannt')} wurde lokal geplant."
                    else:
                        reply = str(
                            turn_result.get("reply", "Lokale Antwort nicht verfuegbar.")
                        )
                    speech_response = await client.post(
                        os.getenv("TTS_URL", "http://tts:8092") + "/v1/synthesize",
                        json={"text": reply},
                    )
                    speech_response.raise_for_status()
            except (HTTPException, self.httpx.HTTPError, ValueError) as error:
                self._voice_presence("error")
                detail = (
                    error.detail if isinstance(error, HTTPException) else str(error)
                )
                safe_detail = str(detail)[:250]
                self.audit.append("voice.failed", {"reason": safe_detail})
                await websocket.send_json(
                    {"type": "state", "schema_version": 1, "state": "failed"}
                )
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "Lokale Sprachverarbeitung nicht bereit.",
                        "detail": safe_detail,
                    }
                )
                return
            self.audit.append(
                "voice.completed",
                {
                    "turn_id": turn_result.get("turn_id"),
                    "message_length": len(transcript),
                    "reply_length": len(reply),
                    "pipeline": "/v1/turns",
                    "conversation_mode": session_mode,
                },
            )
            await websocket.send_json({"type": "transcript", "text": transcript})
            await websocket.send_json({"type": "response", "text": reply})
            await websocket.send_json(
                {"type": "state", "schema_version": 1, "state": "speaking"}
            )
            self._voice_presence("speaking")
            await websocket.send_bytes(speech_response.content)

        try:
            while True:
                packet = await websocket.receive()
                if packet.get("type") == "websocket.disconnect":
                    return
                if packet.get("bytes") is not None:
                    audio = packet["bytes"]
                    if len(recorded) + len(audio) > self.MAX_VOICE_BYTES:
                        recorded.clear()
                        await websocket.send_json(
                            {"type": "error", "message": "Audioaufnahme ist zu groß."}
                        )
                        await websocket.close(code=1009)
                        return
                    recorded.extend(audio)
                    await websocket.send_json(
                        {"type": "audio_ack", "bytes": len(packet["bytes"])}
                    )
                elif packet.get("text"):
                    if (
                        len(packet["text"].encode("utf-8"))
                        > self.MAX_VOICE_CONTROL_BYTES
                    ):
                        await websocket.close(code=1009)
                        return
                    try:
                        command = __import__("json").loads(packet["text"])
                    except ValueError:
                        command = {}
                    try:
                        control = self.VoiceControl.model_validate(command)
                    except ValueError:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "message": "Ungueltiger VoiceControl-Vertrag.",
                            }
                        )
                        continue
                    if control.command == "finalize":
                        session_remember = session_remember and control.remember
                        await finalise()
                        recorded.clear()
                    elif control.command == "cancel":
                        recorded.clear()
                        self._voice_presence("idle")
                        await websocket.send_json(
                            {"type": "state", "schema_version": 1, "state": "cancelled"}
                        )
                        await websocket.close(code=1000)
                        return
                    else:
                        session_mode = self.normalize_conversation_mode(
                            control.conversation_mode
                        )
                        session_remember = control.remember
                        self._voice_presence("listening")
                        await websocket.send_json(
                            {
                                "type": "state",
                                "schema_version": 1,
                                "state": "listening",
                                "conversation_mode": session_mode,
                            }
                        )
        except WebSocketDisconnect:
            return
        finally:
            if not self.policy.is_emergency_stopped():
                self._voice_presence("idle")
            with self._VOICE_LOCK:
                self._VOICE_SESSIONS.pop(session_key, None)

    async def _close_voice_for_stop(self, websocket: WebSocket) -> None:
        try:
            await websocket.send_json(
                {"type": "state", "schema_version": 1, "state": "cancelled"}
            )
            await websocket.close(code=1001, reason="emergency_stop")
        except (RuntimeError, WebSocketDisconnect):
            pass

    def _cancel_active_voice(self, exclude: WebSocket | None = None) -> int:
        with self._VOICE_LOCK:
            sessions = [
                item for item in self._VOICE_SESSIONS.values() if item[1] is not exclude
            ]
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        for loop, websocket in sessions:
            if loop.is_closed():
                continue
            if loop is current:
                loop.create_task(self._close_voice_for_stop(websocket))
            else:
                asyncio.run_coroutine_threadsafe(
                    self._close_voice_for_stop(websocket), loop
                )
        return len(sessions)

    def _voice_presence(self, state: str) -> None:
        try:
            with self.StorageLease(self.brain.root.parent, timeout=0):
                if not (self.brain.root.parent / ".restore-incomplete").exists():
                    self.phase4_store.set_presence(state, "voice")
        except self.StorageBusy:
            pass

    def _voice_turn(self, request: TurnRequest) -> dict[str, Any]:
        try:
            with self.StorageLease(self.brain.root.parent, timeout=1):
                if (self.brain.root.parent / ".restore-incomplete").exists():
                    raise HTTPException(503, "Wiederherstellung unvollständig")
                return self.turn(request)
        except self.StorageBusy as error:
            raise HTTPException(503, "Backup/Wiederherstellung läuft") from error


ROUTES = [("/v1/voice", "websocket", "voice")]
