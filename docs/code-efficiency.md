# Codebereinigung und Effizienz-Refactoring

Stand: 2026-10-04. Die Bereinigung umfasst aktive Desktop- und Backend-Module,
gemeinsame Verträge, Paketgrenzen und die automatisierten Prüfungen. Das
Legacy-Archiv bleibt historische Quelle. Änderungen wurden anhand konkreter
Mehrarbeit, Imports und Abhängigkeiten ausgewählt; Funktionen und Berechtigungen
werden durch bestehende und zusätzliche Verhaltenstests abgesichert.

## Änderungen

- **Wissensindex:** Die Indexpflege liegt in `backend/services/common/brain_index.py`.
  Inhaltsfingerprints werden dauerhaft im abgeleiteten SQLite-Index gespeichert.
  Suchen lesen die Markdown-Quellen einmal und aktualisieren nur geänderte
  Dokumente. FTS, Vektoren und Quellenmetadaten werden zusammen in einer
  Transaktion geändert. Löschungen, externe Änderungen trotz gleicher
  Dateigröße/Zeitstempel und eine neue Prozessinstanz bleiben sichtbar.
- **Suche:** Lernfeld- und Kind-Filter gelten vor dem FTS-Limit. Gleiche Relevanz
  behält die Reihenfolge der neuesten Quellen. Vektorberechnungen entfallen,
  wenn genaue Treffer das Limit bereits füllen. Ergänzende Vektortreffer werden
  pro Dokument zusammengefasst und nur die besten benötigten Treffer ausgewählt.
  Exakte Treffer behalten auch bei optionalem Hindsight Priorität.
- **Wiederherstellung:** Explizites `brain.reindex()` baut weiterhin den gesamten
  Index neu auf. `force=False` synchronisiert Änderungen und wird vom periodischen
  Worker sowie nach Schreibvorgängen genutzt. Fehlende/alte Indextabellen werden
  migriert. Der Index bleibt aus Markdown rekonstruierbar. Atomare Dateiersetzung
  verhindert, dass Leser einen begonnenen Schreibvorgang als Quelle übernehmen.
- **Datenbanklisten:** Pläne, Schritte und Korrekturen werden in drei Abfragen über
  eine Verbindung und einen Lesesnapshot geladen. Twin-Fakten werden gemeinsam
  geladen; der Prompt liest nur die benötigten aktiven Fakten. Zusätzliche Indizes
  unterstützen Planreihenfolge, Korrekturen, aktive Fakten, Operationen und Historie.
- **Audit:** Jede Abfrage, jedes Anhängen und jede Verifikation prüft weiterhin die
  vollständige Hash-Kette. Die Verifikation verarbeitet Datensätze nacheinander;
  eine Listenabfrage behält nur die angeforderte Anzahl im Speicher. Die
  Laufzeit bleibt proportional zur Kettenlänge; die Integritätsprüfung wird
  weder gecacht noch auf die letzte Seite beschränkt.
- **Desktop:** Verlauf, Erinnerungen und lokales Gedächtnis liegen in
  `desktop/ui_pages.py` und teilen die Kopfzeilen-Erstellung. MainWindow behält
  seine Methoden. Die UI-Fassade behält ihre bisherigen Exporte. Verborgene HUD-
  und Wellenform-Widgets stoppen ihre Animationstimer. Die Log-Warteschlange
  verwendet eine FIFO ohne wiederholtes Verschieben aller wartenden Einträge.
- **Lokales Gedächtnis:** Die Größenbereinigung zählt entfernte JSON-Einträge
  inkrementell, statt nach jedem Entfernen den gesamten Speicher zu serialisieren.
  Reihenfolge, Zeichenlimit, Unicode-/Escape-Behandlung und Benachrichtigung bleiben
  erhalten.
- **Imports:** Ungenutzte Imports und drei ungenutzte optionale Paketprüfungen
  wurden entfernt. Desktop-Konfiguration und Control Center haben kanonische
  Paketimporte. Ein eigener Prozess prüft optionale Desktop-Aktionen ohne
  zusätzliche Desktop-Suchpfade. Die CI prüft ungenutzte Implementierungsimports.

## Lokale Messung

Gleicher Windows-Rechner, Python 3.13, gleiche Paketumgebung und synthetische
Daten vor/nach der Änderung. Zeiten sind der Median von drei Wiederholungen.
Ein Teil der Messungen lief parallel zu Tests; kleine Zeitunterschiede sind
keine belastbare Leistungsänderung. Zählwerte und Speicherverbrauch sind als
eigene Nachweise aufgeführt. Die [Rohwerte](benchmarks/code-efficiency-2026-10-04.json)
enthalten den Ausgangscommit und die gemessenen Zahlen.

| Prüfung | Vorher | Nachher |
|---|---:|---:|
| Unveränderte Suche, 80 Markdown-Dokumente | 162 ms | 19 ms |
| Chunker-Aufrufe je unveränderter Suche | 80 | 0 |
| Liste mit 80 Plänen | 175 ms | 1,8 ms |
| Verbindungen je Planliste | 241 | 1 |
| Zusätzlicher Python-Spitzenspeicher: 25 Audit-Einträge aus 6.000 | 6.697.902 B | 46.427 B |
| Vollständig geprüfte Audit-Abfrage | 38 ms | 42 ms |
| Größenbereinigung bei 1.200 Gedächtniseinträgen | 487 ms | 6,9 ms |

Die Audit-Änderung spart Speicher; eine Beschleunigung wird daraus nicht
abgeleitet. Der Benchmark misst die hier genannten Datenmengen, keine
LLM-Latenz, echten Benutzerdaten, produktiven Container oder physischen Geräte.

Reproduzieren im Projektstamm, in der Entwicklungsumgebung mit den dokumentierten
Runtime-/Prüfabhängigkeiten:

```powershell
python scripts/benchmark_efficiency.py --runs 3 --output .mica-data/refactor-benchmark.json
```

Der Benchmark erstellt alle Quellen, Pläne und Audit-Daten in einem temporären
Verzeichnis. Er sendet keine Provideranfragen und nutzt keine produktiven Stores.

## Prüfung und Grenzen

`tests/test_efficiency_refactor.py` ergänzt Verhaltens- und Recovery-Prüfungen für
unveränderte/neue/gelöschte Quellen, gleiche Größe und Zeitstempel, Domainwechsel,
Schemawechsel, expliziten Wiederaufbau, abgebrochene Index-/Dateischreibvorgänge,
parallele Instanzen, Trefferreihenfolge und vollständige Vektorrangfolge.
Weitere Fälle prüfen Audit-Manipulation außerhalb der zurückgegebenen Seite,
Plan-/Twin-Datenformate, Größenbereinigung und Sichtbarkeit der Animationstimer.

Die vollständige aktive Testsuite wird zusammen mit Ruff, Importgrenzen,
Repository-/Linkprüfung und der Diff-Prüfung ausgeführt. Historische Testzahlen
stehen in ihren datierten Nachweisen; sie gelten nicht als aktueller Testlauf.
Der finale lokale Lauf für diese Änderung bestand mit **546 Tests und 77
Untertests**; zwei Warnungen stammen aus Starlette/TestClient-Abhängigkeiten.
Der direkte Vergleich mit dem Ausgangscode ergab identische Ergebnisse für
18 repräsentative Suchfälle und vier Embedding-Eingaben. Repository-, Link-,
Import- und Ruff-Prüfungen sind fehlerfrei. Die Prüfumgebung war separat vom
Projekt und verwendete zusätzlich bereits installierte Systempakete.
Docker-/Zielhost-Betrieb, echte Provider, physische Audiofunktionen und eine
Produktionsabnahme bleiben separate [Abnahmen](README.md#phasen-und-abnahme).
