# Selbst-Quellcode-Zugriff — MICA liest ihren eigenen Code und ändert Einstellungen

Modul: `core/self_source.py` · Tool: `self_source` · Tests: `tests/test_self_source.py`

## Was MICA kann

| Aktion | Wirkung |
|---|---|
| `list` | Eigene Dateien auflisten (nur Text-Endungen, ohne `.git`, venvs, Caches) |
| `read` | Eine eigene Datei lesen — **Secrets werden maskiert** (`***gesetzt***`) |
| `search` | Begriff im eigenen Code finden (Datei + Zeile + Auszug, max. 60 Treffer) |
| `settings` | Aktuelle Einstellungen aus `.env`, `.env.example` und `config/*.json` |
| `history` | Protokoll aller eigenen Änderungen (`memory/self-edits/index.jsonl`) |
| `preview_setting` | Diff-Vorschau einer Einstellungsänderung — schreibt nichts |
| `preview_edit` | Diff-Vorschau einer Quelländerung inkl. Syntaxprüfung — schreibt nichts |
| `apply_setting` | Schreibt die Einstellung (Backup + Protokoll + HUD-Bestätigung) |
| `apply_edit` | Schreibt die Quelländerung (zusätzlich `MICA_SELF_EDIT_ENABLED=1`) |

Typischer Ablauf für den Assistenten: **erst `preview_*`, dem Nutzer den Diff
zeigen, dann `apply_*`** — die Ausführung selbst hängt am Bestätigungs-Gate des
HUDs (`core.confirm`), und `undo` stellt den Zustand danach wieder her.

## Sicherheitsleiter

1. **Pfad-Käfig** — es geht nur innerhalb der eigenen Installation; `..`-Ausbrüche
   und virtuelle Umgebungen/Git/Caches werden abgelehnt.
2. **Secret-Maskierung** — Werte mit Secret-Schlüsseln (`*_key`, `*token*`,
   `*secret*`, `*password*`) erscheinen nie im Klartext im Modellkontext.
3. **Nur Literal-Ersetzungen** — Quelländerungen brauchen **genau einen** Treffer
   des Suchtexts; kein Regex, kein Massen-Ersetzen.
4. **Syntaxprüfung vor dem Schreiben** — ungültiges Python wird verworfen.
5. **Backup + Undo** — jede Änderung landet unter `memory/self-edits/` und im
   Undo-Stack; nach dem Schreiben wird bei `.py` noch einmal `py_compile`
   geprüft und im Fehlerfall automatisch zurückgerollt.
6. **Bestätigungspflicht** — ohne gebundenes HUD wird nichts geschrieben
   (fail-closed), auch nicht im Headless-Betrieb.
7. **Quellcode nur mit Flag** — `MICA_SELF_EDIT_ENABLED=1` (Standard aus).
   Einstellungsänderungen in `.env`/`config` bleiben ohne Flag möglich, sind
   aber ebenfalls bestätigungs- und backup-pflichtig.

## Bewusst nicht enthalten

- Kein Ausführen von Code, kein Löschen von Dateien, kein Schreiben außerhalb
  der eigenen Installation.
- Keine Änderungen an Policy-, Freigabe-, Audit- oder Host-Agent-Bereichen —
  diese Grenzen bleiben wie in der übrigen Architektur unangetastet.
- Der isolierte Improvement-Loop (`mica_core`) bleibt der Ort für validierte
  Artefakte; `self_source` ist der direkte, sichtbare Weg für den Nutzer am HUD.

## Verhältnis zu Dream-RSI

`self_source` ist der **manuelle** Kanal (Nutzer fragt, Diff, Bestätigung).
Dream-RSI ist der **automatische** Kanal: Vorschläge entstehen aus
aufgezeichneter Historie, laufen durch Validierung + Shadow-Test und werden
erst nach ausdrücklicher Freigabe aktiv (`docs/dream-rsi.md`).
