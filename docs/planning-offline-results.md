# Tagesplanung, Schritte, Ergebnisprüfung, Offline-Arbeit und Markdown

Stand: 7. Oktober 2026. Diese Erweiterungen gehören zur Oberfläche aus
`desktop/local_main.py`, gestartet über `Start MICA.cmd`.

## Tagesplanung

Mit **Tagesplanung** oder „Plane meinen Tag“ öffnest du Aufgaben, Tagesplan und
Abgleich. Unter **Abgleich** lädt „Aktuelle Aufgaben laden“ den Backend-Stand
lokal, ohne vorgemerkte Änderungen zu senden. Der Zeitpunkt dieses Standes bleibt
sichtbar. Unter **Aufgaben** kannst du bestehende Aufgaben bearbeiten oder neue
anlegen: Titel, Quellen/Beschreibung, geschätzte Minuten, Frist, Status, Priorität
und eine Voraussetzung. **Änderung lokal vormerken** bewahrt diese Eingaben auch
über einen Neustart; erst ein bestätigter Abgleich übernimmt sie ins Backend.

Wähle die Aufgaben über **Planen** aus, gib ein Datum und freie Zeitfenster je
Zeile als `09:00-12:00` an. Feste Termine und belegte Zeiten müssen ausgespart
werden; für einen lesenden ICS-Kalender und spätere Anpassungen siehe
[Flexible Planung](planning-extensions.md). Zeiten verwenden
Europe/Vienna. Die Voreinstellung ist 45 Minuten Fokus und zehn Minuten Pause;
beides ist einstellbar. Dauern sind Schätzungen, keine Messung deiner Leistung.

**Tagesplan vorschlagen** verteilt zuerst früh fällige Aufgaben, dann nach
Priorität, und berücksichtigt Voraussetzungen. Lange Aufgaben können mehrere
Fokusblöcke erhalten. Fristen werden nicht überschritten. Fehlende oder zyklische
Voraussetzungen, Zeitmangel und bereits abgelaufene Fristen lassen Arbeit
**nicht eingeplant**; die Restdauer bleibt sichtbar. Zeitfenster dürfen sich
nicht überschneiden. Höchstens 20 Fenster und 200 Aufgaben werden geplant.

**Geprüften Tagesplan übernehmen** speichert die Vorschau lokal. Änderungen an
den Eingaben erfordern eine neue Vorschau. Der zuletzt übernommene Plan erscheint
beim erneuten Öffnen. Übernahme startet keine Aufgabe, Erinnerung oder Programme.

## Aufgaben in Schritte zerlegen

Wähle eine Aufgabe und **In Schritte zerlegen**, oder schreibe zum Beispiel:
„Zerlege Für die Prüfung lernen in Schritte“.

Das konfigurierte Modell schlägt 2–12 Schritte mit Titel, Beschreibung und
geschätzten Minuten vor. Bei einem Cloudmodell gilt dieselbe Freigabe für privaten
Kontext wie bei Dokumentvorschlägen. Im lokalen Modus bleiben die Inhalte beim
lokalen Modell. Der Vorschlag speichert oder führt keine Aufgabe aus.

Bearbeite die Tabelle und bestätige **Diese Schrittfolge lokal vormerken**.
Die Schritte erhalten Voraussetzungen in ihrer Reihenfolge. Die übergeordnete
Aufgabe bleibt bestehen; sie wird beim Planen nicht standardmäßig zusätzlich
eingeplant und auch nicht automatisch als erledigt markiert. Schrittaufgaben
werden erst nach geprüftem Abgleich im Backend angelegt. Ohne erreichbares Modell
kannst du einzelne Aufgaben und ihre Voraussetzungen weiterhin manuell erstellen.

## Ergebnis prüfen

Mit **Ergebnis prüfen** öffnest du eine rein lesende Prüfung. Für Dateien:

1. Datei auswählen, gegebenenfalls auch eine noch nicht vorhandene Zieldatei.
2. Für einen Änderungsnachweis **Ausgangsfassung merken**.
3. Im zuständigen Programm selbst bearbeiten und speichern.
4. Optional die erwartete Textstelle eingeben und **Gespeicherte Datei prüfen**.

Die Prüfung verwendet Dateiinhalt und SHA-256; ein neuer Zeitstempel allein zählt
nicht als Änderung. Bei aktivem Änderungsnachweis braucht dieselbe Datei eine
Ausgangsfassung. Dateien bis 16 MB sind unterstützt, erwartete Textstellen werden
in UTF-8-Text geprüft. Vorhandensein, Veränderung und erwarteter Inhalt sind
unterschiedliche Nachweise. Fehler beim Lesen und nicht prüfbarer Inhalt ergeben
**Unklar**, fehlende Dateien oder fehlender Text **Nicht bestätigt**.

Für Fenster zuerst das gewünschte andere Fenster aktivieren. Gib die erwartete
sichtbare Meldung ein und wähle **Ausgewähltes Fenster prüfen**. MICA liest einmal
die verfügbaren sichtbaren Beschriftungen und verfügbaren Schalter-/Auswahlzustände
genau dieses Fensters. Zum Beispiel kann `Automatisch speichern (eingeschaltet)`
geprüft werden. Für einen Änderungsnachweis zuerst **Fenster-Ausgangsfassung merken**,
dann im gewünschten Programm ändern, erneut dieses Fenster aktivieren und mit
aktiviertem Änderungsnachweis prüfen. Der erwartete Zustand muss neu hinzugekommen
sein. Ein anderer Fensterbezug oder eine gekürzte Ausgangsfassung ergeben **Unklar**;
schon vorher vorhandene Meldungen bestätigen keine neue Änderung. Es gibt keine
automatische Bildschirmaufnahme, keinen Klick und keine Eingabe; Passwortfelder
bleiben ausgeschlossen. Eine gefundene Meldung bestätigt ihre sichtbare Präsenz,
aber nicht die dauerhafte Speicherung einer Einstellung. Fehlende lesbare
Beschriftungen oder nicht gefundener Text ergeben **Unklar**. Ausgangsfassung und
Prüfbelege bleiben nur im geöffneten Prüfungsfenster.

## Offline weiterarbeiten und später abgleichen

Projektstände und Lernkarten bleiben lokal gespeichert. „Offline weiterarbeiten“
öffnet die vorhandenen Projektstände auch bei ausgefallenem Core. Laden stellt
die ausgewählten Dokumentinhalte und den nächsten Schritt in der Oberfläche
wieder her und kennzeichnet ausdrücklich, dass das Backend-Gespräch noch nicht
verbunden ist. Du kannst den Projektstand lokal bearbeiten und erneut speichern,
Lernkarten wiederholen und Aufgaben lokal vormerken. KI-Antworten und neue
KI-Vorschläge benötigen weiterhin das Backend.

Auch bei geschlossener Oberfläche kannst du offline starten: **Start MICA offline.cmd**
öffnet dieselbe MICA-Oberfläche direkt und startet keine Backend-Dienste. Bei einem
fehlgeschlagenen normalen Start bietet das Startfenster nach Ende des Startversuchs
ebenfalls **Offline weiterarbeiten**. Dieser ausdrückliche Offline-Start führt keinen
Verbindungstest und startet kein Aktivierungswort-Mikrofon.

Zum späteren Verbinden prüfe den gespeicherten Stand im Arbeitsstand-Fenster und
klicke **Lokalen Projektstand mit Gespräch im Backend verbinden**. Die gespeicherte
Aufgabe wird im Backend neu geprüft; gelöschte Aufgaben werden nicht wiederbelebt.
Authentifizierungs-, Zertifikats- und Eingabefehler werden als Fehler behandelt;
Verbindungsabbrüche und vorübergehende Gateway-Ausfälle ermöglichen Offline-Laden.

Aufgaben haben einen separaten **Abgleich**:

1. **Vorgemerkte Änderungen mit Backend vergleichen** liest aktuelle Aufgaben.
2. Wähle eine Zeile: Backend und gewünschter lokaler Stand werden vollständig
   gegenübergestellt. Noch nichts wird gesendet.
3. Hake passende Änderungen an und bestätige **Ausgewählte geprüfte Änderungen
   übernehmen**. Konflikte sind nicht auswählbar und werden nicht überschrieben.
4. Bei einem Konflikt kannst du ausdrücklich den Backend-Stand behalten; die lokale
   Änderung wird verworfen. Ungesendete Änderungen kannst du separat verwerfen.

Wenn eine Aufgabe nach der Vorschau geändert wird, lehnt das Backend die veraltete
Übernahme atomar ab. Verlorene Antworten behalten die Änderung zur erneuten Prüfung;
neue Aufgaben verwenden beständige Anfragekennungen gegen doppelte Anlage. Eine
bereits gesendete, ungeklärte Änderung bleibt bis zum Abgleich unveränderbar.
Erfolgreiche Teilübernahmen bleiben gespeichert, verbleibende Änderungen gehen
nicht verloren. Verbindung oder Laden lösen niemals einen automatischen Abgleich aus.

Die lokale Aufgabenübersicht hält höchstens 500 zuletzt bekannte Aufgaben. Die
Backend-Liste liefert standardmäßig bis 200 Einträge; bekannte Aufgaben und
Voraussetzungen außerhalb dieser Liste werden beim Aktualisieren zusätzlich nach
Kennung geprüft. Fehlende Listeneinträge gelten nicht als gelöscht. Vorgemerkte
Aufgaben, benötigte Voraussetzungen und Schrittstrukturen bleiben geschützt.
Bei Platzbedarf können ältere ungeschützte Cacheeinträge verdrängt werden; ihre
Backend-Aufgaben bleiben bestehen. Ist jeder Platz geschützt, wird ein neuer
Abgleich vor dem Senden abgelehnt. Es ist ein datierter Cache, kein vollständiges
Backup. Bis 200 Änderungen können vorgemerkt werden.

Bearbeiten erhält die Zuordnung zu übergeordneten Aufgaben und die Schrittnummer.
Zum Verwerfen einer Schrittfolge zuerst die letzten Schritte verwerfen; eine
noch benötigte Voraussetzung kann nicht verschwinden. Ohne verbleibende Schritte
wird die Hauptaufgabe wieder standardmäßig zum Planen ausgewählt. Fristen und
Texte werden beim Vormerken genauso wie im Backend normalisiert, damit nach
verlorenen Antworten bereits gespeicherte Änderungen wiedererkannt werden.
Gespeicherte Funktionen benötigen den Modus mit Speicherung.

## Projekt als Markdown exportieren

Unter **Arbeitsstand** wählst du ein gespeichertes Projekt und
**Gespeichertes Projekt als Markdown exportieren**. Die Vorschau enthält:

- „Hier warst du“ und „Nächster Schritt“ samt Zeitpunkt des Projektstandes;
- die von dir angehakten Aufgaben mit Status, Frist und Beschreibung/Quellen;
- die ausgewählten Dokumentinhalte samt Herkunft und Dokumentkennung;
- optional nur Lernkarten, deren Quellen zu diesen Dokumenten gehören.

Aufgabenstand und rein lokale Änderungen sind gekennzeichnet. Nur die gespeicherte
Projektaufgabe und ihre Teilaufgaben sind gegebenenfalls vorgewählt; andere Aufgaben
wählst du selbst aus. **Diese Vorschau als .md speichern** schreibt eine portable
UTF-8-Datei an den gewählten Ort. Sie lässt sich etwa in Obsidian öffnen. Inhalte
werden als Text ausgegeben, eingebettete HTML-Inhalte und Obsidian-Transklusionen
werden nicht aktiviert. Es gibt keinen automatischen Upload und keinen Import.

## Lokale Dateien und Prüfungen

Zusätzlich zu `project-workspaces.json` und `flashcards.json` liegen unter
`.mica-data/` der datierte Aufgabenstand und die Vormerkungen in
`offline-tasks.json`, der ausdrücklich übernommene Plan in `day-plan.json`.
Vorhandene Projekt- und Lernkartenspeicher werden weiterverwendet.

Automatisierte Grenzen prüft `tests/test_planning_offline_results.py`.
`scripts/check_planning_results_core.py` prüft den laufenden Core und echte
Modellvorschläge, ohne Aufgaben zu verändern.
`scripts/check_planning_results_windows.py` prüft sichtbare Windows-Beschriftungen,
echte Dateien und gerenderte Dialoge mit eigenen temporären Testdaten.
Die [Abnahmenachweise](planning-offline-results-acceptance.md) beschreiben den
geprüften Umfang und die Grenzen.
