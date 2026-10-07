# Aufgaben, Diktieren und Weiterarbeiten

Diese sechs Ergänzungen bauen auf der [Projektassistenz](project-assistance.md) auf.

## Erinnerungen bedienen

Neue Windows-Erinnerungen und Timer zeigen ein eigenes MICA-Fenster. **Erledigt**
schließt eine einfache Erinnerung; bei einer verknüpften Aufgabe markiert es diese
im Core als abgeschlossen. **10 Minuten später** registriert eine neue dauerhafte
Windows-Zustellung. **Aufgabe öffnen** zeigt den aktuellen Aufgabenstatus, Termin
und Beschreibung einschließlich ihrer Quelle. Ohne verknüpfte Aufgabe heißt der
Knopf **Erinnerung öffnen**.

Die Zustellung läuft auch bei geschlossener Desktopoberfläche, solange Windows
läuft und der Benutzer angemeldet ist. Im geöffneten Desktop hält die MICA-Ruhezeit
die Fenster zurück und zeigt sie danach. Bereits vor dieser Erweiterung erzeugte
Windows-Erinnerungsskripte behalten ihre bisherige Zustellung. Neu angelegte
Erinnerungen verwenden die neuen Schaltflächen. Es handelt sich um ein eigenes
Fenster, nicht um eine Nachricht im Windows-Benachrichtigungscenter.

## Aufgaben aus Unterlagen

Wähle unter **Dateien** deine Unterlagen und drücke **Aufgaben erstellen**, oder
sage **„Mach aus diesem Arbeitsblatt meine Aufgaben für diese Woche.“** Drücke in
der Vorschau **Vorschläge erstellen**. Jeder Vorschlag enthält eine vom Core
überprüfte, wörtliche Textstelle mit Datei und Zeile. Erfundenen oder uneindeutigen
Belegen folgt eine Fehlermeldung statt eines speicherbaren Vorschlags.

Bearbeite Titel und Termine und wähle die gewünschten Zeilen. Termine werden als
ISO-Zeit mit Zeitzone angezeigt, etwa `2026-10-09T16:00:00+02:00`. Ein leeres Feld
bedeutet keine Frist. Erst **Auswahl speichern** legt Aufgaben in der vorhandenen
Aufgabenverwaltung an. Aufgaben mit Termin erhalten eine verknüpfte lokale
Erinnerung. Es sind bis zu 64 Aufgabenerinnerungen mit Terminen innerhalb eines
Jahres möglich. Ein Registrierungsfehler wird ausdrücklich angezeigt; die bereits
gespeicherte Aufgabe bleibt erhalten. Wiederholen derselben Speicheranfrage erzeugt
dank einer Anfragekennung keine zweite Aufgabe. Bei einer geänderten bereits
gespeicherten Anfrage wird auf die Aufgabenübersicht verwiesen.

Die Quellenprüfung belegt die Textstelle, nicht automatisch die Qualität der
Interpretation oder die Richtigkeit eines vorgeschlagenen Termins. Prüfe beides
vor dem Speichern. PDF-Ausschnitte und die bestehende Extraktionsbegrenzung bleiben
sichtbar durch die ausgewählten Dokumente. Im Modus ohne Speicherung kannst du
Vorschläge erstellen; Speichern benötigt den Modus mit Speicherung.

## Routinen im Gespräch

**„Erstelle einen Schulmodus: Unterlagen öffnen, 45 Minuten Fokus und danach
10 Minuten Pause.“** öffnet den vorhandenen Ablaufeditor mit einem Vorschlag.
Dokumente stammen aus der aktuell ausgewählten lokalen Dateiliste. Bekannte
Programme wie **Chrome öffnen** werden vorausgewählt. Weitere Schritte wählst du
im Editor; unerkannte Teile bleiben in der ursprünglichen Anfrage sichtbar und
werden nicht als Aktionen ausgeführt.

Fokus, Ruhezeit, Pause, Dateien und Programme sind bearbeitbar. Ohne genannte
Pausendauer schlägt MICA fünf Minuten vor; null bedeutet keine Pause. **Speichern**
startet noch nichts. **„Starte Ablauf Schulmodus“** startet den gespeicherten
Ablauf. Nach dem Fokus beginnt der Pausentimer, auch über einen Desktopneustart.
Programmstarts laufen weiterhin durch die vorhandenen Freigaben.

## Diktieren mit Korrekturen

Öffne **Textauswahl → Diktieren und korrigieren** oder sage **„Diktiermodus
starten“**. Drücke **Diktieren** für einen Abschnitt von höchstens zehn Sekunden;
**Aufnahme beenden** schickt ihn früher an die lokale Spracherkennung. Die Vorschau
wächst mit jedem Abschnitt und ist von Hand bearbeitbar.

- **„Ersetze den letzten Satz durch …“** ersetzt nur den letzten Satz.
- **„Ersetze den letzten Satz“** erwartet den Ersatz im nächsten Abschnitt.
- **„Mach daraus Stichpunkte“** erstellt eine bearbeitbare Modellvorschau.
- **„Rückgängig“** stellt die vorherige Fassung wieder her.

Andere gesprochene Sätze werden Text; sie führen keine Programme oder Aktionen aus.
Erst **Geprüften Text kopieren zum Einfügen** schreibt die Vorschau in die
Zwischenablage. Du fügst sie anschließend selbst im gewünschten Programm ein.
Audio und Entwurf bleiben ungespeichert. Stummschaltung, Wiederherstellung und
Schließen brechen laufende Aufnahmen ab; verspätete Ergebnisse werden verworfen.
Aktivierungswort und normaler Sprachmodus pausieren während des Diktiermodus.

## Lernkarten wiederholen

Unter **Dateien → Lernkarten erstellen** oder mit **„Lernkarten erstellen“**
erstellt MICA Fragen mit überprüften Quellen. Die Antwort ist die tatsächliche
Textstelle, nicht eine unbelegte Modellantwort. Prüfe und bearbeite die Fragen und
speichere die Auswahl. **Karten wiederholen** beziehungsweise **„Lernkarten
wiederholen“** zeigt die fälligen Karten zunächst ohne Antwort.

Zeige die Antwort mit ihrer Quelle an und bewerte sie: **Noch einmal** setzt zehn
Minuten, **Schwer** mindestens einen Tag, **Gut** verdoppelt das bisherige Intervall
und **Leicht** verdreifacht es bei mindestens vier Tagen. Maximal sind 365 Tage
möglich. Termine und Bewertungen bleiben lokal über Neustarts erhalten.
**Diese Karte vergessen** löscht eine Karte nach Bestätigung. Bis zu 1000 Karten
liegen in `.mica-data/flashcards.json`.

## Am letzten Schritt weiterarbeiten

Im Fenster **Arbeitsstand** kannst du zusätzlich **Hier war ich: letzter
Arbeitsschritt** ausfüllen. Mit **Weitere Gesprächsschritte für dieses Projekt
merken** wird die letzte beantwortete Anfrage als **Zuletzt besprochen** aktualisiert.
MICA behauptet dadurch nicht, dass diese Arbeit bereits erledigt ist. Der nächste
Schritt bleibt deine ausdrücklich gespeicherte Angabe.

Beim nächsten **„Wechsle zu Projekt Schule“** zeigt die Vorschau **Hier warst du**
und **Nächster Schritt** zusammen mit Dateien und offener Aufgabe. Erst **Laden**
stellt den Gesprächsbezug wieder her. Ohne aktivierte Option wird kein
Gesprächsschritt automatisch in den Projektstand übernommen; ältere Fassungen
bleiben erhalten. Gesprächsspeicherung ausschalten stoppt weitere Fortschrittsnotizen.

## Prüfung

[Prüfnachweise und Grenzen](assistance-extensions-acceptance.md) dokumentieren
automatisierte Checks und die Prüfungen mit Windows und dem lokalen Core.
