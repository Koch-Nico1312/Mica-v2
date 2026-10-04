# Phase 4 – technische Abnahme

Stand: 2026-09-19. Phase 4 ist lokal implementiert und standardmäßig deaktiviert.
Sie gilt noch nicht als abgeschlossen: Ein echter ZimaOS-Read-only-Scan, Not-Aus
während eines realen Schritts und der mehrtägige Pilot bleiben physische Gates.

## Implementierter Umfang

- Planweite Risikobewertung mit unveränderlichem SHA-256-Planhash, Pflicht-Dry-Run,
  Standard- und Hartbudgets sowie erneuter Policy-, Not-Aus-, Budget- und
  Idempotenzprüfung vor jedem Schritt.
- Endliche Agentenpläne mit höchstens einem Schritt je Scheduler-Zyklus. Freier
  Code, Shelltext, dynamische Tools und unbekannte Aktionen werden abgewiesen.
- ZimaOS-first Server-Agent über den bestehenden Broker/Host-Agent-Pfad. Ziele
  und Container sind allowlistgebunden; Messungen, 24h-/7d-Trends und Diagnosen
  sind deterministisch. Monitoring-Zeitpläne laufen alle fünf Minuten und enden
  spätestens nach 288 Ausführungen. Bestätigte Diagnosen erzeugen dedupliziert
  eine lokale Aufgabe und optional einen endlichen, erneut zu prüfenden Leseplan.
- Getrennter lokaler Digital Twin. Sichere Quellen sind Aufgaben, Zeitpläne,
  bestätigtes Profil und reine Nutzungsmetriken. Secrets, Roh-Audio, vollständige
  Chats, Audit-Payloads, Brain-, Gesundheits- und Finanzdaten werden nicht
  übernommen. Abgeleitete Fakten brauchen drei unabhängige Beobachtungen und
  mindestens 0,8 Konfidenz; sensible Fakten bleiben bis zur Bestätigung inaktiv.
- Gemeinsame Präsenzzustände für PyQt und PWA sowie eine unabhängige Tagesebene.
  Die PWA nutzt eine leichte lokale Darstellung; die große React-/Three.js-App
  bleibt Phase 5.
- Deduplizierte Prompt-/Config-Vorschläge nach wiederholten Fehlern. Shadow-
  Evaluierung verändert die aktive Revision nicht; Promotion bleibt immer ein
  eigener freigabepflichtiger Endpunkt. Automatische Promotion ist blockiert;
  fehlgeschlagene Kandidaten werden unter Quarantäne gestellt.
- Additive SQLite-Tabellen und ein versionierter JSON-Export des lokalen
  Phase-3-/4-Zustands. Der Restore-Drill baut daraus eine frische SQLite-Datei
  sowie die erlaubten Profil-/Lernfeld-Konfigurationen wieder auf.

## Lokale Nachweise

- `python -m compileall -q desktop backend tests`: bestanden.
- Hauptsuite: 185 Tests bestanden.
- Core-/Deployment-/Voice-/Learning-Suite: 14 Tests bestanden.
- Phase-4-Fokus: 23 Tests innerhalb der Hauptsuite bestanden.
- PWA-JavaScript-Parse, Compose-Vertragsprüfung, isolierter Scheduler-Lauf,
  Audit-Redaktion und Backup/Restore-Drill bestanden.
- Docker CLI ist auf dem Prüf-PC nicht installiert; ein realer Compose-Start
  und der physische ZimaOS-/mTLS-Lauf bleiben daher offen.

## Offene Zielabnahme

1. ZimaOS-Host mit produktiver mTLS-Kette und exakter Ziel-Allowlist verbinden.
2. Endlichen 5-Minuten-Monitor über Neustart fortsetzen und 24h-/7d-Trends prüfen.
3. Einen Plan pausieren, Not-Aus während eines Schritts auslösen und beweisen,
   dass kein weiterer Schritt startet.
4. Twin-Fakten im Alltag erklären, widerrufen und vollständig löschen.
5. Den Pilot mehrere Tage beobachten. Erst danach darf Phase 4 als abgeschlossen
   bezeichnet werden.
