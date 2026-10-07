# Abnahme: Tagesplanung, Schritte, Ergebnisprüfung, Offline und Export

Stand: 7. Oktober 2026. Diese Seite unterscheidet implementierte Funktionen,
automatisierte Grenzen, lokale Windows-Prüfung und laufendes Backend.

| Anforderung | Umsetzung und maßgeblicher Nachweis |
| --- | --- |
| Dauer, Fristen, freie Zeitfenster, Pausen | `day_planner.py`; Tests prüfen Blöcke innerhalb freier Fenster, Priorität nach Frist, Pausen, Restdauer und ausgeschlossene feste Termine. |
| Vorschau vor Planübernahme | `TaskPlanningDialog`; Oberflächentest prüft fehlende Speicherung vor ausdrücklicher Übernahme und ungültige Vorschau nach Eingabeänderungen. |
| Große Aufgabe in sinnvolle Schritte | Modell-Endpunkt `/v1/task-items/decompose`; validierte 2–12 Schritte, bearbeitbare Tabelle, atomare lokale Vormerkung und geordnete Voraussetzungen. API-Test prüft, dass ein Vorschlag keine Aufgabe anlegt. |
| Datei wirklich gespeichert / verändert | Reale temporäre Datei, Ausgangshash, gespeicherte Änderung und erwarteter Text. Unveränderter Inhalt, fehlende Ausgangsfassung und Binärinhalt werden passend abgegrenzt. |
| Änderung im ausgewählten Fenster prüfen | Tatsächliche Windows-UIA-Prüfung eines eigenen Fensters: vollständige Ausgangsfassung, Schalter von ausgeschaltet zu eingeschaltet, neu erwarteter Zustand erkannt, Passwortfeld ausgeschlossen. Schon vorher sichtbare Texte bestätigen keine neue Änderung. Dauerhafte Speicherung wird nicht behauptet. |
| Projekte und Karten ohne Backend nutzen | Vorhandene lokale Speicher; Projektoperation mit kontrolliertem Verbindungsabbruch lädt Dokumente und Schritt lokal, explizites Verbinden wird danach geprüft. Lernkarten bleiben im bisherigen lokalen Speicher. |
| Offline bearbeiten und später Vorschau abgleichen | Persistente Vormerkungen über Neustart; bloßes Laden sendet nichts. Konflikte, Änderungen nach Vorschau, verlorene Antwort, wiederholte Anlage und Teilübernahme sind getestet. Backend-Update verwendet atomaren Versionsvergleich. |
| Markdown mit Aufgaben, Quellen und Fortschritt | Ausgewählter Projektstand, Aufgaben-Checkboxen, optionale quellenbezogene Karten, vollständige Vorschau; realer UTF-8-Dateirundlauf und wörtliche Quellen werden geprüft. HTML und Transklusionen bleiben Text. |

Die Benutzeranleitung steht in [planning-offline-results.md](planning-offline-results.md).

## Laufzeitgrenzen

Die Windows-Prüfung liest ein eigenes kontrolliertes Fenster, nicht beliebige
Anwendungen. Manche Programme bieten keine verwertbaren Beschriftungen; diese
Fälle bleiben unklar. Eine sichtbare Meldung beweist keine dauerhafte Einstellung.
Dateiprüfung unterstützt höchstens 16 MB und Textstellen in UTF-8-Dateien.
Kein physischer Mikrofontest gehört zu diesen fünf Erweiterungen.

Offline-Fehlerpfade sind kontrolliert und mit isolierten lokalen Daten geprüft.
Die produktive Backend-Installation wird dafür nicht heruntergefahren. Projekte
und Karten werden lokal genutzt; Modellvorschläge brauchen eine Verbindung.
Tagesplanung verwendet manuell angegebene freie Zeitfenster und keine externe
Kalenderanbindung. Übernahme speichert den Plan, führt ihn nicht automatisch aus.

Ein gesunder Docker-Container bedeutet nicht vollständige Phase-0-Abnahme. Die
laufende API meldet gegenwärtig eine fehlende Windows-Betriebsprüfung und bewusst
deaktivierte Netzwerkfähigkeiten. Die neuen lokalen Modell- und Dialogfunktionen
werden deshalb direkt geprüft; diese bestehenden Abnahmegrenzen bleiben sichtbar.
