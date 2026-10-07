# Ergebnisprüfung, Korrekturen und Fensterhilfe

Diese Erweiterungen ergänzen [Gespräche und Dokumente](dialog-improvements.md)
in der nativen Windows-Oberfläche. Desktop und API müssen den neuen Stand
verwenden; das API-Image wurde neu gebaut. Ein kompletter produktiver Stack
wurde dabei nicht automatisch gestartet.

## Programmstarts überprüfen

Nach „Öffne Firefox“ prüft Mica ein sichtbares, nicht minimiertes Fenster des
passenden Programmprozesses. Ein erfolgreicher Startaufruf allein reicht nicht
für „Firefox geöffnet“. Die Prüfung läuft bis zu zwölf Sekunden. Eine bereits
geöffnete passende Anwendung zählt ebenfalls; Mica behauptet damit nicht,
ein zusätzliches neues Fenster erzeugt zu haben. Fenstertitel allein genügen
nicht als Nachweis. Explorer-Desktop und Taskleiste zählen nicht als Ordnerfenster.

Die Prüfung sitzt sowohl im Windows-Aktionsadapter als auch vor der kurzen
Desktop-Bestätigung. Ohne bestätigtes Fenster gibt es einen konkreten Hinweis;
ein schon übergebener Start wird nicht automatisch wiederholt. Bestehende
Windows-Freigaben, Preflight und App-Allowlist bleiben erforderlich. Unbekannte
Prozesszuordnungen können deshalb einen unbestätigten Start melden.

## Laufenden Timer korrigieren

„Timer für fünf Minuten“ → „Nein, zehn Minuten statt fünf“ ersetzt den zuletzt
gestarteten, noch laufenden Timer durch zehn Minuten **ab der Korrektur**.
Die genannte alte Dauer muss zu diesem Timer passen. Bei einer abweichenden
Dauer oder ohne laufenden Timer wird nichts geändert. Andere Timer bleiben
erhalten. Die Korrektur funktioniert mit Text und Sprache ohne Sprachmodell.
Auch Sekunden und Stunden sowie Ziffern werden unterstützt. Gespeicherte
Endzeiten erhalten Timer inzwischen über Neustarts; siehe
[Arbeitsstände und Tageshilfe](productivity-extensions.md).

## Geänderte Dokumente neu einlesen

Ausgewählte lokale Dateien werden ungefähr alle drei Sekunden auf Änderungen
geprüft. Inhaltshashes erkennen auch Änderungen mit gleichbleibender Dateigröße.
Der Knopf **Dateien** und die betroffene Zeile zeigen **Geändert**. **Neu einlesen**
übernimmt ausdrücklich den aktuellen Inhalt; bis dahin bleibt die bisherige
Version im Gespräch. Fehlende oder unlesbare Dateien liefern einen Hinweis.
Das Original wird nicht verändert.

Nach erfolgreichem Einlesen werden die Gesprächsbezüge aktualisiert und alte
kurzfristige Zitate entfernt. Dateiwege und Prüfsummen verbleiben lokal und
werden nicht als Gesprächskontext übertragen. Einzelne Fensteraufnahmen werden
nicht als veränderliche Dateien überwacht.

## Arbeitsmodus festlegen und wiederholen

Benannte Abläufe mit eigenen Dokumenten ergänzen inzwischen den ursprünglichen
Arbeitsmodus; siehe [Eigene benannte Abläufe](productivity-extensions.md#eigene-benannte-abläufe).

Über **Abläufe** neben dem Eingabefeld werden die Programme, die Dauer des
Fokus-Timers und die Mica-Ruhezeit festgelegt. **Diesen Ablauf aktivieren** und
**Speichern** machen die Auswahl verfügbar. Die Konfiguration liegt lokal in
`.mica-data/work-routine.json`; ohne aktivierte Konfiguration startet nichts.
Bis zu acht unterschiedliche Programme sind möglich.

„Arbeitsmodus starten“ führt genau diesen gespeicherten Ablauf aus: ausgewählte
Programme der Reihe nach öffnen und ihre Fenster prüfen, anschließend den
Fokus-Timer starten und die Ruhezeit aktivieren. Jeder Programmstart durchläuft
die normalen Aktionsfreigaben. Bei fehlender Freigabe, Fehler oder Abbruch hält
der Ablauf an; bereits geöffnete Programme bleiben geöffnet. Timer und Ruhezeit
starten erst nach bestätigten Programmstarts. Der Sprachkanal wartet für einen
Arbeitsablauf bis zu fünf Minuten auf dessen tatsächliche Ergebnisbestätigung.

Während der **Mica-Ruhezeit** hört Mica nicht auf das Aktivierungswort und zeigt
keine Timer-Popups. Abläufe erscheinen weiter im Verlauf; Text und Sprechtaste
bleiben nutzbar. Der Knopf zeigt **Abläufe · Ruhezeit**. Die Ruhezeit endet
automatisch oder mit „Ruhemodus beenden“. Sie verändert nicht die Windows-
Benachrichtigungseinstellungen oder unabhängig laufende Backend-Automationen.
Programme und Fokus-Timer werden beim Beenden der Ruhezeit nicht geschlossen.

## Ein Fenster gezielt lesen

Zuerst das gewünschte Fenster verwenden, dann in Mica **Fensterhilfe** anklicken.
Mica merkt sich dafür nur die Metadaten des zuletzt aktiven fremden Fensters;
es erfolgt keine fortlaufende Bildschirmaufnahme. Ein über fünf Minuten alter
Bezug verlangt, das Fenster erneut zu aktivieren.

Eine einzelne Aufnahme erscheint als Vorschau mit dem Fenstertitel. Erst
**Als Kontext verwenden** erkennt ihren Text lokal mit Windows OCR. Danach
erscheint sie als auswählbarer Kontext unter **Dateien**. Bei leerem Eingabefeld
wird eine bearbeitbare Frage zur Fehlermeldung vorgeschlagen; sie wird nicht
automatisch gesendet. Text- oder Sprachfragen verwenden den ausgewählten Inhalt.

Aufnahme und OCR laufen außerhalb des UI-Threads. Die Aufnahme hat ein
achtsekündiges Zeitlimit; temporäre Bilddateien werden nach dem Lesen entfernt.
Geschlossene, minimierte, zu große oder geschützte Fenster können nicht gelesen
werden. Die Hilfe verwendet erkannten Text, keine allgemeine Bildanalyse.
Eine Erklärung benötigt das gewählte Sprachmodell. Nur extrahierter Text
gelangt zum Core; die bestehenden Freigaben für privaten Cloudkontext gelten.

## Prüfung am 2026-10-05

Ein Gesamtlauf bestand mit 719 Tests und 79 Untertests. Neuere Änderungen wurden
zusätzlich mit 77 erfolgreichen Tests gezielt geprüft; zwei Backend-Tests bestanden im tatsächlichen
API-Image. Einzelheiten und die Zuordnung zu allen fünf Anforderungen stehen
im [Prüfnachweis](../artifacts/daily-assistance/verification.json).

Die echte Windows-Fensterprüfung und Aufnahme wurden mit einem kontrollierten
Testfenster ausgeführt. Windows OCR erkannte dessen Docker-Fehlermeldung.
Dabei wurden keine Inhalte fremder Nutzerfenster aufgenommen.
[Windows-Laufnachweis](../artifacts/daily-assistance/windows-runtime.json).

Synthetische deutsche Sprache „Nein, zehn Minuten statt fünf“ durchlief den
echten lokalen Redux-Dienst, änderte den realen Desktop-Timer von 300 auf 600
Sekunden und erzeugte anschließend eine echte lokale Sprachbestätigung.
Das Sprachmodell wurde nicht aufgerufen.
[Sprachlauf](../artifacts/daily-assistance/voice-runtime.json).

Die sichtbaren Dialoge wurden geprüft:
[Arbeitsmodus](../artifacts/daily-assistance/routine-dialog.png),
[Fenstervorschau](../artifacts/daily-assistance/window-preview.png) und
[geänderte Datei](../artifacts/daily-assistance/changed-document.png).
Die [Desktop-Bedienelemente](../artifacts/daily-assistance/desktop-controls.png)
wurden zusätzlich bei normaler und minimaler Fenstergröße geprüft.
Physisches Mikrofon und Lautsprecher, einzelne installierte Drittprogramme
unter produktiven Freigaben sowie die Qualität freier Erklärungen bleiben
separate Alltags- und Geräteprüfungen.
