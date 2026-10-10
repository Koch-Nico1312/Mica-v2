# MICA-Dokumentation

Stand des Einstiegs: **11.10.2026**. Für den ersten Start beginne mit der
[Projekt-README](../readme.md). Wähle danach die Anleitung für dein konkretes Ziel.
Das Datum jeder Detailseite zeigt, auf welchen Arbeitsstand sich ihre Prüfergebnisse beziehen.

## Schnell zur passenden Anleitung

| Ich möchte … | Hier weiterlesen |
|---|---|
| MICA oder das Backend einrichten | [Projektübersicht](Projekt-Übersicht.md), [Backend-Einrichtung](../backend/README.md) |
| Verbindung, Zertifikate oder Zugang prüfen | [API und LAN-Zugriff](api-access.md), [Betrieb und Diagnose](daily-operations.md) |
| Mikrofon und Sprachbedienung einstellen | [Sprache einrichten](voice-improvements.md), [Parakeet/Whisper](parakeet-redux.md) |
| Mit Dokumenten und Gesprächen arbeiten | [Gespräche und Dokumente](dialog-improvements.md) |
| Rechnen, Listen führen, Dateien oder Aufgaben prüfen | [Neue Alltagshilfen](EVERYDAY_IMPROVEMENTS.md) |
| Den aktuellen Verbesserungs- und Prüfstand sehen | [MICA Improvements](MICA_IMPROVEMENTS_PROGRESS.md) |
| Quellcode sichern oder aktualisieren | [Git und Updates](Git-Vorbereitung.md), [Repository-Pflege](repository-maintenance.md) |

## Bedienung im Alltag

- [Alltagshilfe](daily-assistance.md): Programmstarts prüfen, Timer korrigieren,
  Dateiänderungen erkennen, Arbeitsmodus und gezielte Fensterhilfe nutzen.
- [Neue Alltagshilfen](EVERYDAY_IMPROVEMENTS.md): Aufgabenfilter und Markdown-Export,
  Umrechnung, Rechner, Dokumentinfos/Suche, Listen, Kennwörter und Dateigrößen.
- [Aufgaben, Diktieren und Weiterarbeiten](assistance-extensions.md): Erinnerungen,
  Dokumentaufgaben, Routinen, Diktatkorrekturen, Lernkarten und Projektfortschritt.
- [Tagesplanung, Offline und Ergebnisprüfung](planning-offline-results.md):
  Zeitfenster, Pausen, bearbeitbare Schritte und ausdrücklicher Offline-Abgleich.
- [Flexible Planung und Projektfortsetzung](planning-extensions.md):
  Planänderungen mit Vorschau, Projektfortsetzung, ICS-Kalender und Lernblöcke.
- [Projektassistenz](project-assistance.md): Projektstände, Textbelege,
  Dateivergleiche, Fensterbedienung und Projektgedächtnis.
- [Arbeitsstände und Tageshilfe](productivity-extensions.md): gespeicherte
  Arbeitsstände, Textauswahl, dauerhafte Timer, Abläufe und Tagesübersicht.
- [Aufmerksamkeit und interne Zustände](cognition.md): Gesprächsfokus,
  relevantes Gedächtnis und beobachtbare Antwortfehler.

## Einrichtung und Technik

- [Architektur](Architektur.md): Desktop, Backend, Datenfluss und Berechtigungsgrenzen.
- [Backend-Einrichtung](../backend/README.md): Windows, ZimaOS, Proxmox und Prüfungen.
- [API und LAN-Zugriff](api-access.md): API-Token, Browser-Zugang und Zertifikate.
- [Parakeet Redux STT](parakeet-redux.md): CPU-Erkennung, Docker, Whisper-Alternative
  und Einschränkungen des nativen Windows-Modellpfads.
- [Betrieb und Diagnose](daily-operations.md): Aufgaben, Aktionsverlauf,
  Backups, Wiederherstellung und Backend-Gedächtnis.
- [Jira-MCP](JIRA_MCP.md): bestehende lesende Anbindung und lokaler Aufgabenimport;
  weitere Einrichtung und Kontoabnahme sind bis zum Nachmittag zurückgestellt.
- [Lernen und Weiterentwicklung](evolution.md): bestätigte Vorlieben,
  Fähigkeitslücken, Skill-Werkstatt und begrenzte Artefakt-Reparaturen.
- [Dream-RSI und Laya](dream-rsi.md): optionale Bewertung und Weiterentwicklung.
- [Hindsight](hindsight.md): optionales Gedächtnis, Quellen, Reflexionen und Backups.
- [Repository-Pflege](repository-maintenance.md): Dateien, lokale Checks und sichere Pflege.

## Phasen und Abnahme

**Implementiert** bedeutet, dass der Code und sein Bedienweg vorhanden sind.
**Automatisiert geprüft** nennt die tatsächlich ausgeführten Tests.
**Auf dem Zielgerät bestätigt** braucht Belege von der konkreten Installation,
etwa für Audio, Modelle, Zertifikate oder ein externes Konto.

Die folgenden Seiten dokumentieren Prüfwege und datierte Ergebnisse. Eine
aktivierte Einstellung oder ein historisch grüner Test ersetzt keine aktuelle
Abnahme auf deinem Zielgerät.

- [Phase 0: lokaler Core](phase0-acceptance.md)
- [Phase 1: Sprache](phase1-acceptance.md) und [Sprachrichtlinie](phase1-voice.md)
- [Phase 2: Lernen und Recherche](phase2-acceptance.md) und [Bedienung](phase2-learning.md)
- [Phase 3A: Automatisierung](phase3a-acceptance.md)
- [Phase 4: Planung und Serverbetrieb](phase4-acceptance.md)
- [Phase 4.5: Wahrnehmung und Präsenz](phase4.5-acceptance.md)
- [Backend-Implementierungsbericht](../backend/IMPLEMENTATION_STATUS.md):
  datierter Stand und noch erforderliche Prüfungen auf dem Zielgerät.
- [Architektur-Korrekturen](architecture-remediation.md): sieben Oktober-Befunde,
  Korrekturen und verbleibende Betriebsprüfungen.
- [Hindsight-Pilot vom 30.09.2026](../artifacts/hindsight-pilot/acceptance.md):
  echter Server, Ausfall/Wiederherstellung und begrenzter Qualitätsvergleich.
  Die Standardaktivierung bleibt aus.

## Sicherheit und Änderungshistorie

- [Cloud-Anbieter und private Inhalte](cloud-provider-security.md)
- [Monatliche Sicherheitsprüfung](monthly-security-review.md)
- [Git, Sicherungen und Updates](Git-Vorbereitung.md)
- [Effizienzänderungen und Messungen](code-efficiency.md)
- [Architekturentscheidung: lokaler Core](decisions/0001-phase0-local-core.md)
- [Dream-RSI-Entscheidungen](decisions/20.09.26-100-points-decisions.md),
  [Umsetzung](20.09.26-100-points-implementation.md) und
  [Analyse](decisions/20.09.26-100-points-analysis.md)
- [50-Punkte-Entscheidungen](decisions/20.09.26-50-points-decisions.md) und
  [Umsetzung](20.09.26-50-points-implementation.md)
- [Historische UI-Prüfung](design-qa.md): damalige Bild-/Oberflächenbelege.

## Archivierte Funktionen

Der normale Start verwendet den aktuellen Desktop-/Backend-Pfad. Die folgenden
Seiten beschreiben frühere Laufzeiten oder deren Bestandteile:

- [Archivierter Gemini-Live-Pfad](../legacy/README.md)
- [Historischer Selbstquellcode-Zugriff](self-source-access.md)
- [Erweiterte Agenten](ADVANCED_AGENTS.md)

Für das heutige Verhalten haben aktueller Quellcode und die passende
Bedienungsanleitung Vorrang vor älteren Änderungstagebüchern.
