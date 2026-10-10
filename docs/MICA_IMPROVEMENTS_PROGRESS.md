# MICA Improvements – Arbeitsstand

Auftrag: kontinuierliche praktische Verbesserungen bis **11.10.2026 09:00 Europe/Vienna**.
Branch: `MICA-Improvements`; Basis beim Start: `e0c2133`.
Goal bleibt bis zum geprüften Abschluss aktiv.

## Organisation

- Heartbeat-ID: `mica-verbesserungen-bis-09-uhr`, alle 20 Minuten in diesem Chat.
- Verifiziertes Gmail-Konto und Status-Empfänger: `kochnico1312@gmail.com`.
- Autorisierter Instruktionsabsender: `kochn8322@gmail.com`.
- Nur neue Mails seit `2026-10-10T22:02:00Z` verarbeiten. Tatsächliche Absender und
  Authentifizierungsheader prüfen; bearbeitete IDs in privatem Laufzeitstand merken.
- Privater Laufzeitstand: `.mica-data/improvement-run/status.json` (nicht committen).
- Erste Startmail erfolgreich gesendet, Message-ID `1a127d8266aa3a83`.
- Vor jedem Arbeitsblock aktuelle Zeit/Nutzungsgrenzen prüfen. Bei >=95% Verbrauch
  eines relevanten Fensters keine Entwicklungsarbeit bis zu dessen Reset. Keine
  Reset-Credits nutzen. Weitere Statusmails nur soweit Konto/Tools nutzbar bleiben.
- Nach 09:00 keine neuen Features beginnen; Änderungen prüfbar abschließen,
  Abschlusscheckpoint pushen, Abschlussmail senden, Heartbeat deaktivieren.
- Checkpoints nur ausgewählte Source-/Test-/Dokumentdateien committen. Keine
  Secrets, Datenbanken, Modelle, privaten Mails oder Laufzeitdaten veröffentlichen.

## Erster Zyklus: 1 von 10 Features lokal implementiert

### 1. Direkte Atlassian-Jira-MCP-Verbindung

- MICA im Alltag → Jira: E-Mail plus eingeschränkter API-Token, Windows Credential
  Manager, Zugang entfernen, gespeicherten Zugang prüfen, Website auswählen.
- Eigene offene Vorgänge per voreingestelltem JQL suchen, JQL ändern, Vorgang lesen.
- Offizieller v2-Endpunkt, MCP-Initialisierung, Session-/Protokollheader, JSON/SSE,
  feste Lesewerkzeugliste, keine automatischen Abfragen, Hintergrundarbeit,
  Antwortlimits, sichere Fehlertexte und reine Textanzeige.
- `docs/JIRA_MCP.md` erklärt Einrichtung und erforderliche Rechte.
- **Validierung:** 33 Tests bestanden (neue MCP/UI-Verträge plus Secure Store und
  bestehende Aufgabenübersicht); Ruff und Git-Diff-Prüfung bestanden.
- **Evidenzgrenze:** mit Testtransport geprüft. Echte Atlassian-Anmeldung ist
  mangels benutzereigener Zugangsdaten noch unbestätigt. Browser-OAuth sowie
  Jira-Schreibaktionen sind noch nicht eingebaut. Diese Ergänzungen dürfen nicht
  als bereits erledigt ausgegeben werden.

## Nächste Auswahl

Prüfe zuerst bestehende Funktionen und aktuellen Bedarf; keine Duplikate oder
isolierten Prototypen als Features zählen. Sinnvolle Kandidaten: bessere
Aufgabenpriorisierung, Projekt-Weiterarbeit, Jira-Ergebnisse als lokale Aufgaben,
eine übersichtliche tägliche Arbeitsansicht und sichere Erinnerungen.
Jede Funktion braucht einen erreichbaren UI-/Chat-Pfad und passende Prüfungen.

## Offene Prüfstufe

Der spezielle Bugbot-Subagent ist in dieser Sitzung nicht als Tool verfügbar.
Nach zehn Features Verfügbarkeit erneut prüfen. Der Skill
`review-bugbot` verlangt den echten Reviewer; einen allgemeinen Agenten oder
manuelle Prüfung niemals als Bugbot ausgeben. Keine garantierte Bugfreiheit
behaupten. Gemeldete echte Befunde bearbeiten und erneute Prüfung dokumentieren.
