"""Read explicitly dropped files locally. Only extracted text is sent to Core."""
from __future__ import annotations
import json
import hashlib
import io
import os
from pathlib import Path
import subprocess
import uuid
from datetime import datetime, UTC

MAX_BYTES = 10 * 1024 * 1024
MAX_TEXT = 32000
TEXT_SUFFIXES = {".txt", ".md", ".csv", ".log", ".json", ".py", ".yaml", ".yml"}


def _bounded_bytes(path):
    with path.open("rb") as handle:
        data = handle.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Bitte eine Datei mit höchstens 10 MB auswählen.")
    return data


def extract_attachment(path: str) -> dict:
    source = Path(path).resolve(strict=True)
    if not source.is_file() or source.stat().st_size > MAX_BYTES:
        raise ValueError("Bitte eine Datei mit höchstens 10 MB auswählen.")
    suffix = source.suffix.casefold()
    if suffix not in TEXT_SUFFIXES | {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
        raise ValueError("Unterstützt werden Textdateien, PDFs und Screenshots.")
    data = _bounded_bytes(source)
    fingerprint = hashlib.sha256(data).hexdigest()
    if suffix in TEXT_SUFFIXES:
        body = data.decode("utf-8-sig")
        kind = "text"
    elif suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("Bitte das PDF zuerst ohne Passwortschutz bereitstellen.")
        if len(reader.pages) > 100:
            raise ValueError("Bitte ein PDF mit höchstens 100 Seiten auswählen.")
        sections, length = [], 0
        for index, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            section = f"Seite {index + 1}:\n{text}"
            sections.append(section)
            length += len(section)
            if length > MAX_TEXT:
                break
        body, kind = "\n\n".join(sections), "pdf"
        if not any(section.split("\n", 1)[-1].strip() for section in sections):
            raise ValueError("Dieses PDF enthält keinen lesbaren Text. Bitte die Seite als Screenshot auswählen.")
    elif suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
        if os.name != "nt":
            raise ValueError("Screenshot-Texterkennung benötigt Windows OCR.")
        powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-File",
                                 str(Path(__file__).with_name("windows_ocr.ps1")), "-ImagePath", str(source)],
                                capture_output=True, timeout=30, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise ValueError("Screenshot konnte nicht gelesen werden. Bitte Windows-OCR-Sprachen und Bildgröße prüfen.")
        body, kind = json.loads(result.stdout)["text"], "screenshot"
    else:
        raise ValueError("Unterstützt werden Textdateien, PDFs und Screenshots.")
    if not body.strip():
        raise ValueError("Die Datei enthält keinen erkennbaren Text.")
    truncated = len(body) > MAX_TEXT
    if hashlib.sha256(_bounded_bytes(source)).hexdigest() != fingerprint:
        raise ValueError("Die Datei wurde während des Lesens geändert. Bitte erneut einlesen.")
    return {"id": uuid.uuid4().hex, "title": source.name[:160], "body": body[:MAX_TEXT],
            "source": kind, "truncated": truncated, "local_path": str(source), "fingerprint": fingerprint,
            "loaded_at": datetime.now(UTC).isoformat()}


def attachment_changed(document):
    path = document.get("local_path")
    if not path:
        return False
    try:
        source = Path(path)
        return source.stat().st_size > MAX_BYTES or hashlib.sha256(_bounded_bytes(source)).hexdigest() != document.get("fingerprint")
    except (OSError, ValueError):
        return True
