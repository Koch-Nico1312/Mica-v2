# MICA: Lernen, Fähigkeitsentwicklung und begrenzte Reparatur

Der Bereich **Weiterentwicklung** im Windows-Control-Center und in der lokalen PWA verbindet bestätigte
Nutzerkorrekturen, strukturierte Fehlersignale, die Skill-Werkstatt und die
bestehende versionierte Verbesserungspipeline. Modellgewichte werden dabei
nicht trainiert. Neue Fähigkeiten sind isolierte Python-Datenwerkzeuge.

## Nutzerkorrekturen

Unter **Weiterentwicklung → Lernen aus Korrekturen** eine Vorliebe benennen,
ihren gewünschten Wert und Geltungsbereich auswählen und bestätigen.
Die bestehenden lokalen Freigaben müssen dafür entsperrt sein.

Geltungsbereiche sind `global`, `personal`, `technical` und `monitoring`.
Eine modusspezifische Vorliebe überschreibt denselben Schlüssel im globalen
Bereich. Korrekturen ersetzen die aktive Fassung atomar und behalten Herkunft,
Zeit und den Verweis auf die vorherige Fassung. **Vergessen** löscht den ganzen
Verlauf des betreffenden Schlüssels in diesem Bereich. Wiederholte Bestätigung
derselben Vorliebe erzeugt keine neue Fassung.

Text- und Sprachantworten über die Backend-API verwenden die bestätigten
Vorlieben als Datenkontext. Bei einem Cloud-Modell wird dieser Kontext nur mit
dem bestehenden privaten Cloud-Opt-in mitgegeben. Präferenzen verleihen keine
Werkzeugrechte. Die eigenständige Desktop-Offline-Laufzeit verwendet diesen
Backend-Kontext nicht automatisch.

## Fähigkeitslücken

Fehlgeschlagene Ausführungen, ausdrücklich gemeldete Misserfolge und unbekannte
angeforderte Aktionen erzeugen strukturierte Beobachtungen:

| Kategorie | Auslöser | Geeigneter nächster Schritt |
|---|---|---|
| `missing_tool` | Aktion fehlt in der Werkzeugregistrierung | Fähigkeit spezifizieren |
| `broken_tool` | Werkzeugfehler ohne Berechtigungs-/Ausfallsignal | Reproduzieren und Reparatur vorschlagen |
| `missing_permission` | 401/403, PermissionError, fehlende Freigabe | Rechte oder Freigabe prüfen |
| `temporary_outage` | Timeout, 429, 502/503/504, nicht verfügbare Laufzeit | Verfügbarkeit prüfen |

Gleichartige Beobachtungen erhalten eine stabile Signatur und einen Zähler.
Rohe Fehlermeldungen, Zugangsdaten und Tracebacks werden hierfür nicht gespeichert.
Freigaben und Ausfälle sind keine Auslöser für die Erzeugung zusätzlicher Skills.
Die Einordnung basiert auf verfügbaren strukturierten Signalen; sie ist keine
automatische Beweisführung über die genaue Ursache.

## Skill-Werkstatt

1. Eine konkrete Prüfaufgabe mit **3–12 unabhängigen Beispielen** bestätigen.
   Jedes Beispiel enthält `id`, `input` als JSON-Objekt und `expected` als
   erwartetes JSON-Ergebnis. Normale Fälle, Grenzfälle und Fehlerbedingungen
   gehören in dieselbe Prüfaufgabe. Gespeicherte Prüfaufgaben sind unveränderlich.
2. Eine passende beobachtete Fähigkeitslücke, die Prüfaufgabe und einen Namen
   auswählen. **Kandidat erstellen** verwendet den konfigurierten Modellpfad.
   Über die API kann alternativ vorhandener Code als Kandidat eingereicht werden.
3. Der Generator erhält die Aufgabenbeschreibung, bei Reparaturen auch den
   bisherigen Code, jedoch keine Soll-Ergebnisse der unabhängigen Prüfbeispiele.
   Es gibt höchstens zwei Modellaufrufe für die syntaktische Erzeugung und drei
   gespeicherte Kandidaten pro Prüfaufgabe und Entwicklungsart.
4. **Isoliert prüfen** sendet den Kandidaten durch die bestehende, separat
   freigegebene `improvement.shadow`-Ausführung an den Host-Agenten.
5. Erst nach bestandenem Vergleich ist **Geprüfte Version übernehmen** möglich.
   Dieser Schritt braucht seine eigene parametergebundene Freigabe.

Die PWA merkt sich die angeforderte Freigabekennung für den erneuten Versuch.
Nach Bestätigung unter **Freigaben** den ursprünglichen Schritt nochmals starten.
Übernommene Fähigkeiten werden dem Antwortkontext als Werkzeugmetadaten
bekanntgegeben und können im selben Bereich mit **Fähigkeit nutzen** über die
bestehende `improvement.invoke`-Aktion ausgeführt werden. Dabei bleiben Preflight,
Not-Aus und die gesonderte Ausführungsfreigabe bestehen.

## Qualitätsvergleich

Alte und neue Version bearbeiten dieselben eingefrorenen Eingaben jeweils
zweimal in separaten Python-Unterprozessen innerhalb des Containers. Gemessen
werden richtige Soll-Ergebnisse, Ausführungsfehler und Dauer; pro Fall wird der
Median der zwei Läufe berichtet. Kein Ergebnis darf gegenüber einem vorher
korrekten Fall schlechter werden. Alle Kandidatenfälle müssen korrekt sein.

Ein bestandener Vergleich bedeutet, dass die Prüfaufgabe erfüllt wurde. Er ist
keine allgemeine Garantie über unbekannte Eingaben oder schnelleres Verhalten.
Beim erstmaligen Aufbau einer Fähigkeit dient ein ausdrücklich nicht
unterstützender Platzhalter als Baseline; das ist kein gemessener alter Skill.

Diese isolierten Vergleiche tätigen keine Provideraufrufe; ihre Providerkosten
sind daher null. Erzeugungskosten gehören zum bestehenden Betriebsjournal.
Nutzerkorrekturen sind im Testbericht `null`, da der Fixture-Test keine echten
Nutzerreaktionen messen kann. **Alltagsergebnis bestätigen** erfasst pro Revision
und tatsächlicher Aufgabenkennung separat Erfolg, Dauer, Providerkosten in EUR,
Nutzerkorrekturen und Herkunft. Wiederholte Meldung derselben Aufgabe ersetzt die
Beobachtung. Noch unbeobachtete Größen bleiben `null`; sie werden nicht als null
Fehler oder null Korrekturen ausgegeben. Diese Beobachtungen sind bestätigte
Messdaten des Nutzers, keine automatisch verifizierte Rechnung.

## Begrenzte Selbstreparatur

**Aktive Fähigkeit reparieren** erstellt eine getrennte Kopie des aktiven
Code-Artefakts mit sichtbarem Diff. Der Patch darf höchstens 80 geänderte Zeilen
und der gesamte Kandidat höchstens 12.000 Zeichen umfassen. Der isolierte
Vergleich muss mindestens einen Fehler der alten Version reproduzieren, mehr
korrekte Ergebnisse der neuen Version zeigen und alle Prüfbeispiele bestehen.
Eine Reparatur ohne reproduzierten Fehler wird abgelehnt.

Die aktive Version bleibt während Erzeugung und Prüfung erhalten. Änderung der
Baseline zwischen Erzeugung und Übernahme verhindert die Übernahme eines
veralteten Kandidaten. Nach einer Übernahme ist die bisherige versionierte
Rollback-Funktion verfügbar. Diese Reparaturgrenze umfasst erzeugte
Code-Artefakte; Änderungen am MICA-Kern, an Freigaben, Credentials, Hostrechten
oder Sicherheitsregeln werden nicht automatisch übernommen.

## Isolation und Speicherung

Der API-Prozess importiert keinen generierten Code und benötigt keinen
Docker-Socket. Auf dem Host braucht es einen laufenden Docker-Dienst, das lokal
vorhandene Basisimage `python:3.12-alpine` und die bestehende mTLS-Konfiguration
für `improvement.shadow` und `improvement.invoke`.

Der Qualitätscontainer hat kein Netzwerk, keine Host-Mounts, ein schreibgeschütztes
Dateisystem, Benutzer 65534, 256 MiB RAM, eine CPU und ein Prozesslimit. Testfälle
haben Zeitlimits. Prüfdaten und Prüfläufer werden mit SHA-256 im Kandidatenmanifest
gebunden. Kandidaten erlauben keine Imports oder Host-/Interpreterzugriffe.

`MICA_EVOLUTION_DB` wählt die Datenbank; im gemeinsamen Datenverzeichnis liegt
sie als `evolution.sqlite3`. Bei `create_app(data_dir=...)` ist auch dieser Store
pro Anwendung getrennt. Backup/Restore exportiert die sechs strukturierten
Evolutionstabellen als logische JSON-Daten. Das Backupformat archiviert keine
Docker-Images und keinen vollständigen Verbesserungscode-Workspace; diese
bestehenden Betriebsdaten müssen zusätzlich gesichert werden. Wiederhergestellte
Werkstattverweise ohne zugehörige Revision sind keine ausführbaren Fähigkeiten.

## API

- `GET/POST /v1/evolution/preferences`, `DELETE /v1/evolution/preferences/{id}`
- `GET /v1/evolution/gaps`
- `GET/POST /v1/evolution/suites`
- `GET/POST /v1/evolution/workshop`
- `POST /v1/evolution/revisions/{id}/observations`
- Bestehende Endpunkte: `/v1/improvements/{id}/evaluate`, `/promote` und
  `/v1/improvements/{name}/rollback`

Alle Endpunkte verlangen den bestehenden API-Token. Bestätigende Änderungen
verlangen zusätzlich die lokale Freigabesitzung und `X-Mica-Approval-Intent:
confirm`. Modellcode und JSON-Testdaten sind keine Ausführungsfreigabe.
