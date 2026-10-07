"""Explicit, bounded name aliases; never fuzzy-correct an entire utterance."""
from __future__ import annotations
import re
import json


def validate_aliases(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > 32:
        raise ValueError("Maximal 32 Namenskorrekturen sind erlaubt.")
    result, seen = [], set()
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != {"heard", "name"}:
            raise ValueError("Jeder Eintrag braucht gehört und Name.")
        heard, name = entry["heard"], entry["name"]
        if not all(isinstance(v, str) and 1 <= len(v.strip()) <= 80
                   and re.fullmatch(r"[^\W\d_]+(?:[ '\-][^\W\d_]+)*", v.strip(), re.UNICODE)
                   for v in (heard, name)):
            raise ValueError("Namen dürfen nur Buchstaben, Leerzeichen, Apostrophe und Bindestriche enthalten.")
        heard, name = heard.strip(), name.strip()
        if heard.casefold() in seen:
            raise ValueError("Eine gehörte Schreibweise darf nur einmal vorkommen.")
        seen.add(heard.casefold())
        result.append({"heard": heard, "name": name})
    if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > 6000:
        raise ValueError("Das Namenwörterbuch ist zu groß; bitte weniger oder kürzere Namen verwenden.")
    return result


def correct_names(text: str, aliases: list[dict[str, str]]) -> tuple[str, list[str]]:
    changes = []
    # Maika may be a real contact: only correct the assistant's leading address.
    address = re.compile(r"^(?P<greeting>(?:(?:hallo|hey|hi|okay|ok)\s+))Maika(?=[\s,.:!?]|$)", re.I)
    corrected, count = address.subn(lambda match: match["greeting"] + "Mica", text, count=1)
    if count:
        changes.append("Maika → Mica (Anrede)")
    entries = validate_aliases(aliases)
    if not entries:
        return corrected, changes
    mapping = {entry["heard"].casefold(): entry["name"] for entry in entries}
    pattern = re.compile(r"(?<!\w)(?:" + "|".join(
        re.escape(entry["heard"]) for entry in sorted(entries, key=lambda item: len(item["heard"]), reverse=True)
    ) + r")(?!\w)", re.I)

    def replace(match):
        name = mapping[match[0].casefold()]
        if name != match[0]:
            changes.append(f"{match[0]} → {name}")
        return name

    return pattern.sub(replace, corrected), changes
