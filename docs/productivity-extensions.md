# Arbeitsstände, Textauswahl und Tageshilfe

Die sechs Erweiterungen verwenden die vorhandene Windows-Oberfläche
`desktop/local_main.py`. Desktop und API müssen auf demselben Stand sein.

## Arbeitsstand gezielt speichern und laden

**Arbeitsstand** neben dem Eingabefeld öffnet eine Vorschau. Trage den nächsten
Schritt ein und bestätige **Aktuellen Arbeitsstand speichern**. Gespeichert
werden ausschließlich die angehakten Dokumente einschließlich ihrer aktuellen
Textfassung, der Bezug zur geöffneten Aufgabe und der nächste Schritt.
Gesprächsverlauf, wartende Aktionen und Ausführungsfreigaben werden nicht übernommen.

Nach einem Neustart öffnet „Mach dort weiter, wo wir aufgehört haben“ denselben
Dialog. **Gespeicherten Arbeitsstand laden** stellt die Auswahl und den
Aufgabenbezug wieder her; der nächste Schritt erscheint im Eingabefeld und im
Gesprächskontext. Eine Aufgabe wird aus der aktuellen Aufgabenverwaltung gelesen.
Eine gelöschte Aufgabe wird nicht neu erzeugt. Änderungen an Originaldateien
werden angezeigt; Laden verwendet die gespeicherte Fassung, **Dateien → Neu
einlesen** übernimmt ausdrücklich die neue Fassung.

Es gibt einen bewusst gespeicherten Arbeitsstand unter `.mica-data/workspace.json`.
Ersetzen und Löschen erfordern eine sichtbare Bestätigung. Grenzen: acht
Dokumente, insgesamt 64.000 Textzeichen und 2.000 Zeichen für den nächsten Schritt.
Die Datei enthält private Inhalte im Klartext. Ohne Gesprächsspeicherung sind
Speichern und Laden gesperrt; vorhandene Arbeitsstände lassen sich weiterhin
als lokale Datei verwalten. Es erfolgt kein automatisches Laden beim Start.

## Markierten Text bearbeiten

Text im gewünschten Programm markieren und **Strg+Alt+M** drücken. Ist dieses
Kürzel schon belegt, versucht Mica **Strg+Alt+Umschalt+M**. Das tatsächlich
registrierte Kürzel steht im Menü **Textauswahl**. Dort kann es deaktiviert
werden; die Einstellung bleibt über Neustarts erhalten. Sind beide Kürzel
belegt, kann kopierter Text über dasselbe Menü verwendet werden.

Die Auswahl erscheint zuerst in einem bearbeitbaren Vorschaufenster. Wähle
**Erklären**, **Zusammenfassen**, **Übersetzen** oder **Umformulieren** und bei
Übersetzungen eine Zielsprache. Erst **Vorschau erstellen** fordert die
Modellantwort an. **Ergebnis kopieren** übernimmt das Ergebnis ausdrücklich in
die Zwischenablage; Mica ersetzt keinen Text in der ursprünglichen Anwendung.

Windows UI Automation liest bevorzugt die echte Textauswahl. Für Anwendungen
ohne unterstütztes Textmuster gibt es einen Kopierweg: nach Loslassen der
Tasten wird ausschließlich im unveränderten aktiven Fenster Strg+C gesendet.
Die vorherigen Zwischenablageformate werden nach erfolgreichem Kopieren
wiederhergestellt. Ein Fensterwechsel, leere Auswahl, erkannte Passwortfelder
oder mehr als 16.000 Zeichen führen zu einem Hinweis. Geschützte Anwendungen,
Programme mit höheren Rechten oder Anwendungen ohne normalen Kopierweg können
die Auswahl verhindern; hierfür gibt es den manuellen Kopierweg.

Die Modellvorschau verwendet keine Gesprächs- oder Gedächtnisdaten und speichert
keinen Gesprächseintrag. Privater Text darf nur mit dem vorhandenen privaten
Cloud-Opt-in zu einem Cloudanbieter gelangen. Die lokale Alternative benötigt
ein verfügbares Sprachmodell. Ergebnisse sind auf höchstens 4.096 Ausgabetokens
begrenzt und können bei langen Texten unvollständig sein; vor Verwendung prüfen.

## Timer nach einem Neustart

Timer werden beim Start, Ändern, Stoppen und Ablaufen atomar unter
`.mica-data/timers.json` gespeichert. UTC-Endzeiten erhalten die verbleibende
Dauer über App- und Rechnerneustarts hinweg. Schließen hält nur die lokalen
Callbacks an. Beim nächsten Start werden bereits abgelaufene Timer nachgemeldet.
Während die App geschlossen ist, erscheint keine Mica-Timerbenachrichtigung.

Es gelten weiterhin acht gleichzeitige Timer, eine Sekunde bis 24 Stunden und
die Korrektur „Nein, zehn Minuten statt fünf“. Korrigieren beginnt die neue
Dauer ab der Korrektur. Not-Aus löscht die aktiven Timer weiterhin ausdrücklich.
Nur eine Desktop-Instanz darf dieselbe Timerdatei verwalten. Fehlerhafte Dateien
werden nicht stillschweigend überschrieben; Schreibfehler werden angezeigt.
Die Endzeiten beruhen auf der Systemzeit; starke Uhrzeitänderungen können die
Wiederaufnahme beeinflussen.

## Eigene benannte Abläufe

**Abläufe** bietet eine editierbare Namensauswahl. Für **schulmodus**,
**programmieren**, **feierabend** oder einen eigenen Namen werden Programme,
Dokumente, Fokusdauer und Mica-Ruhezeit getrennt gespeichert. Bestätige
**Diesen Ablauf aktivieren** und **Speichern**. Start: „Starte Ablauf Schulmodus“
oder „Schulmodus starten“. „Arbeitsmodus starten“ verwendet den bisherigen
Ablauf `work`. Ältere Konfigurationen werden beim Speichern übernommen.

Die Dokumente werden zuerst lokal geprüft und neu gelesen. Danach werden die
Programme einzeln über die vorhandenen Freigaben gestartet und ihre Fenster
bestätigt. Erst bei Erfolg wird genau die gespeicherte Dokumentauswahl für das
Gespräch übernommen; danach starten Fokus-Timer und Ruhezeit. Ein Ablauf ohne
Dokumente leert die bisherige Gesprächsauswahl. Fehler oder Abbruch halten die
weiteren Schritte an; schon geöffnete Programme bleiben geöffnet.

Grenzen: 20 Abläufe, acht unterschiedliche Programme und acht Dateien pro
Ablauf; die bestehenden Dateigrößen- und Kontextgrenzen gelten weiterhin.
Die Konfiguration liegt unter `.mica-data/work-routine.json`. Die Ruhezeit
betrifft Mica, nicht Windows-Benachrichtigungen oder Backend-Automationen.

## Tagesübersicht auf Zuruf

„Was steht heute an?“ oder „Tagesübersicht“ bündelt heute fällige und
überfällige Aufgaben, weitere unerledigte Aufgaben und anstehende Erinnerungen.
Die Priorisierung berücksichtigt zuerst überfällige Aufgaben, dann heute
fällige Aufgaben und anschließend Priorität sowie Fälligkeit. Daraus entsteht
ein konkreter Vorschlag zum Anfangen. Erledigte und abgebrochene Aufgaben
werden ausgelassen. Das funktioniert ohne Sprachmodell und ohne
Gesprächsspeicherung.

Zeiten beziehen sich auf **Europe/Vienna**. Die API verwendet die lokale
Aufgabenverwaltung und den Scheduler. Der Desktop ergänzt heute registrierte
Windows-Erinnerungen aus dem schon vorhandenen lokalen Erinnerungsregister.
Dieses Register beweist keine tatsächliche Zustellung; die Übersicht kennzeichnet
diese Grenze. Eine deaktivierte Aufgabenverwaltung wird ausdrücklich gemeldet.
Lange Listen werden sichtbar gekürzt, Aktionen werden nicht ausgeführt.

## Vorlieben direkt aus dem Gespräch

„Antworte bei technischen Fragen kürzer“ öffnet einen Vorschlag mit Schlüssel,
Wert und Geltungsbereich. Möglich sind auch „Antworte ausführlicher“,
„Antworte in Stichpunkten“, „Antworte auf Deutsch“ und der Bereich persönliche
Fragen. **Vorliebe dauerhaft speichern** verwendet den bestehenden
Weiterentwicklungs-Endpunkt und seine lokale Freigabe. Falls nötig wird das
Freigabe-Passwort in diesem Dialog eingegeben; es wird nicht mit der Vorliebe
gespeichert. **Verwerfen** verändert nichts.

Bestätigte Vorlieben bleiben unter **Weiterentwicklung → Lernen aus Korrekturen**
sichtbar und löschbar. Derselbe Schlüssel im selben Bereich ersetzt die
vorherige Fassung. Modelltexte, Dokumentinhalte und unbekannte Formulierungen
können keine Vorliebe automatisch speichern. Text und Sprache verwenden
dieselbe feste Befehlserkennung. Ohne Gesprächsspeicherung wird nichts angeboten.

## API und Prüfung

- `GET /v1/dialog/{session_id}/workspace`: aktueller Aufgabenbezug.
- `POST /v1/dialog/workspace/resume`: aktuellen Aufgabenbezug und nächsten Schritt setzen.
- `POST /v1/text/transform`: ausgewählten Text bearbeiten, ausschließlich als Vorschau.
- `GET /v1/day-overview`: lokale Tagesübersicht.
- `POST /v1/evolution/preferences`: vorhandener Endpunkt für bestätigte Vorlieben.

Alle API-Aufrufe behalten die vorhandene Zugriffsauthentifizierung. Programmstarts
und Vorliebenspeicherung verwenden weiterhin ihre bestehenden Freigaben.
Die neuen lokalen Zustandsdateien ersetzen keine vollständige Datensicherung.

Die gezielten Prüfungen stehen in `tests/test_productivity_extensions.py`;
Laufnachweise, sichtbare Dialoge und die abschließende Anforderungsprüfung unter
[Prüfnachweise](../artifacts/productivity-extensions/verification.json).
Der abschließende Gesamtlauf bestand mit **757 Tests und 79 Untertests**.
Die zwei Chunker-Prüfungen bestanden zusätzlich im frisch gebauten API-Image.
Die Windows-Prüfung erkannte die Auswahl eines kontrollierten fremden
Testprozesses über das tatsächlich registrierte globale Kürzel und erhielt die
Zwischenablage. Vier synthetisch gesprochene deutsche Befehle wurden vom echten
lokalen Redux-Dienst erkannt; der lokale TTS-Dienst erzeugte eine echte
Sprachbestätigung. Die Dialoge und alle fünf Werkzeuge wurden auch bei der
minimalen Fenstergröße von 960 × 680 Pixeln auf lesbare Beschriftungen geprüft.
Echte Modellantwortqualität, physisches Mikrofon und Lautsprecher bleiben
gesonderte Geräte- und Alltagsprüfungen.
