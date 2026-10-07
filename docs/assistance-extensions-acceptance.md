# Prüfnachweise für die sechs Assistenz-Erweiterungen

Stand: 2026-10-07. Der Quellstand, die laufende API und die getrennten
Windows-Prüfungen werden gegen die sechs Anforderungen geprüft.

| Anforderung | Nachweis |
|---|---|
| Erinnerungen erledigen, verschieben und Aufgaben öffnen | UI-Tests prüfen die drei Aktionen und die Statusänderung. `check_assistance_extensions_windows.py` beobachtet das echte unabhängige Fenster, klickt per UI Automation auf zehn Minuten Aufschub und prüft die neue dauerhafte Frist sowie den registrierten Windows-Task. |
| Aufgaben aus Dokumenten mit Termin und Quelle | API-Tests prüfen Originalzitate, Ablehnung erfundener Belege, Speicherung erst nach Bestätigung und idempotente Wiederholung. Der reale HTTPS-Core liefert lokal erzeugte Vorschläge mit geprüften Textstellen. |
| Gesprächsroutinen mit bearbeitbarer Vorschau | API/Desktop verwenden dieselbe Grammatik. UI-Test prüft Dokumentauswahl, Fokus, Pause, Bearbeitung und Speicherung ohne Start. Timer-Test prüft Fokusende und Pausenbeginn nach Neustart. |
| Diktatvorschau und Sprachkorrekturen | Tests prüfen Satzersatz, nächste Ersatzaufnahme, Rückgängig, Stichpunkte, Abbruch und die Trennung vom Aktionspfad. Der echte lokale STT-Dienst transkribiert über HTTPS synthetisierte lokale Prüfsprache. |
| Lernkarten und verteilte Wiederholung | API prüft die Quellzitate; Antworten stammen direkt daraus. Tests prüfen ausdrückliches Speichern, Deduplizierung, Bewertungen, dauerhafte Fristen, erneutes Öffnen und Löschen. Der echte lokale Core erzeugt belegte Karten. |
| Letzten Projektschritt auf Wunsch merken und anzeigen | Tests prüfen explizite Aktivierung, unveränderte ältere Fassungen und Wiederaufnahme mit letztem und nächstem Schritt. Die vorhandene Projektladeprüfung bleibt erhalten. |

## Reproduzierbare Prüfungen

Ergebnisse dieses Durchlaufs:

- Vollständige Testsammlung: **808 bestanden, 79 Untertests bestanden**, eine
  bestehende Starlette-TestClient-Deprecation-Warnung. Die zuletzt ergänzten zwei
  Prüfungen zum bestehenden Windows-Erinnerungspfad wurden anschließend gemeinsam
  mit den Erweiterungs- und HUD-Tests geprüft: **38 bestanden**.
  Abschließend bestanden **56 gezielte Tests** für Erweiterungen, Sprachmodus und
  Alltagshilfe einschließlich der gleichzeitigen Zustellung nach einer Ruhezeit.
- Standard-Ruff-Prüfung bestanden; zusätzliche Import-/Variablenprüfung der
  neuen Module bestanden. Bestehende Altmodule werden nicht als zusätzlich
  bereinigt dargestellt.
- Repositoryprüfung: **333 Python-Dateien, 141 lokale Dokumentationslinks,
  keine Fehler**. `git diff --check` bestanden.
- Echtes Windows: Benachrichtigung nach Desktop-Shutdown beobachtet; Schaltflächen
  sichtbar; zehn Minuten Aufschub tatsächlich angeklickt; neuer Datensatz und
  Windows-Task geprüft; eigene Prüf-Tasks anschließend entfernt.
- Laufender HTTPS-Core mit lokalem Modell: Aufgaben, Lernkarten, Stichpunkte und
  alle fünf neuen Gesprächsbefehle geprüft. Keine Aufgaben oder Karten produktiv
  gespeichert. Der synthetische lokale Diktattest wurde erfolgreich transkribiert.
- API neu gebaut und gestartet; die bestehenden neun Core-Dienste sind gesund.
  Acht geänderte API-/Shared-Quelldateien stimmen byteweise mit dem laufenden
  Container überein. Keine eigenen `MICA-Timer-*`-Prüftasks blieben zurück.

- `python -m pytest tests/test_assistance_extensions.py tests/test_feature_runtime_callbacks.py tests/test_voice_improvements.py -q`
- `python scripts/check_assistance_extensions_windows.py`
- `python scripts/check_assistance_extensions_core.py`
- `python scripts/check_assistance_dictation_core.py`
- `python scripts/check_project_assistance_windows.py`
- `python scripts/check_repository.py`

Die Windows-Prüfungen verwenden eigene temporäre Zustandsdateien, suchen den
konkreten Prüfprozess anhand seiner zufälligen Timerkennung und räumen die eigenen
Tasks wieder auf. Die Modell- und Diktierprüfungen speichern keine Aufgaben,
Lernkarten oder Audioaufnahmen in den produktiven Daten.

## Grenzen der Nachweise

Synthetisierte Prüfsprache ist kein Nachweis für das physische Mikrofon,
Hintergrundgeräusche oder österreichischen Dialekt. Schlafzustand, Abmeldung und
Neustart des gesamten Rechners wurden nicht geprüft; Windows-Zustellung bei
geschlossener Desktopoberfläche wurde tatsächlich beobachtet. Die Bedienfenster
sind eigene MICA-Fenster, keine Windows-Action-Center-Toasts.

Quellenprüfung bestätigt wörtliche Belege. Sinnhaftigkeit der Fragen und Aufgaben
und die korrekte Interpretation von Terminen bleiben Teil der sichtbaren Prüfung
vor dem Speichern. Die Backend-Funktionsschalter, Cloudfreigaben und bestehenden
Programmfreigaben bleiben wirksam. Der Produktivpfad für Diktieren wurde mit einem
lokalen TTS/STT-Dienst geprüft; externe Sprachdienste wurden nicht verwendet.
