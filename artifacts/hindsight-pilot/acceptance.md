# Hindsight-Pilot für MICA — 30. September 2026

Der isolierte Funktionstest ist erfolgreich. Getestet wurde Hindsight 0.10.2
mit dem vorhandenen Qwen3-4B-Q4_K_M-Modell über einen lokalen llama.cpp-Server,
CPU-Betrieb mit vier Threads und 16384 Tokens Kontext. Es wurden ausschließlich
drei repräsentative Testauszüge zu MICA verwendet, keine produktiven Chatarchive.

## Nachgewiesen

Der echte Server bestätigt Aufbereitung und begrenzten Recall. Eine neue
Clientinstanz synchronisiert bereits bestätigte Quellen nicht nochmals.
Nach tatsächlichem Stoppen des Hindsight-Containers liefert MICA lokale Treffer;
nach dem Neustart sind die externen Erinnerungen wieder verfügbar. Korrekturen
sperren die alte Quelle sofort und synchronisieren die neue Fassung. Nach der
Löschung liefert auch eine direkte Serverabfrage keine Erinnerungen mehr.

Die Reflexion beantwortet die Speicherentscheidung und Stimmpräferenz korrekt,
liefert überprüfbare Quell-IDs und bleibt als Ableitung gekennzeichnet.

## Vergleich

| Frage | Lokaler Rang | Hindsight allein | MICA mit Ergänzung |
| --- | ---: | ---: | ---: |
| Bevorzugte Sprachausgabe | 1 | 3 | 1 |
| Lösung des Docker-Startfehlers | 1 | 1 | 1 |
| Maßgeblicher Wissensspeicher | 1 | 2 | 1 |

Lokale Suche: 0,026–0,029 Sekunden. Hindsight-Recall: 0,459–0,639 Sekunden.
Die ergänzte MICA-Suche: 0,474–0,494 Sekunden. Reflexion: 131,166 Sekunden.
Die Aufbereitung der drei Auszüge benötigte zusammen 172,606 Sekunden;
der lokale Rückfall während des Dienst-Ausfalls 2,352 Sekunden.

Diese kleinen Beispiele zeigen keinen Qualitätsgewinn gegenüber der vorhandenen
Suche. Daher behalten exakte lokale Treffer ihren Vorrang. Die Funktion bleibt
optional und standardmäßig ausgeschaltet. Die Messung belegt Funktion und
Fehlerverhalten, keine allgemeine Überlegenheit oder GPU-/Produktionsabnahme.

Die Ressourcen-Stichprobe während einer früheren Reflexion zeigt etwa 1 GiB
für Hindsight und 4,3 GiB für das lokale Modell. Es handelt sich um eine
Momentaufnahme, nicht um eine gemessene Spitze.

## Belege

- [Vollständiger erfolgreicher Lauf](report.json)
- [Erster Lauf mit zu kurzem Reflexionslimit](report-first.json)
- [Zweiter Lauf vor Anpassung des Hindsight-internen Zeitlimits](report-second.json)
- [Ressourcen-Stichprobe](resource-samples.jsonl)

Zusätzlich bestanden 176 gezielte Regressionstests mit sechs Unterfällen.
Die Compose-Konfiguration ist gültig. Die produktive MICA-Konfiguration wurde
nicht aktiviert; Testdaten und Dienste sind von ihr getrennt.
