# Repository-Wartung

Stand: 2026-10-04. Der Projektstamm enthält die gemeinsamen Einstiegspunkte,
Konfigurationsbeispiele und Dependency-Manifeste. Funktionscode liegt unter
`desktop/`, `backend/` und `mica_shared/`; historischer Code bleibt in `legacy/`.
Dokumentation liegt in `docs/`, Prüfwerkzeuge in `scripts/` und Tests unter
`tests/` und `backend/tests/`.

## Lokale Daten und Sicherungen

`.mica-data/`, `.env`, private Desktop-Konfiguration, Modelle und virtuelle
Umgebungen sind lokale Installationsdaten. Sie werden beim Aufräumen nicht
gelöscht. Einzelne ältere Connector-/Freigabedatenbanken können noch im
Projektstamm liegen; ihre Pfade dürfen nur zusammen mit der zugehörigen
Konfiguration migriert werden. Auch `.agents/`, `agent/` und `skills-lock.json`
gehören zur lokalen Werkzeugumgebung.

Explorer-Kopien von Konfiguration und Laufzeitdaten können Geheimnisse
enthalten. Prüfe Namen, Inhalt und Unterschiede, stelle fehlende kanonische
Dateinamen wieder her und archiviere übrige Kopien außerhalb des Checkouts.
Ignorierte Dateien sind nicht automatisch sicher zu löschen.

`artifacts/` enthält lokale Pilotberichte und einen historischen
Quellcode-Snapshot. Dessen alte Git-Metadaten wurden zusammen mit der bisherigen
Projekt-Historie außerhalb des Projekts archiviert. Das aktive Projekt besitzt
ein neues leeres Git-Repository ohne Remote; Details stehen in der
[Projektvorbereitung](Git-Vorbereitung.md).
Historische Messungen bleiben erhalten. Der [Design-QA-Bericht](design-qa.md)
ist ebenfalls historische Evidenz; seine lokalen Bildpfade sind kein aktueller
Abnahmenachweis. Generierte Caches und Testberichte werden ignoriert und können
nach abgeschlossenen Prüfungen entfernt oder außerhalb des Checkouts archiviert
werden. Laufende Prozesse werden dabei ausgespart.

## Prüfungen

Verwende eine separate Entwicklungsumgebung mit den Runtime-Abhängigkeiten
aus `requirements.txt`, `backend/requirements.txt` und den Prüfwerkzeugen aus
`requirements-dev.txt`. Die Backend-Chunker-Prüfung benötigt die dort exakt
gepinnten Chonkie- und Tree-Sitter-Versionen. Ändere für Prüfungen keine
produktive Python-Umgebung.

Im Projektstamm:

```powershell
python scripts/check_repository.py
python -m ruff check .
python -m ruff check --select F401,F811 desktop/actions desktop/core desktop/memory desktop/config backend mica_shared
$env:QT_QPA_PLATFORM = 'offscreen'
$env:MICA_LAYA_ENABLED = '0'
$env:MICA_DREAM_RSI_ENABLED = '0'
$env:MICA_LEARNING_NETWORK = '0'
python -m pytest
git diff --check
```

Die Repository-Prüfung liest nur versionierte und nicht ignorierte neue
Python-/Markdown-Dateien. Sie prüft erforderliche Einstiegspunkte,
Python-Syntax einschließlich des Legacy-Archivs, lokale Markdown-Linkziele
und verbliebene Explorer-Kopien im Projektstamm. Sie importiert keine
MICA-Module und verändert keine Konfiguration. Externe URLs und Anker werden
nicht geprüft. Ruff prüft die konfigurierten Ausführungsfehler; es erzwingt
keine Formatierungsänderung am gesamten Projekt.

Diese Prüfungen und die vollständige automatisierte Testsuite werden lokal
ausgeführt. Fehlende Abhängigkeiten sind eine fehlgeschlagene Prüfung und
kein Grund, die betroffenen Tests stillschweigend auszulassen. Hardware,
Zielhost-Deployment und echte Provider bleiben separate
[Abnahmeprüfungen](README.md#phasen-und-abnahme).

`python scripts/benchmark_efficiency.py` misst mit temporären Daten Suche,
Planlisten, Audit-Speicherverbrauch und Speicherbereinigung. Es verändert keine
Produktivdaten und aktiviert keine Provider. Vergleichswerte und Messgrenzen
stehen im [Refactoring-Nachweis](code-efficiency.md).
