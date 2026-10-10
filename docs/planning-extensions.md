# Flexible Tagesplanung und Projektfortsetzung

Stand: 8. Oktober 2026. Alle Ergänzungen gehören zur vorhandenen lokalen
MICA-Oberfläche; sie funktionieren auch über **Start MICA offline.cmd**.

## Tagesplan anpassen

Öffne **Tagesplanung**, wähle Aufgaben und verfügbare Zeiten und übernimm zuerst
eine geprüfte Vorschau. Danach kannst du schreiben:

- „Ich habe erst ab 15 Uhr Zeit“
- „Aufgabe Bericht dauert 60 Minuten“
- „Die Aufgabe dauert länger“ (vorher die Aufgabe auswählen; Vorschlag: 15 zusätzliche Minuten)

Die Anfrage öffnet den Plan mit einer Anpassung. **Tagesplan vorschlagen** zeigt
alte und neue Startzeiten, Pausen und nicht passende Restarbeit. Erst **Geprüften
Tagesplan übernehmen** speichert die Änderung. Eine Daueranpassung meint offene
Restarbeit und bleibt für weitere Anpassungen dieses Plans erhalten; sie verändert
nicht automatisch die Aufgabendauer im Backend.

Verpasste Zeitblöcke bleiben offen und werden neu geplant. Ein gerade laufender
Block und ausdrücklich abgeschlossene Blöcke bleiben erhalten. Mit **Gewählten
Arbeitsblock als abgeschlossen merken** hältst du Planfortschritt fest. Das ändert
keinen Aufgabenstatus. Fristen, Voraussetzungen und freie Zeiten bleiben wirksam.
Eine Anpassung gilt für den Tag des gespeicherten Plans. Eine zwischenzeitliche
Änderung durch eine andere Instanz erfordert eine neue Vorschau.

## Projekt mit einem Klick fortsetzen

**Projekt fortsetzen** neben dem Eingabefeld lädt das zuletzt gespeicherte Projekt.
Alternativ: „Projekt alpha fortsetzen“. Ausgewählte Dokumentinhalte, offene Aufgabe,
letzter Arbeitsschritt und nächster Schritt werden gemeinsam wiederhergestellt.
Der letzte Schritt erscheint im Gesprächsprotokoll; der nächste im Eingabefeld.
Keine gespeicherte Aktion wird ausgeführt. Offline erfolgt das Laden lokal; späteres
Verbinden mit dem Backend bleibt eine ausdrückliche Handlung im Arbeitsstand-Fenster.

## Kalenderzeiten einlesen

Wähle unter Tagesplanung **Kalender auswählen** und eine lokale ICS-Datei aus deinem
Kalenderexport. Jede Vorschau liest diese Datei frisch und zieht belegte Termine
vom gewählten Tag ab. Ganztägige Termine, Wiederholungen, Ausnahmen und verschobene
Serientermine werden berücksichtigt; abgesagte oder als frei gekennzeichnete Termine
blockieren keine Zeit. Termine erscheinen als Belegt in der Vorschau.

MICA schreibt weder Termine noch Kalenderdateien und verbindet sich hierbei mit
keinem Konto. Es wird keine Datei automatisch gesucht. Ändert sich die Datei nach
der Vorschau, ist vor Übernahme eine neue Vorschau nötig. Ohne Zeitzone gilt
Europe/Vienna; nicht eindeutige Zeiten werden abgewiesen. Unlesbare Kalender werden
nicht als freie Tage behandelt. Grenzen: 2 MB, 2.000 Termine, höchstens 20 verbleibende
Zeitfenster. Sekündliche, minütliche und stündliche Serien brauchen einen Tagesexport.

Für die Erweiterung sind `icalendar` und `recurring-ical-events` in den normalen
und gesperrten Installationsabhängigkeiten enthalten. Die Wiederholungsverarbeitung
verwendet die [offizielle Bibliotheks-API](https://recurring-ical-events.readthedocs.io/en/v3.8.0/reference/api.html).

## Prüfkriterien an Aufgaben hängen

Wähle unter Aufgaben eine gespeicherte Aufgabe und **Erledigt, wenn …**.
Wähle eine Datei, optional eine erwartete Textstelle und optional einen
Änderungsnachweis. **Kriterium und Ausgangsfassung speichern** merkt den Ausgangszustand.
Für eine noch nicht vorhandene Zieldatei kannst du den Pfad direkt eingeben.

**Gespeichertes Kriterium prüfen** verwendet den vorhandenen Dateinachweis und
zeigt Bestätigt, Nicht bestätigt oder Unklar. Eine erfolgreiche Prüfung erledigt
die Aufgabe nicht. **Nach erneuter Prüfung als erledigt vormerken** liest die Datei
noch einmal und merkt die Änderung nur bei bestätigtem Ergebnis lokal vor.
Erst der Aufgabenabgleich übernimmt sie ins Backend. Neue lokale Aufgaben müssen
zuerst als offen abgeglichen werden, bevor ihr Status geändert werden kann.

Dateiinhalt, nicht nur Zeitstempel, zählt. Es gelten weiterhin 16 MB je Datei und
UTF-8 für erwartete Textstellen. Kriterien und letzter Nachweis bleiben lokal und
sind entfernbar; höchstens 500 Kriterien und 2 MB gespeicherte Prüfdaten.

## Lernen in den Tag aufnehmen

Aktiviere **Fällige und zuletzt schwierige Lernkarten als kurze Lernblöcke einplanen**.
Karten, die bis zum Ende des gewählten Tages fällig sind, und zuletzt mit Schwer
oder Noch einmal bewertete Karten werden nach Quelle gebündelt. Schwierige Karten
kommen zuerst. Eine Karte wird mit etwa zwei Minuten geschätzt; Blöcke enthalten
höchstens sieben Karten und dauern mindestens fünf Minuten.

Die Lernblöcke erscheinen mit den übrigen Aufgaben im Vorschlag; Restarbeit bleibt
sichtbar. Sie erzeugen keine Backend-Aufgaben. Mit **Lernkarten des gewählten Blocks
wiederholen** öffnest du nur dessen Karten, auch wenn eine schwierige Karte erst
später fällig wäre. Antworten werden zunächst verborgen. Erst deine Bewertung
verändert den Wiederholungstermin; das Planen allein verändert keine Karte.

## Nachweise

Die Tests in `tests/test_planning_extensions.py` prüfen alle fünf Anforderungen,
einschließlich fehlender Bestätigung, Kalenderänderungen, mehrfacher Anpassung,
verpasster Blöcke, konkurrierender Aufgabenänderung und tatsächlicher Dateiinhalte.
`scripts/check_planning_extensions_windows.py` prüft reale Qt-Dialoge mit dem
normalen Windows-Interpreter und ausschließlich temporären Projekt-, Karten- und
Aufgabendaten. Bilder und Laufzeitbeleg stehen unter `artifacts/planning-extensions/`.
Die Offline-Projektprüfung ist kein Nachweis einer neuen Cloud-Kalenderverbindung.

| Anforderung | Nachweis am 8. Oktober 2026 |
| --- | --- |
| Flexible Tagesplanung mit Übernahme | Tests prüfen mehrfaches Verlängern, genaue Restdauer, verpasste Blöcke, abgeschlossene Voraussetzungen, laufende Pause und Vorschau ohne Schreibzugriff. Realer Dialog speichert erst bei Übernahme. |
| Projekt mit einem Klick | Test ruft die tatsächliche Oberflächen-Fortsetzung auf und prüft genau einen Ladevorgang, Dokumentauswahl, letzten und nächsten Schritt. Windows-Prüfung lädt diese Daten über die echte lokale Offline-Operation. |
| Kalender lesend berücksichtigen | Echte ICS-Dateien mit Serien, Ausnahmen, Verschiebungen, Ganztag, Überlappung, transparenten und abgesagten Terminen; Dateibytes bleiben unverändert. Dateiänderung nach Vorschau sperrt Übernahme. |
| Aufgaben mit Prüfkriterien | Echte Datei, Ausgangshash, erwarteter Text, gespeicherter Nachweis; bloßes Prüfen erzeugt keine Vormerkung. Erledigen prüft erneut und bewahrt konkurrierende Änderungen. |
| Lernblöcke nach Bedarf | Fälligkeit und letzte Schwierigkeit steuern Auswahl und Reihenfolge. Gezielter Kartendialog zeigt nur die gewählten Karten, verbirgt Antworten und verändert erst bei Bewertung Termine. |

Die laufende HTTPS-API erkannte außerdem alle sechs neuen Befehlsvarianten in
einem eigenen anschließend geleerten Gespräch. Alle neun lokalen Dienste waren
gesund. Die API meldet weiterhin die bestehenden Phase-0-Abnahmegrenzen als
`blocked`; diese Erweiterungen beseitigen weder die fehlende Windows-Betriebsprüfung
noch bewusst deaktivierte Netzwerkfähigkeiten. Der Nachweis steht in
`artifacts/planning-extensions/core-runtime.json`.

Abschließender Gesamtlauf des fertigen Stands: **871 Tests und 79 Subtests
bestanden**, keine Fehler, keine übersprungenen Tests, Laufzeit 354,81 Sekunden.
Eine bestehende Starlette-Abkündigungswarnung blieb sichtbar. Die gezielte
Funktionsprüfung bestand mit 87 Tests. Quellprüfung: 350 Python-Dateien und
148 lokale Dokumentlinks, keine Fehler; Ruff und Formatprüfung bestanden.
