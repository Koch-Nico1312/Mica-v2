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
| Projekte und Karten ohne Backend nutzen | Vorhandene lokale Speicher; Projektoperation mit kontrolliertem Verbindungsabbruch lädt Dokumente und Schritt lokal, explizites Verbinden wird danach geprüft. Offline-Starter öffnet die kanonische Oberfläche ohne Dienste-/Mikrofonstart; Startfenster bietet nach einem beendeten Fehlschlag eine Offline-Fortsetzung. |
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

## Unabhängige Bug-Prüfung und Korrekturen

Der angeforderte `review-bugbot`-Skill wurde mit einem eigenen Review-Unteragenten
ausgeführt. Der Reviewer untersuchte auch die bereits im aktuellen HEAD gesicherten
Implementierungen. Alle sieben bestätigten Findings wurden korrigiert; die letzte
Nachprüfung fand keine weiteren reproduzierbaren Bugs im geänderten Umfang.

| Priorität | Bestätigter Fehler | Korrektur und Regression |
| --- | --- | --- |
| P1 | Eine ältere Aufgabe außerhalb der begrenzten Liste erscheint fälschlich als fehlend. | Updates und Backend-Übernahme prüfen jede Kennung direkt; nur echte 404 bedeuten fehlend. Test bewahrt eine alte Aufgabe trotz leerer Liste. |
| P1 | Neue Aufgabe überschreitet die Cachegrenze und macht den lokalen Stand unlesbar. | Lesbarer Cache mit höchstens 500 Einträgen, Schutz für Vormerkungen/Voraussetzungen/Struktur, Kapazitätsprüfung vor Remote-Schreiben. Zwei Grenztests prüfen Verdrängung und voll geschützten Cache. |
| P2 | Bearbeiten entfernt Haupt-/Schrittstruktur. | Nur editierbare Planungseinstellungen werden ersetzt; Parent, Schrittnummer und Container bleiben erhalten. |
| P2 | Verwerfen einer Schrittfolge lässt einen leeren Container zurück. | Abhängige Schritte werden geschützt, verworfene Metadaten entfernt und leere Container aufgehoben. |
| P2 | UTC- oder Textnormalisierung erzeugt nach Antwortverlust einen falschen Konflikt. | Gemeinsame kanonische Werte für Vormerkung und Vergleich; verlorene PATCH-Antwort wird ohne erneutes PATCH erkannt. |
| P2 | Aktualisieren verliert ältere Voraussetzungen und Schrittzuordnungen. | Liste und bekannte Aufgaben werden vereinigt, fehlende Listeneinträge direkt gelesen. Ausfälle und konkurrierende Bearbeitung überschreiben den lokalen Stand nicht. |
| P2 | Synchronisieren von B lässt A-Dokumente in der Oberfläche stehen. | Sync übernimmt dieselbe Dokumentauswahl und den nächsten Schritt wie Load. Regression prüft den folgenden Textturn und Fortschritt ausschließlich für B. |

Das Projektfenster bleibt während eines laufenden Vorgangs offen; Escape und
Schließen können die Kontextübernahme nicht unterbrechen. Der Starter-Test prüft
weiterhin den kanonischen Einstieg und nun auch das explizite Offline-Flag, ohne
bei einer fehlgeschlagenen Assertion das gesamte Prozess-Environment auszugeben.

## Abschließende Prüfung

Die vollständige Testsuite des endgültigen Stands bestand am 7. Oktober 2026:
848 Tests und 79 Subtests, keine Fehler, Laufzeit 389,36 Sekunden. Eine bestehende
Starlette-Abkündigungswarnung blieb sichtbar. Die gezielte Prüfung von Planung,
Offline-Verhalten, Projektunterstützung und Starter bestand zusätzlich mit 64 Tests.
Die unabhängige Nachprüfung fand keine weiteren reproduzierbaren Fehler im
geprüften Umfang. Quell- und Dokumentprüfung sowie die Formatprüfung waren fehlerfrei.
