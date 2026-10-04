from __future__ import annotations

import io
import json
import queue
import sys
import threading
import unittest
import wave
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy  # Keep the native module loaded across temporary sys.modules patches.
from websocket import WebSocketTimeoutException

from desktop.core.local_core_client import LocalCoreClient, LocalCoreError
from desktop.core.local_voice import CoreVoiceSession
from desktop.core.response_timing import TimingHistory


def speech_wav():
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\x00\x00" * 240)
    return output.getvalue()


class VoiceSocket:
    def __init__(self, reply=True):
        self.messages = queue.Queue()
        self.controls = []
        self.audio = []
        self.send_threads = []
        self.reply = reply
        self.closed = False

    def settimeout(self, timeout):
        self.timeout = timeout

    def send(self, data):
        control = json.loads(data)
        self.controls.append(control)
        if control["command"] == "finalize" and self.reply:
            self.messages.put(json.dumps({"type": "transcript", "text": "Hallo"}))
            self.messages.put(json.dumps({"type": "response", "text": "Guten Tag"}))
            self.messages.put(speech_wav())

    def send_binary(self, payload):
        self.audio.append(payload)
        self.send_threads.append(threading.current_thread().name)

    def recv(self):
        if self.closed:
            raise OSError("closed")
        try:
            return self.messages.get(timeout=0.01)
        except queue.Empty:
            raise WebSocketTimeoutException() from None

    def close(self):
        self.closed = True

    def abort(self):
        self.closed = True


class VoiceReliabilityTests(unittest.TestCase):
    def session(self, **kwargs):
        return CoreVoiceSession(LocalCoreClient("https://localhost:8443", api_token="test"), **kwargs)

    def run_session(self, session, websocket, *, block_count=3, input_error=False,
                    finish_capture=True, input_active=True):
        opened = []

        class InputStream:
            def __init__(self, **kwargs):
                self.callback = kwargs["callback"]
                self.active = input_active
                opened.append(kwargs)

            def __enter__(self):
                if input_error:
                    raise OSError("unplugged")

                def capture():
                    for _ in range(block_count):
                        self.callback(b"\x00\x00" * 1280, 1280, None, False)

                callback_thread = threading.Thread(target=capture, name="test-audio-callback")
                callback_thread.start()
                callback_thread.join(timeout=2)
                if finish_capture:
                    session.finish()
                return self

            def __exit__(self, *args):
                return False

        audio = SimpleNamespace(RawInputStream=InputStream, stop=Mock(), play=Mock(), wait=Mock())
        with patch.dict(sys.modules, {"sounddevice": audio}), \
                patch("websocket.create_connection", return_value=websocket), \
                patch.object(session, "_selected_device", side_effect=[7, 9]):
            self.assertTrue(session.start())
            session._worker.join(timeout=3)
            self.assertFalse(session._worker.is_alive())
            self.assertFalse(session.active)
        return opened, audio

    def test_devices_are_used_and_audio_is_sent_outside_capture_callback(self):
        transcripts, replies, errors = [], [], []
        session = self.session(on_transcript=transcripts.append, on_reply=replies.append, on_error=errors.append)
        socket = VoiceSocket()
        opened, audio = self.run_session(session, socket)
        self.assertEqual(opened[0]["device"], 7)
        self.assertEqual(len(socket.audio), 3)
        self.assertNotIn("test-audio-callback", socket.send_threads)
        self.assertEqual([control["command"] for control in socket.controls], ["start", "finalize"])
        self.assertEqual(transcripts, ["Hallo"])
        self.assertEqual(replies, ["Guten Tag"])
        self.assertEqual(audio.play.call_args.kwargs["device"], 9)
        self.assertEqual(errors, [])
        self.assertTrue(socket.closed)

    def test_receive_timeouts_do_not_abort_a_slow_reply(self):
        session = self.session()
        socket = Mock()
        socket.recv.side_effect = [WebSocketTimeoutException(), TimeoutError(), speech_wav()]
        completed = threading.Event()
        with patch.object(session, "_play_wav") as play:
            session._reader(socket, completed)
        self.assertTrue(completed.is_set())
        play.assert_called_once()

    def test_voice_timings_record_receipt_and_playback_completion(self):
        history = TimingHistory()
        session = self.session()
        with patch('desktop.core.local_voice.RESPONSE_TIMINGS', history):
            self.run_session(session, VoiceSocket())
        record = history.snapshot()[0]
        self.assertEqual(record['outcome'], 'success')
        self.assertTrue({'connect_ms', 'transcript_ms', 'reply_ms', 'audio_ms', 'total_ms'} <= record.keys())
        self.assertGreaterEqual(record['audio_ms'], record['reply_ms'])
        self.assertEqual(len(history.snapshot()), 1)

    def test_voice_timeout_and_input_failure_are_not_success_timings(self):
        for input_error in (False, True):
            with self.subTest(input_error=input_error):
                history = TimingHistory()
                session = self.session(response_timeout=0.03)
                with patch('desktop.core.local_voice.RESPONSE_TIMINGS', history):
                    self.run_session(session, VoiceSocket(reply=False), input_error=input_error)
                self.assertEqual(history.snapshot()[0]['outcome'], 'failed')
                self.assertNotIn('reply_ms', history.snapshot()[0])

    def test_voice_cancellation_remains_cancelled_not_failed_or_successful(self):
        class CancelSocket(VoiceSocket):
            def send(self, data):
                super().send(data)
                if json.loads(data)['command'] == 'finalize':
                    self.messages.put(json.dumps({'type': 'state', 'state': 'cancelled'}))

        history = TimingHistory()
        session = self.session()
        with patch('desktop.core.local_voice.RESPONSE_TIMINGS', history):
            self.run_session(session, CancelSocket(reply=False))
        self.assertEqual(len(history.snapshot()), 1)
        self.assertEqual(history.snapshot()[0]['outcome'], 'cancelled')
        self.assertNotIn('audio_ms', history.snapshot()[0])

    def test_audio_arriving_after_cancel_is_discarded(self):
        session = self.session()
        socket = Mock()

        def receive():
            session.cancel()
            return speech_wav()

        socket.recv.side_effect = receive
        with patch.dict(sys.modules, {"sounddevice": Mock()}), patch.object(session, "_play_wav") as play:
            session._reader(socket, threading.Event())
        play.assert_not_called()

    def test_playback_cannot_restart_after_cancel(self):
        cancelled = threading.Event()
        cancelled.set()
        audio = Mock()
        with patch.dict(sys.modules, {"sounddevice": audio}):
            CoreVoiceSession._play_wav(speech_wav(), cancelled=cancelled, playback_lock=threading.Lock())
        audio.play.assert_not_called()

    def test_response_deadline_reports_error_and_releases_session(self):
        errors = []
        session = self.session(on_error=errors.append, response_timeout=0.03)
        self.run_session(session, VoiceSocket(reply=False))
        self.assertEqual(len(errors), 1)
        self.assertIn("zu lange", errors[0])

    def test_capture_overflow_fails_instead_of_sending_truncated_speech(self):
        errors = []
        session = self.session(on_error=errors.append)
        socket = VoiceSocket()
        self.run_session(session, socket, block_count=65)
        self.assertIn("zu langsam", errors[0])
        self.assertNotIn("finalize", [control["command"] for control in socket.controls])

    def test_unplugged_microphone_can_be_retried(self):
        errors = []
        session = self.session(on_error=errors.append)
        self.run_session(session, VoiceSocket(), input_error=True)
        self.assertEqual(len(errors), 1)
        self.run_session(session, VoiceSocket())
        self.assertEqual(len(errors), 1)

    def test_missing_selected_microphone_does_not_record_another_device(self):
        with patch("desktop.memory.config_manager.get_input_device", return_value="Headset"), \
                patch("desktop.core.audio_devices.resolve", return_value=None):
            with self.assertRaisesRegex(LocalCoreError, "Mikrofon"):
                CoreVoiceSession._selected_device("input")

    def test_cancel_during_connection_does_not_open_microphone(self):
        session = self.session()
        socket = VoiceSocket()

        def connect(*args, **kwargs):
            session.cancel()
            return socket

        audio = Mock()
        with patch.dict(sys.modules, {"sounddevice": audio}), \
                patch("websocket.create_connection", side_effect=connect), \
                patch.object(session, "_selected_device", return_value=None):
            session.start()
            session._worker.join(timeout=3)
        audio.RawInputStream.assert_not_called()
        self.assertEqual(socket.controls, [])
        self.assertTrue(socket.closed)

    def test_lost_input_stream_reports_disconnection(self):
        errors = []
        session = self.session(on_error=errors.append)
        self.run_session(session, VoiceSocket(), block_count=0,
                         finish_capture=False, input_active=False)
        self.assertEqual(len(errors), 1)
        self.assertIn("getrennt", errors[0])

    def test_cancel_wakes_socket_without_waiting_for_close_handshake(self):
        session = self.session()
        session._socket = Mock()
        with patch.dict(sys.modules, {"sounddevice": Mock()}):
            session.cancel()
        session._socket.abort.assert_called_once()
        session._socket.close.assert_not_called()

