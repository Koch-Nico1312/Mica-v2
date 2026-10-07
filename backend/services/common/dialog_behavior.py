"""Deterministic references and clarification before model or action dispatch."""
from __future__ import annotations
import re
from fastapi import HTTPException
from backend.services.api.schemas import TaskItemUpdate
from mica_shared.quick_commands import NUMBER_WORDS
from .dialog_sessions import clarify, resolve_choice
from .day_overview import day_overview


def prepare_dialog(runtime, request, state):
    text = request.message.strip()
    normalized = text.casefold().rstrip(".!?")
    if normalized in {'was steht heute an', 'tagesübersicht', 'zeige meine tagesübersicht', 'was muss ich heute machen'}:
        return request, None if request.native_commands else {'state': 'completed', 'reply': day_overview(runtime)}
    selected = resolve_choice(state, text)
    if selected:
        if selected.get("cancelled"):
            return request, {"state": "completed", "reply": "Abgebrochen."}
        if "document" in selected:
            state.focus = selected["document"]
            return request, {"state": "completed", "reply": f"{state.focus['title']} geöffnet.",
                             "document": state.focus}
        if "task" in selected:
            state.focus = selected["task"]
            return request, {"state": "completed", "reply": f"Aufgabe: {state.focus['title']}\n{state.focus.get('body', '')}"}
        request = request.model_copy(update={"message": selected["message"]})
        text, normalized = request.message, request.message.casefold().rstrip(".!?")
    elif state.pending and (re.fullmatch(r"\d{1,2}(?: uhr)?", normalized) or normalized in {"ja", "die erste", "die zweite"}):
        return request, {"state": "clarification_required", "reply": state.pending["question"]}
    else:
        state.pending = None

    if re.fullmatch(r"(?:öffne|starte) (?:den )?browser", normalized):
        choices = [{"label": name, "message": f"Öffne {name}"} for name in ("Edge", "Chrome", "Firefox")]
        return request, clarify(state, text, choices, "Welchen Browser meinst du: 1. Edge, 2. Chrome oder 3. Firefox?")

    # Resolve an ambiguous twelve-hour time before creating any reminder.
    match = re.fullmatch(r"(?:erinnere mich|erinner mich) (heute|morgen|übermorgen) um (\d{1,2}|\w+)(?: uhr)? (?:an|daran,?) (.+)", text.rstrip(".!?"), re.I)
    hour = (int(match[2]) if match[2].isdigit() else NUMBER_WORDS.get(match[2].casefold(), -1)) if match else -1
    if match and 1 <= hour <= 11:
        choices = [{"label": f"{h:02}:00", "aliases": [str(h), f"{h} uhr", f"um {h} uhr", f"um {h:02}:00",
                    *(word + " uhr" for word, number in NUMBER_WORDS.items() if number == h),
                    *("um " + word + " uhr" for word, number in NUMBER_WORDS.items() if number == h),
                    "morgens" if h < 12 else "abends" if h >= 18 else "nachmittags"],
                    "message": f"Erinnere mich {match[1]} um {h:02}:00 an {match[3]}"} for h in (hour, hour + 12)]
        return request, clarify(state, text, choices,
                               f"Meinst du {match[1]} um {hour:02}:00 oder {hour + 12:02}:00? Antworte mit der Uhrzeit.")
    if match and 0 <= hour <= 23:
        return request.model_copy(update={"message": f"Erinnere mich {match[1]} um {hour:02}:00 an {match[3]}"}), None
    if match:
        return request, {"state": "clarification_required", "reply": "Welche Uhrzeit meinst du? Bitte eine Uhrzeit zwischen 00:00 und 23:59 nennen."}

    # A pronoun must refer to selected/opened data, never a guessed disk path.
    search = re.fullmatch(r"(?:such|suche|finde)(?: darin| in (?:der|dieser) (?:datei|notiz|pdf))? nach (.+)", normalized)
    if search and any(term in normalized for term in ("darin", "in der", "in dieser")):
        document = state.focus
        if not document and len(state.documents) == 1:
            document = state.documents[0]
            state.focus = document
        if not document or "body" not in document:
            return request, {"state": "clarification_required", "reply": "In welcher Datei soll ich suchen? Öffne oder wähle zuerst eine Datei."}
        query = search[1].strip('"„“')
        lines = [line.strip() for line in document.get("body", "").splitlines() if query in line.casefold()]
        reply = f"In {document['title']} gefunden:\n" + "\n".join(lines[:12]) if lines else f"„{query}“ habe ich in {document['title']} nicht gefunden."
        return request, {"state": "completed", "reply": reply[:16000], "document_id": document["id"]}

    if normalized in {"erledige diese aufgabe", "markiere diese aufgabe als erledigt", "markiere sie als erledigt"}:
        if not state.focus or not state.focus.get("task_id") or "status" not in state.focus:
            return request, {"state": "clarification_required", "reply": "Welche Aufgabe meinst du? Zeige zuerst eine Aufgabe."}
        if runtime.policy.is_emergency_stopped():
            return request, {"state": "stopped", "reply": "Not-Aus ist aktiv."}
        if not request.remember:
            return request, {"state": "completed", "reply": "Im Modus ohne Speicherung ändere ich keine Aufgaben."}
        updated = runtime.update_task_item(state.focus["task_id"], TaskItemUpdate(status="completed"))
        state.focus["status"] = updated["status"]
        return request, {"state": "completed", "reply": f"Aufgabe „{updated['title']}“ erledigt."}

    tasks = re.fullmatch(r"(?:zeige|öffne)(?: mir)? (?:meine |die )?aufgabe(?:n)?(?: (.+))?", normalized)
    if tasks:
        try:
            records = runtime.list_task_items()["tasks"]
        except HTTPException:
            return request, {"state": "completed", "reply": "Die Aufgabenverwaltung ist noch nicht aktiviert."}
        if tasks[1]:
            records = [item for item in records if tasks[1] in item["title"].casefold()]
        choices = [{"label": task["title"], "task": {"id": task["id"], "task_id": task["id"],
                    "title": task["title"], "status": task["status"], "body": task["description"]}}
                   for task in records[:8]]
        if len(choices) > 1:
            return request, clarify(state, text, choices, "Welche Aufgabe meinst du?\n" + "\n".join(
                f"{i + 1}. {item['label']}" for i, item in enumerate(choices)))
        if choices:
            state.focus = choices[0]["task"]
            return request, {"state": "completed", "reply": f"Aufgabe: {state.focus['title']}\n{state.focus['body']}"}
        return request, {"state": "completed", "reply": "Keine passende Aufgabe gefunden."}

    opening = re.fullmatch(r"(?:öffne|zeige)(?: mir)? (?:meine |die |den |das )?(.+)", normalized)
    if opening:
        query = opening[1].strip('"„“')
        documents = state.documents
        if query in {"notizen", "notiz"}:
            documents = [doc for doc in documents if "notiz" in doc["title"].casefold()]
            if not documents:
                documents = [doc for doc in runtime.brain.documents() if doc.get("kind") == "notes"][:8]
            if not documents:
                return request, {"state": "completed", "reply": "Ich habe keine lokale Notiz gefunden. Wähle zuerst eine Datei für das Gespräch aus."}
        else:
            documents = [doc for doc in documents if query in doc["title"].casefold()]
            if not documents and any(word in query for word in ("notiz", "datei", ".md", ".txt", ".pdf")):
                documents = [doc for doc in runtime.brain.documents()
                             if doc.get("kind") == "notes" and query in doc["title"].casefold()][:8]
        documents = [{"id": doc["id"], "title": doc["title"], "body": doc.get("body", "")[:32000]}
                     for doc in documents]
        if len(documents) > 1:
            choices = [{"label": doc["title"], "document": doc} for doc in documents]
            return request, clarify(state, text, choices, "Welche Datei meinst du?\n" + "\n".join(
                f"{i + 1}. {doc['title']}" for i, doc in enumerate(documents)))
        if documents:
            state.focus = documents[0]
            return request, {"state": "completed", "reply": f"{state.focus['title']} geöffnet.", "document": state.focus}
    return request, None
