# Abschlussprüfung: MICA-Weiterentwicklung

Stand: 4. Oktober 2026. Geprüft wird der Implementierungsauftrag mit fünf Bereichen.

| Anforderung | Implementierung | Nachweis |
|---|---|---|
| Bestätigte Vorlieben mit Herkunft, Geltungsbereich, Korrektur und Löschung | EvolutionStore, geschützte API, Text-/Voice-Kontext, Windows- und PWA-Oberfläche | test_evolution: Neustart, konkurrierende Korrekturen, scope override, vollständige Löschung, Authentifizierung, privates Cloud-Opt-in; test_evolution_desktop |
| Fehlendes Werkzeug, Werkzeugfehler, fehlende Rechte, Ausfall unterscheiden | Strukturierte Klassifikation; Hooks bei Aufgabenfehlern, gemeldeten Misserfolgen und unbekannten angeforderten Aktionen | parametrische Klassifikationsfälle, echte API-Anfragen, nicht ausgeführte und fehlerhaft ausgeführte Werkzeugantworten |
| Spezifikation, Kandidat und unabhängige Prüfungen aus einer belegten Lücke | Unveränderliche Prüfaufgabe, Input-/Output-Typen, begrenzte Modellerzeugung, bestehende Git-Worktree-Pipeline | test_skill_workshop, test_evolution_api; keine Erzeugung bei Freigabe-/Ausfallsignalen; Modell erhält keine Testantworten |
| Alte und neue Version anhand derselben Aufgaben vergleichen | Networkless quality runner mit eingefrorenen Fixtures; richtige Ergebnisse, Fehler, Dauer, Providerkosten; separat bestätigte Nutzerkorrekturen | echter Docker-Test: fehlerhafte Version 1/3, reparierte Version 3/3; falsche Ergebnisse abgelehnt; Beobachtungen dedupliziert; unbekannte Messgrößen bleiben null |
| Begrenzte Reparatur mit Reproduktion, getrenntem Patch und Prüfung vor Übernahme | Aktiver Code als Baseline, sichtbarer Diff, 80 geänderte Zeilen, separate Kandidatenkopie, reproduzierter Fehler als Gate, gesonderte Übernahmefreigabe | echter Docker-Test einschließlich isolierter Nutzung und Rollback; keine Übernahme bei geänderter Baseline; Timeout abgelehnt |

Die größere gezielte Regression bestand mit 172 Tests. Danach ergänzte
Fehlerklassifikation für ausgeführte Werkzeuge wurde mit den betroffenen
Aufgaben-/Client-Tests und einem zusätzlichen Test geprüft. Zwei Fehler in neuen
Testdaten wurden korrigiert und die betroffenen Tests erneut erfolgreich ausgeführt.
Ein echter Docker-Lauf prüfte Ablehnung, Reproduktion, Reparatur, Übernahme,
isolierte Nutzung und Rollback. JavaScript-Syntax, Python-Kompilation und
Diff-Whitespace wurden ebenfalls geprüft.

`desktop.png` ist eine Layoutaufnahme mit Testdaten. Sie zeigt keine Ergebnisse
aus einem produktiven MICA-Betrieb. Die native Oberfläche wurde zusätzlich mit
Qt-Tests geprüft. Der isolierte Docker-Lauf verwendete tatsächliche Container
mit Python 3.12; API-/Modelldurchläufe wurden mit kontrollierter Modellantwort und
Broker-Evidenz geprüft. Ein vollständiger produktiver mTLS-/Provider-/Audio- oder
Hardwarelauf ist damit nicht behauptet. Es wurden keine aktiven Nutzerdaten
umgeschrieben und keine produktiven Artefakte übernommen.

Die Änderung liegt im Quellprojekt. Bei Nutzung über bestehende Docker-Images
müssen die betroffenen Backend-/Web-Images wie üblich aus dem aktuellen Quellstand
gebaut werden. Der aktuelle Host hatte beim Abschluss keinen laufenden MICA-Stack.
Nutzung und Grenzen sind in `docs/evolution.md` beschrieben.
