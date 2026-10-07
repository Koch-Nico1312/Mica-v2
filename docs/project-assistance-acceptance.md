# Projektassistenz: Prüfung am 2026-10-07

Die sechs angeforderten Erweiterungen sind in der bestehenden Windows-Oberfläche
und der lokalen API angebunden. Dieser Nachweis bezieht sich auf den aktuellen
Quellstand und die unten konkret ausgeführten Prüfungen.

| Erweiterung | Nachweis |
|---|---|
| Mehrere Projektstände | Neustartfähige Speicherung mehrerer Namen, Migration des Einzelstands, drei Fassungen je Projekt, Schreibsperren und Laden der Dokumentauswahl sowie des nächsten Schritts im tatsächlichen Arbeitsstand-Dialog geprüft. Die bestehenden API-Prüfungen bestätigen aktuelle Aufgabenbezüge und Ablehnung gelöschter Aufgaben. |
| Dokumentquellen | Exakte Ausschnitte, Zeilen und PDF-Seitenbereiche, widersprüchliche Beispieldokumente mit gleichem Namen, ungültige beziehungsweise fehlende Modellmarkierungen und private Cloudgrenzen geprüft. Das echte lokale Modell lieferte eine Antwort mit einer gültigen Quelle aus der ausgewählten Prüfnotiz. |
| Dokumentänderungen | Tatsächlich geänderte lokale Datei verglichen; gespeicherte Auswahl blieb erhalten. Dialog fordert die Erklärung erst ausdrücklich an. Das echte lokale Modell erklärte den bekannten Portwechsel der Prüfdatei. |
| Fenster-Bedienelemente | Windows UI Automation erkannte den sichtbaren Button einer eigenen Testanwendung; deren Passwortinhalt wurde ausgeschlossen. Vorschau, Auswahl und OCR-Ausfall mit vorhandenen bestätigten Beschriftungen geprüft. |
| Timer bei geschlossener Oberfläche | Ein echter Windows-Auftrag zeigte nach Beenden der Desktop-Timerverwaltung eine native MICA-Benachrichtigung. Die Timerdatei wurde einmal verbraucht; der Desktop-Callback blieb aus. Veraltete, korrigierte und gestoppte Zustellaufträge sowie Registrierungsfehler zusätzlich geprüft. |
| Projektgedächtnis | Der direkte Befehl öffnet die bestehende Übersicht, setzt den Projektfilter und lässt Herkunft, Bearbeiten und Löschen verfügbar. Die vorhandenen Gedächtnisprüfungen decken Freigaben, Entwurfserhalt, Aktualisierung und Konflikte ab. |

## Automatisierte Prüfungen

- Gesamtsuite auf dem abschließenden Stand: **783 bestanden**, **79 Unterprüfungen**,
  eine Deprecation-Warnung der FastAPI/Starlette-Testintegration.
- Python-Prüfumgebung separat unter `artifacts/project-assistance-check-py313`;
  Backend-Abhängigkeiten einschließlich Chonkie 1.7.0 und
  tree-sitter-language-pack 1.8.1 installiert. Die produktive Python-Umgebung
  wurde dafür nicht verändert.
- Ruff einschließlich der ergänzenden Importprüfung bestanden.
- Repository-Prüfung: 321 Python-Dateien und 137 lokale Dokumentationslinks,
  keine Fehler. `git diff --check` bestanden.

Beim vorangehenden Gesamtlauf schlug das Veröffentlichen einer Update-Sicherung
wegen einer vorübergehenden Windows-Dateisperre fehl. Die Veröffentlichung
wiederholt jetzt ausschließlich die Windows-Fehler 5/32 höchstens fünfmal mit
kurzen Pausen. Bestehende Ziele werden nicht ersetzt; andere oder dauerhafte
Berechtigungsfehler bleiben Fehler. Die entsprechenden positiven und negativen
Prüfungen sowie die abschließende Gesamtsuite bestanden.

## Echte lokale Laufzeit

`python scripts/check_project_assistance_windows.py` bestätigte:

- sichtbare UI-Automation-Beschriftung und Ausschluss des Testpassworts;
- eigenständige Timerzustellung durch Windows mit beobachteter nativer Meldung;
- keine Zustellung durch den beendeten Desktop-Callback;
- einmalige Entfernung des Timerdatensatzes; ausschließlich temporäre Testdaten.

Das aktualisierte API-Image wurde gebaut und gestartet. Alle neun vorhandenen
Core-Dienste meldeten gesund. Die Verbindung verwendete `https://localhost:8443`
mit der lokalen Caddy-CA und aktivierter Zertifikatsprüfung. Die geänderten
Quellen- und Dialogmodule wurden anhand ihrer SHA-256-Werte mit dem laufenden
Container abgeglichen.

`python scripts/check_project_assistance_core.py` bestätigte über diese Verbindung:

- Antwort des echten lokalen Modells zum bekannten Prüfport;
- eine bereitgestellte und eine vom Modell verwendete, exakt aufgelöste Textstelle;
- erfolgreiche Änderungs-Erklärung;
- Erkennung der vier neuen Befehlsarten;
- keine neu gespeicherten Gespräche oder Aufgaben; Testgespräch danach entfernt.

## Grenzen

Die Fensterprüfung belegt eine tatsächlich unterstützte Windows-Testanwendung,
nicht die Unterstützung jedes Fremdprogramms. Die Timerprüfung belegt Zustellung
in der angemeldeten Sitzung nach Beenden der Desktop-Timerverwaltung; ein
Rechnerneustart oder eine physische Schlaf-/Aufweckprüfung wurde nicht durchgeführt.
Physische Mikrofon- und Lautsprecherprüfungen sind kein Bestandteil dieser
Erweiterungsabnahme. Modellzitate müssen weiterhin inhaltlich geprüft werden.
Nutzung, Speichergrenzen und Zustellbedingungen stehen in
[Projektassistenz](project-assistance.md).
