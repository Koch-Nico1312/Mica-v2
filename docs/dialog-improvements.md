# Gespräche, Rückfragen und Dokumente

Die native Mica-Oberfläche verbindet Text und Sprache mit einem gemeinsamen
kurzfristigen Gespräch. Diese Erweiterung ergänzt die
[Spracheinstellungen](voice-improvements.md).

## Zusammenhängende Gespräche

Jede Desktop-Instanz erhält eine eigene Gesprächskennung. Text und
Sprachaufnahmen verwenden dieselbe Kennung; verschiedene Instanzen vermischen
ihren Kontext nicht. Der Kontext enthält die letzten Gesprächsschritte,
ausgewählte Dokumente und die gerade geöffnete Notiz oder Aufgabe.

Beispiele:

- „Öffne meine Notizen“ → gegebenenfalls eine Notiz auswählen → „Such darin nach Docker“.
- „Zeige Aufgabe Docker“ → passende Aufgabe auswählen → „Markiere diese Aufgabe als erledigt“.
- Eine Datei auswählen → eine Frage stellen → per Sprache dazu nachfragen.

Die Dateisuche und Aufgabenbezüge werden vor dem Sprachmodell aufgelöst. Andere
Nachfragen erhalten den bisherigen Gesprächskontext im Modellprompt. Für lange
Dokumente werden zur Frage passende Textausschnitte verwendet; eine vollständige
Analyse beliebig langer Dokumente wird nicht zugesichert.

Der Kontext liegt ausschließlich im Arbeitsspeicher, ist auf 32 gleichzeitige
Gespräche begrenzt und verfällt nach 30 Minuten ohne Nutzung. Der Knopf
**Dateien → Neues Gespräch** löscht die bisherigen Bezüge. Weiterhin angehakte
Dateien werden beim nächsten Turn wieder hinzugefügt. Die normale Option zum
Speichern von Gesprächen bleibt unabhängig davon: gespeicherte Antworten können
wie bisher zitierte Inhalte enthalten. Ausschalten der Gesprächsspeicherung
setzt auch den kurzfristigen Gesprächsverlauf zurück.

## Gezielt nachfragen

Mehrere passende Dokumente oder Aufgaben führen zu einer Auswahl mit Namen und
Nummern. Mica führt vor der Auswahl keine entsprechende Änderung aus.
„Öffne Browser“ fragt nach Edge, Chrome oder Firefox.

Bei „Erinnere mich morgen um acht an Hausaufgaben“ fragt Mica nach 08:00 oder
20:00. „20 Uhr“, „um zwanzig Uhr“ und „abends“ beantworten diese Rückfrage.
Danach wird dieselbe Anfrage mit eindeutiger Uhrzeit fortgeführt. Zeiten
beziehen sich auf Europe/Vienna. „Abbrechen“ verwirft eine offene Rückfrage.
Ein neuer unabhängiger Auftrag ersetzt sie.

Die gezielten Rückfragen decken diese konkreten Fälle ab. Eine allgemeine
Konfidenzerkennung für jede beliebige Modellinterpretation ist nicht enthalten.

## Einfache Befehle ohne Sprachmodell

Eine feste Grammatik erkennt ausdrücklich vom Nutzer gesendete Befehle, zum
Beispiel:

- „Lautstärke auf fünfzig Prozent“, „lauter“, „leiser“.
- „Öffne Editor“, „Öffne Rechner“, „Starte Firefox“.
- „Starte einen Timer für fünf Minuten“, „Timer anzeigen“, „Timer stoppen“.
- Eindeutige Erinnerungen, beispielsweise „Erinnere mich morgen um 20:00 an Hausaufgaben“.

Diese Befehle benötigen keine Modellantwort. Die Parameter müssen erneut zur
ursprünglichen Nutzeranfrage passen; Modellprosa oder beliebige Shell-Kommandos
können keine native Aktion auslösen.

Lautstärke, Programme und Erinnerungen verwenden weiterhin Core, Aktionsdienst,
Windows-Adapter, aktuelle Preflight-Prüfung und die bestehenden Freigaben. Bei
einer fehlenden Freigabe zeigt **Betrieb** die wartende Ausführung; nach Freigabe
kann sie dort fortgesetzt werden. Mica bestätigt erst ein erfolgreiches
Ausführungsergebnis. Das funktioniert bei ausgefallenem Sprachmodell, setzt
aber einen erreichbaren Core und die freigegebenen Windows-Aktionen voraus.

Timer laufen lokal in der geöffneten Desktop-App, unabhängig vom Sprachmodell.
Bis zu acht Timer mit einer Dauer von einer Sekunde bis 24 Stunden sind möglich.
„Timer stoppen“ beendet den zuletzt gestarteten Timer. Ablauf erscheint in der
Antwortkarte und im lokalen Verlauf. Gespeicherte Endzeiten erhalten Timer
über Neustarts; während die App geschlossen ist, erscheinen keine Timer-Popups.
Einzelheiten stehen unter [Timer nach einem Neustart](productivity-extensions.md#timer-nach-einem-neustart).

Im bestehenden Modus ohne Gesprächsspeicherung bleiben Änderungen und native
Aktionsbefehle gesperrt. Esc unterbricht eine Sprachanfrage und verhindert eine
noch nicht übergebene Folgeaktion; bereits an Windows übergebene Aktionen können
noch abschließen. Der bestehende Not-Aus blockiert weitere Aktionsentscheidungen.

## Dateien hineinziehen

Eine Datei auf das Eingabefeld ziehen öffnet **Dateien im Gespräch**. Der Knopf
**Dateien** daneben zeigt die Anzahl ausgewählter Dokumente. Häkchen bestimmen,
welche Inhalte für Text und Sprache verwendet werden. Entfernen löscht die
Datei aus diesem Gespräch und verändert nicht die Originaldatei. Nach einer
Abwahl werden auch möglicherweise daraus entstandene kurzfristige Antworten
aus dem Gesprächskontext entfernt. Änderungen werden vor dem nächsten Textturn
beziehungsweise vor der Sprachverarbeitung synchronisiert.

Unterstützt werden UTF-8-Textdateien, textbasierte PDFs und Screenshots mit
lesbarem Text. Screenshot-Texterkennung nutzt lokal
[Windows OCR](https://learn.microsoft.com/en-us/uwp/api/windows.media.ocr.ocrengine.recognizeasync).
Sie überträgt kein Bild und bietet keine allgemeine Analyse von Fotos oder
Grafiken ohne Text. Passwortgeschützte PDFs und Scans ohne Text liefern einen
konkreten Hinweis; eine gescannte Seite kann als Screenshot gelesen werden.

Grenzen: acht Dateien, jeweils höchstens 10 MB; maximal 32.000 extrahierte
Zeichen pro Datei und 64.000 Zeichen in der Auswahl. Abschneiden wird sichtbar
angezeigt. PDFs dürfen höchstens 100 Seiten enthalten; Windows OCR akzeptiert
hier Bilder bis 4096 × 4096 Pixel. Die Windows-Profilsprache muss OCR unterstützen.
Es werden keine Originaldateien hochgeladen. Der Core erhält nur extrahierten
Text. Cloudanbieter bekommen diesen privaten Gesprächs-/Dateikontext nur mit
der bestehenden ausdrücklichen Freigabe für private Cloudkontexte.

## Länge der Sprachantworten

Unter **Einstellungen → Audio-Geräte → Sprache einrichten** gibt es
**Länge der Sprachantworten**: Kurz, Normal oder Ausführlich. Standard ist Kurz.
Die Einstellung wird gespeichert und gilt ab der nächsten Aufnahme.
Einfachen Aktionen folgen kurze Bestätigungen; bei Erklärungen erhält das
Sprachmodell die passende Längenvorgabe. Sprachaufnahmen reichen ihre
Ergebnisbestätigung erst nach dem lokalen Befehl an die Sprachausgabe weiter.

## Verifikation, 2026-10-05

Die automatisierten Prüfungen decken Gesprächswechsel zwischen Text und Sprache,
Datei- und Aufgabenbezüge, Auswahlrückfragen, gesprochene Uhrzeiten, Abwahl,
Cloudkontextgrenzen, Befehle bei ausgefallenem Modell, Freigaben, Fehler,
Abbruch vor Übergabe, Timerablauf, echtes PDF-Lesen und die sichtbare
Dateiauswahl ab. Der komplette bestehende Testbestand wurde ebenfalls geprüft.

Ergebnis: 700 Tests und 79 Untertests im Gesamtlauf bestanden. Die neueste
gezielte Prüfung bestand mit 47 Tests; zwei Backend-Tests liefen zusätzlich
im API-Image. Repository- und Ruff-Prüfung waren fehlerfrei.
[Prüfnachweis](../artifacts/dialog-improvements/verification.json).

Ein realer Lauf verwendete das neu gebaute API-Docker-Image, den echten lokalen
Redux-Dienst und die lokale Sprachausgabe. Synthetische deutsche Sprache
„Starte einen Timer für eine Sekunde“ wurde erkannt, an den Desktop übergeben
und als lokaler Timer ausgeführt. Die echte Sprachausgabe erzeugte danach die
Bestätigung. Das Sprachmodell war im Test ausdrücklich nicht verfügbar und
wurde nicht aufgerufen. Der Timer löste tatsächlich aus.
[Laufnachweis](../artifacts/dialog-improvements/runtime.json),
[Sprachbestätigung](../artifacts/dialog-improvements/native-command-confirmation.wav).

Die Windows-OCR wurde zusätzlich an einem tatsächlichen Mica-Screenshot geprüft.
Die dargestellten UI-Vorschauen sind
[Dateiauswahl](../artifacts/dialog-improvements/attachments.png) und
[Antwortlänge](../artifacts/dialog-improvements/voice-response-settings.png).
Physisches Mikrofon/Lautsprecher, neue Windows-Aktionsfreigaben und die Qualität
freier Modellnachfragen im Alltag bleiben separat zu prüfen.
