# MICA Improvements – Arbeitsstand

Auftrag: kontinuierliche praktische Verbesserungen bis **11.10.2026 09:00 Europe/Vienna**.
Branch: `MICA-Improvements`; Basis beim Start: `e0c2133`.
Goal bleibt bis zum geprüften Abschluss aktiv.

## Organisation

- Heartbeat-ID: `mica-verbesserungen-bis-09-uhr`, Prüfung jede Minute in diesem
  Chat; Statusmails nur alle 20 Minuten nach gespeichertem Versandzeitpunkt.
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
- Authentifizierte neue Mail-Instruktion am 11.10. um 00:27: Jira bis zum
  Nachmittag zurückstellen. In dieser Nacht keine weitere Jira-Anmeldung,
  OAuth- oder Integrationsarbeit; veröffentlichten Stand bewahren. Jira-Zugang
  ist damit keine Voraussetzung für die übrige Nachtarbeit.

## Erster Zyklus: 10 von 10 Features lokal implementiert

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

### 2. Aufgaben nach Dringlichkeit und Fälligkeit ordnen

- Aufgabenübersicht zeigt Priorität und Termin in Wiener Zeit, markiert
  überfällige offene Aufgaben und bietet Filter für heute/überfällig/hohe Priorität.
- Sortierung nach Dringlichkeit, Fälligkeit oder Titel; ursprüngliche Reihenfolge
  bleibt auswählbar. Ungeklärte Ausführungen stehen bei Dringlichkeit zuerst.
- Selektion bleibt an Aufgaben-ID gebunden; Statusaktionen greifen auch nach
  Umsortierung auf die richtige Aufgabe. Abgeschlossene Aufgaben gelten nicht als
  überfällig. Ungültige Termine werden sichtbar, nicht still umgedeutet.

### 3. Sichtbare Aufgaben als Markdown exportieren

- Exportknopf in der Aufgabenübersicht speichert genau den gefilterten/sortierten
  Stand lokal. Veralteter Backend-Stand wird im Dokument kenntlich gemacht.
- Keine Aktionsparameter oder Ausführungsergebnisse; Text wird Markdown-sicher
  maskiert. Ungeklärte Ergebnisse bleiben als Hinweis sichtbar.
- Atomisches Speichern; bei Fehler bleibt vorhandene Datei unverändert.

### 4. Einheiten lokal und ohne Sprachmodell umrechnen

- Chatbefehle wie `2,5 kg in gramm`, `12 zoll in cm`, `32 fahrenheit in celsius`.
- Länge, Masse, Volumen, Fläche, Zeit und Temperatur; Dezimalkomma, exakte
  definierte Faktoren und kontrollierte Ergebnisdarstellung.
- Kanonische Desktop-UI kann Umrechnungen auch offline und ohne Speicherung
  beantworten. Backend-Chat beantwortet dieselben Befehle direkt für alle Clients.
- Keine Modell-/Netzwerkanfrage für die Berechnung, kein Ausdrucks-Eval. Gemischte
  Dimensionen und Temperaturen unter dem absoluten Nullpunkt erzeugen klare Fehler.
- Neue Backend-Grammatik braucht für den bereits laufenden API-Dienst einen
  Neubau/Neustart. Bisher Source-/Test-Beleg, keine Aktualisierung des laufenden Dienstes.

### Checkpoints und Prüfstand

### 5. Dokumentinfos und Suche in ausgewählten Texten

- Unter Dateien → Infos / Suche: Wörter, Zeichen, Zeichen ohne Leerraum,
  Absätze und ausdrücklich geschätzte Lesedauer für bereits eingelesene Texte.
- Literaltextsuche über alle ausgewählten Dokumente, mit Textzeilen und
  begrenzten Ausschnitten. Unausgewählte Dateien werden nicht einbezogen.
- Gekürzte/geänderte Textversionen werden kenntlich gemacht. Keine neue
  Dateilese-, Backend-, Modell- oder Cloud-Anfrage für die Prüfung.
- `Wörter zählen`, `Zeichen zählen` und `Dokumentinfos` sind in der kanonischen
  Desktop-UI auch offline und ohne Speicherung erreichbar.
- Fünf zusätzliche Tests für Zählung, wörtliche Suche, Grenzen, sichtbare
  Oberfläche und den tatsächlichen Offline-Desktop-Pfad bestanden. Zusammen mit
  angrenzenden neuen Funktionen: 57 Tests und Ruff-Prüfung bestanden.

### 6. Jira-Vorgänge als lokale Aufgaben übernehmen

- Nach Lesen eines einzelnen Vorgangs bietet die Jira-Seite einen lokalen
  Aufgabenimport mit vollständiger Vorschau und Bestätigung an.
- Quelle/Website, Vorgangsnummer, Titel und Text werden übernommen, keine
  Jira-Schreibaktion. Status wird offen, Frist bleibt leer; die anfängliche
  30-Minuten-Dauer ist als anpassbarer Platzhalter im Dialog sichtbar.
- Feste Identität aus Website/Vorgangsnummer verhindert doppelte Übernahmen.
  Bereits vorhandene lokale Änderungen werden atomisch erhalten.
- Im Modus ohne Speicherung wird der Import abgelehnt. Wechsel von Vorgangsnummer
  oder Website verwirft die Importvorschau. Text und ADF-Beschreibung unterstützt,
  unbekannte/uneindeutige Antworten führen nicht zu einem geratenen Import.
- Drei neue Tests sowie angrenzende Jira-, Dokument-, Aufgaben- und Offline-
  Planungsprüfungen bestanden: **80 Tests**, Ruff und Diff-Prüfung bestanden.

### Checkpoints und Prüfstand (Fortsetzung)

### 8. Lokaler Rechner und Prozentfragen

- Chat/Offline-Desktop beantwortet `rechne (5 + 3) * 2`, `0,1 + 0,2` und
  `Was sind 15 Prozent von 80` über eine feste Grammatik mit Dezimalarithmetik.
- Keine Modell-/Netzwerkanfrage oder Codeauswertung. Nur Grundrechenarten und
  Klammern; Zahl-/Größen-/Verschachtelungsgrenzen, verständliche Fehler bei null.
- Desktop ohne Speicherung sowie echter FastAPI-Chatpfad für alle Clients geprüft.
- 73 Tests mit Rechner, Checklisten, Umrechnung, Dialogen und Dokumentinfos bestanden.

### 9. Lokaler Kennwortgenerator ohne Chatprotokoll

- Unter MICA im Alltag → Kennwort: 12–128 Zeichen, standardmäßig 20,
  optionale Sonderzeichen, Zufall aus `secrets`/OS, maskierte Anzeige.
- Keine Speicherung in Chat, Dateien oder Backend. Kopieren nur auf Klick.
- Anzeige und die noch unveränderte eigene Zwischenablagekopie werden nach
  60 Sekunden oder Verlassen der Seite entfernt. Fremder neuer Clipboard-Text
  bleibt erhalten; Windows-Clipboard-Verlauf wird ausdrücklich nicht als gelöscht behauptet.
- Zwei neue Tests sowie angrenzende UI-/Rechner-/Listenprüfungen: 41 bestanden.
- Quelle: https://docs.python.org/3/library/secrets.html

### 7. Lokale Einkaufs-, Pack- und Checklisten

- Unter MICA im Alltag → Listen: benannte Listen erstellen/umbenennen,
  Einträge hinzufügen, abhaken/wieder öffnen und nach Bestätigung entfernen.
- Listen liegen ausschließlich im lokalen Datenbereich und überstehen Neustarts.
  Keine externe Ausführung, automatische Bestellung oder Versandaktion.
- Prozesssperre, atomisches Schreiben und Revision verhindern überschreibende
  Änderungen durch veraltete Fenster. Duplikate werden sichtbar abgelehnt.
- Im Modus ohne Speicherung wird keine Änderung übernommen. Beschädigter
  gespeicherter Stand wird nicht still ersetzt.
- Vier neue Persistenz-/Fehler-/UI-Tests, zusammen mit angrenzenden Seiten
  **32 Tests bestanden**; Ruff und Diff-Prüfung bestanden.

- Erster GitHub-Checkpoint: `c2cb11a`, Jira-Implementierung.
- Weitere veröffentlichte Checkpoints: `3bdac36` (Aufgaben/Export/Umrechnung),
  `0b498b9` (Dokumentinfos/Suche), `b724ecc` (Jira-Aufgabenimport).
- Erweiterter kombinierter Prüfstand: **160 bestanden**, dazu ein separat
  hinzugefügter Test der kanonischen Desktop-Umrechnung im Offline-Modus ohne
  Speicherung: **1 bestanden**. Insgesamt 161 unterschiedliche geprüfte Tests.
- Abgedeckt: neue Funktionen, Dialoge, native Befehle, tägliche Operationen,
  Aufgabenübersicht, Credential-Manager-Grenze und Antwortzeitmessung. Der API-Pfad
  der Umrechnung ist über den echten FastAPI-Testclient geprüft.
- Ruff und Git-Diff-Prüfung bestanden. Eine vorhandene Starlette-Testclient-
  DeprecationWarning bleibt; keine fehlgeschlagenen Tests im vollständigen Lauf.
- Der erste erweiterte Lauf hatte vier fehlende Testabhängigkeiten (numpy,
  pypdf, uvicorn); diese waren im erfolgreichen isolierten Wiederholungslauf vorhanden.
- Für den Zehn-Feature-Bugbot-Gate zählen Funktionen 1–10 als lokal implementiert;
  externe Konto-/Hardware-/Live-Dienst-Abnahmen bleiben separat offen.

### 10. Ordner auf große Dateien prüfen

- MICA im Alltag → Dateigrößen: ausgewählten lokalen Ordner im Hintergrund
  durchlaufen, logische Dateigrößen summieren und die größten 20 Dateien anzeigen.
- Nur Metadaten lesen; keine Inhalte öffnen, verschieben oder löschen. Links und
  Windows-Reparse-Punkte überspringen. Abbruch, Eintrags-/Tiefen-/Zeitbudget und
  nicht lesbare Bereiche ergeben sichtbar eine Teilprüfung.
- Drei neue Tests für Inventar, Abbruch/Grenzen, Links und den erreichbaren UI-Pfad.
- Gemeinsamer aktueller Lauf über alle zehn Erweiterungen und angrenzende
  Alltags-, Offline-, API- und Credential-Prüfungen: **231 Tests bestanden**.
  Ruff für die neue Funktion bestanden. Vorhandene Testclient-DeprecationWarning.

## Nächste Auswahl

Prüfe zuerst bestehende Funktionen und aktuellen Bedarf; keine Duplikate oder
isolierten Prototypen als Features zählen. Sinnvolle Kandidaten: bessere
Aufgabenpriorisierung, Projekt-Weiterarbeit, Jira-Ergebnisse als lokale Aufgaben,
eine übersichtliche tägliche Arbeitsansicht und sichere Erinnerungen.
Jede Funktion braucht einen erreichbaren UI-/Chat-Pfad und passende Prüfungen.

## Offene Prüfstufe

Der spezielle Bugbot-Subagent ist in dieser Sitzung nicht als Tool verfügbar.
Nach zehn Features erneut geprüft: kein Bugbot-Werkzeug vorhanden. Der Skill
`review-bugbot` verlangt den echten Reviewer; einen allgemeinen Agenten oder
manuelle Prüfung niemals als Bugbot ausgeben. Keine garantierte Bugfreiheit
behaupten. Gemeldete echte Befunde bearbeiten und erneute Prüfung dokumentieren.
Der nächste Feature-Zyklus beginnt erst nach dieser Prüfstufe. Bis dahin weitere
Verifikation und Stabilisierung des vorhandenen Zyklus; Live-Jira und laufende
Backend-/Desktop-Version weiterhin separat offen.

## Stabilisierung nach dem ersten Zyklus

- Eigener Regressionstest zeigte: ein nach der ersten Auflistung durch einen
  Link ersetzter Unterordner wurde noch betreten. Vor jedem queued Ordner jetzt
  erneute Metadatenprüfung ohne Linkverfolgung. Der vorher fehlschlagende Test
  besteht; zusammen mit angrenzenden Ordner-/Listen-/Kennwort-/Aufgabenprüfungen
  **30 Tests bestanden**, Ruff bestanden.
- Das Dateisystem liefert keinen atomaren Schnappschuss; gleichzeitige externe
  Änderungen können weiterhin eine Teilansicht ergeben. Der Test ist eine eigene
  Verifikation und kein Bugbot-Befund. Die echte Bugbot-Prüfstufe bleibt offen.
- Checklisten zusätzlich mit echtem zweitem Python-Prozess geprüft: Schreiben
  während aktiver Dateisperre wird abgelehnt, nach Freigabe gelingt es wieder.
  Fehler beim atomaren Dateiaustausch erhält den bisherigen Stand und entfernt
  die temporäre Datei. Beide neuen Prüfungen mit Ordner/Kennwort: **12 bestanden**.
- Projektweite Konsistenzprüfung: **376 Python-Dateien**, **150 lokale
  Dokumentationslinks**, **0 Fehler**. Das ist Syntax-/Link-Evidenz und keine
  vollständige Laufzeit- oder Bugbot-Abnahme.
- Korrektur der Ordnerprüfung auf GitHub veröffentlicht: `35f2beb`.
