"""Preview-only dictation with deterministic spoken corrections and undo."""
import re
import threading
import time


class DictationDraft:
    def __init__(self):
        self.text = ''
        self.history = []
        self.replace_next = False

    def update(self, text):
        if len(text) > 16000:
            raise ValueError('Diktat darf höchstens 16.000 Zeichen enthalten.')
        if text != self.text:
            self.history = (self.history + [self.text])[-20:]
            self.text = text

    def replace_sentence(self, replacement):
        text = self.text.rstrip()
        sentences = list(re.finditer(r'[.!?](?:\s+|$)', text))
        boundary = sentences[-2].end() if text.endswith(('.', '!', '?')) and len(sentences) > 1 else sentences[-1].end() if sentences and not text.endswith(('.', '!', '?')) else 0
        self.update(text[:boundary].rstrip() + (' ' if boundary else '') + replacement.strip())

    def accept(self, transcript):
        command = transcript.strip().rstrip('.!?')
        if self.replace_next:
            self.replace_next = False
            self.replace_sentence(transcript)
            return 'replaced'
        if command.casefold() in {'rückgängig', 'letzte änderung rückgängig'}:
            self.undo()
            return 'undo'
        if command.casefold() in {'mach daraus stichpunkte', 'mache daraus stichpunkte'}:
            return 'bullets'
        match = re.fullmatch(r'ersetze den letzten satz(?: durch (.+))?', command, re.I)
        if match:
            if match[1]:
                replacement = re.fullmatch(r'ersetze den letzten satz durch (.+)', transcript.strip(), re.I)[1]
                self.replace_sentence(replacement)
            else:
                self.replace_next = True
            return 'replaced' if match[1] else 'replacement_pending'
        self.update(self.text.rstrip() + (' ' if self.text.strip() else '') + transcript.strip())
        return 'appended'

    def undo(self):
        self.replace_next = False
        if self.history:
            self.text = self.history.pop()


def record_clip(stop, cancelled, *, seconds=10):
    import sounddevice as sd
    from desktop.core.local_voice import CoreVoiceSession
    audio = bytearray()
    limit = 32000 * seconds
    def capture(data, frames, timing, status):
        if not cancelled.is_set():
            audio.extend(bytes(data)[:max(0, limit - len(audio))])
    with sd.RawInputStream(samplerate=16000, channels=1, dtype='int16', blocksize=1600,
            device=CoreVoiceSession._selected_device('input'), callback=capture):
        deadline = time.monotonic() + seconds
        while not cancelled.is_set() and not stop.wait(.05) and time.monotonic() < deadline:
            pass
    return b'' if cancelled.is_set() else bytes(audio)


class DictationCapture:
    def __init__(self):
        self.stop, self.cancelled = threading.Event(), threading.Event()
