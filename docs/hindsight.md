# Hindsight: optionales Langzeitgedächtnis

Stand: 2026-09-30.

Hindsight ergänzt den Markdown-Brain. Markdown bleibt die maßgebliche Quelle;
Hindsight speichert nur abgeleitete Erinnerungen. Die Erweiterung ist standardmäßig
ausgeschaltet. Es werden keine neuen Python-Abhängigkeiten benötigt.

## Lokaler Betrieb

Nach Start von Docker Desktop in `backend/.env` beide Optionen setzen:

```env
MICA_HINDSIGHT_ENABLED=1
MICA_HINDSIGHT_ALLOW_PRIVATE=1
```

Dann aus `backend/` die bestehende Compose-Konfiguration ergänzen:

```powershell
docker compose -f docker-compose.yml -f docker-compose.hindsight.yml --profile hindsight up -d
```

Unter Windows kann der vorhandene Launcher aus dem Projektverzeichnis mit
`python -m backend.windows_launcher --hindsight -- up -d --build` verwendet
werden. Er übernimmt weiterhin die bestehende Credential-Manager-Grenze.

Der Dienst verwendet Hindsight 0.10.2 mit persistenter Datenbank und Modellcache.
Er nutzt MICAs lokalen llama-server für die Aufbereitung und Reflexion. Beim
optionalen Start wird dessen Tool-Unterstützung aktiviert und sein Kontext auf
16384 Tokens gesetzt (`MICA_HINDSIGHT_LLM_CONTEXT` kann dies konfigurieren).
Die Extraktion ist auf kurze Abschnitte und 4096 Ausgabetokens begrenzt.
Beim ersten Start werden lokale Embedding-/Reranker-Modelle heruntergeladen; deshalb
hat der Hindsight-Container Zugang zum Edge-Netz. Es gibt keine veröffentlichten
Ports am Host und keine Cloud-Schlüssel. Der unten dokumentierte CPU-Pilot
prüft die Integration mit drei Testauszügen; eine Alltagsabnahme mit dem
gewählten Zielmodell und freigegebenen Beispielen bleibt separat erforderlich.

`MICA_HINDSIGHT_ALLOW_PRIVATE` erlaubt ausdrücklich die Übertragung ausgewählter
privater Texte an diesen Dienst. Bei einem externen Dienst müssen außerdem
`MICA_HINDSIGHT_URL` und `MICA_HINDSIGHT_ALLOW_REMOTE=1` in der Prozessumgebung
gesetzt werden (HTTPS erforderlich); dessen Modellanbieter separat prüfen.
Ein optionaler `MICA_HINDSIGHT_API_KEY` kommt ausschließlich aus der Umgebung.
Die mitgelieferte Compose-Konfiguration verwendet immer den lokalen Dienst.

## Auswahl und Verwendung

- Neue Backend-Gespräche liefern einen kurzen, unveränderten Auszug der
  Nutzeraussage (bis 1800 Zeichen). MICAs Antwort wird nicht übernommen.
- Kurze Werkzeugberichte aus abgeschlossenen Aufgaben werden als solche
  gekennzeichnet. Lange Berichte bleiben ausschließlich im Markdown-Brain.
- Kurze Dokumente vom Typ `memory` können übernommen werden. Alte vollständige
  Gespräche, Rohbelege, Recherche und allgemeine Runbooks werden nicht pauschal
  importiert. `hindsight_exclude: true` schließt ein Dokument aus.
- Der zusätzliche Filter überspringt erkennbare Schlüssel/Passwortzuweisungen;
  er ist kein vollständiger Geheimnisdetektor. Sensible Quellen explizit ausschließen.

Ein eigener Worker synchronisiert eine Quelle je Durchlauf und wartet danach
15 Sekunden. Dadurch verzögert die Modellverarbeitung keine geplanten Aufgaben.
Ein dauerhaftes SQLite-Ledger merkt sich bestätigte Quellen und unbestätigte
Netzwerkversuche auch nach einem Neustart. Es liegt unter
`/data/memory-sync/hindsight.sqlite3`; der vorhandene Backup-/Restore-Drill
sichert es am Standardpfad als JSON-Zustand und rekonstruiert es beim Restore.
Bei Korrekturen, Ausschluss oder Löschung wird die alte
Hindsight-Quelle zuerst gelöscht. Fehler werden im nächsten Durchlauf erneut
versucht, mit persistenter Wartezeit von 30 bis 300 Sekunden pro fehlgeschlagener
Quelle. Andere Quellen können währenddessen weiterlaufen; geänderte Quellen und
Löschungen umgehen die Wartezeit der alten Version. Solange eine Quelle nicht
aktuell bestätigt ist, wird sie nicht verwendet.

Die normale Suche bewahrt exakte lokale Treffer und ergänzt schwächere
Vektortreffer mit Hindsight-Rangfolgen. Der Antwortkontext stammt weiterhin aus
aktuellem Markdown, nicht aus extrahierten
Behauptungen. Gefilterte Recherche bleibt lokal. Ausfälle lassen die lokale Suche
weiterlaufen; Recall hat ein kurzes Netzwerk-Zeitlimit.

`POST /v1/chat` unterstützt optional `memory_mode: "reflect"`. Das ist eine
gezielte, zusätzliche Auswertung, keine automatische Reflexion jedes Gesprächs.
Im bestehenden Chat funktioniert auch die ausdrückliche Formulierung
`Rückblick: Welche Entscheidungen haben wir für das Projekt getroffen?`.
Die bestehende Freigabe für privaten Kontext bei Cloud-Antworten gilt weiterhin.
Reflexionen werden als unbestätigte Ableitungen gekennzeichnet und nicht gespeichert.
Sie sind gesperrt, solange die Synchronisierung aussteht oder ihre Quellen fehlen.
Die gezielte Reflexion kann auf einer CPU Minuten dauern. Für die Aufbereitung
und Reflexion gelten standardmäßig jeweils 180 Sekunden Netzwerk-Zeitlimit
(`MICA_HINDSIGHT_RETAIN_TIMEOUT` und `MICA_HINDSIGHT_REFLECT_TIMEOUT`, maximal
300 Sekunden); normale Recall-Aufrufe bleiben auf zwei Sekunden begrenzt.

Weitere API-Endpunkte:

| Endpunkt | Zweck |
| --- | --- |
| `GET /v1/memory/hindsight` | Lokaler Synchronisierungsstand, kein Live-Gesundheitsbeweis |
| `POST /v1/memory/hindsight/reflect` | Explizite Reflexion mit `message` und Quellen-IDs |
| `POST /v1/memory/hindsight/sync` | Einen Synchronisierungsdurchlauf auslösen |
| `PATCH /v1/brain/documents/{id}` | Inhalt mit `body` korrigieren |
| `DELETE /v1/brain/documents/{id}` | Quelle lokal löschen und extern zur Löschung vormerken |

Sync/Korrektur/Löschung benötigen die bestehende lokale Freigabesitzung und
`X-Mica-Approval-Intent: confirm`. Die Löschung im externen Dienst erfolgt
nachgelagert; bei Ausfall bleibt sie ausstehend. Lokal ist die Quelle sofort
ausgeschlossen. Korrekturen entfernen alte Gesprächs-/Ergebniszusammenfassungen;
eine neue Auswahl ist erforderlich.
Optional kann bei einer Korrektur `memory_excerpt` mit einem kurzen, wörtlichen
Auszug aus dem neuen `body` angegeben werden; dieser wird neu synchronisiert.
Die neue Funktion betrifft das Backend, nicht den separaten alten Desktop-JSON-Speicher.

## Sicherung und Abschalten

Der [Backup-/Restore-Drill](../backend/README.md#backup-and-restore-acceptance)
sichert Markdown, Audit und den Sync-Zustand unter `hindsight_sync` in
`state/phase4.json`. Ein abweichender Pfad über `MICA_HINDSIGHT_DB` braucht
eine eigene Sicherung. Der Drill sichert die separaten Compose-Volumes
`hindsight-data` (PostgreSQL) und `hindsight-models` (Modellcache) nicht.
Für eine vollständige Wiederherstellung des optionalen Dienstes ist zusätzlich
eine konsistente PostgreSQL-Sicherung erforderlich. Das Sync-Ledger allein
stellt die externe Datenbank nicht wieder her und beweist ihre Verfügbarkeit nicht.

Zum Abschalten beide Optionen in `backend/.env` auf `0` setzen und den Stack
mit demselben Hindsight-Startbefehl erneut starten, damit API und Worker die
neue Konfiguration übernehmen. Danach aus `backend/` nur die optionalen
Dienste stoppen:

```powershell
docker compose -f docker-compose.yml -f docker-compose.hindsight.yml --profile hindsight stop hindsight-sync hindsight
```

Das Stoppen erhält die Volumes. Es löscht bereits übertragene Erinnerungen
nicht; ausstehende Löschungen werden erst bei erneuter aktivierter
Synchronisierung verarbeitet. Die lokale Suche arbeitet ohne Hindsight weiter.

## Gemessener Pilot und Abnahme

Der isolierte CPU-Pilot vom 30. September 2026 lief erfolgreich mit Hindsight
0.10.2 und Qwen3-4B-Q4_K_M, vier CPU-Threads und 16384 Tokens Kontext.
Geprüft wurden Aufbereitung, Recall, wiederholte Synchronisierung ohne Duplikate,
explizite Reflexion, echter Dienst-Ausfall, Neustart, Korrektur und Löschung.
Eine direkte Serverabfrage nach der Bereinigung bestätigte die Löschung.

| Messung | Ergebnis |
| --- | --- |
| Rang des passenden Treffers, lokale Suche | 1 / 1 / 1 |
| Rang des passenden Treffers, Hindsight allein | 3 / 1 / 2 |
| Rang des passenden Treffers, MICA mit Ergänzung | 1 / 1 / 1 |
| Lokale Suche | 0,026–0,029 s |
| Hindsight-Recall | 0,459–0,639 s |
| MICA-Suche mit Ergänzung | 0,474–0,494 s |
| Explizite Reflexion | 131,166 s |
| Aufbereitung der drei Auszüge insgesamt | 172,606 s |
| Lokaler Rückfall während des Dienst-Ausfalls | 2,352 s |

Die drei Beispiele zeigen keinen Qualitätsgewinn gegenüber der lokalen Suche.
Exakte lokale Treffer behalten deshalb Vorrang, und Hindsight bleibt
standardmäßig ausgeschaltet. Die Laufzeiten gelten für diesen CPU-Piloten.
Eine Ressourcen-Stichprobe zeigte etwa 1 GiB für Hindsight und 4,3 GiB für das
lokale Modell; das ist keine gemessene Lastspitze.

Der [Pilotbericht](../artifacts/hindsight-pilot/acceptance.md) verlinkt den
[erfolgreichen Messlauf](../artifacts/hindsight-pilot/report.json), beide früheren
Fehlerberichte und die Ressourcen-Stichprobe. Zusätzlich bestanden 176 gezielte
Regressionstests mit sechs Unterfällen; die Compose-Konfiguration wurde geprüft.
Die produktive Konfiguration wurde nicht aktiviert. Nach dem Pilot wurden die
Testcontainer beendet; Daten und Modellcaches blieben erhalten.

### Pilot wiederholen

Ein isolierter Pilot nutzt das vorhandene Qwen-Modell und ausschließlich drei
repräsentative Testauszüge. Aus `backend/` starten:

```powershell
$env:MICA_HINDSIGHT_PILOT_MODELS=(Resolve-Path '..\desktop\models').Path
docker compose -p mica-hindsight-pilot -f docker-compose.hindsight-pilot.yml up -d
```

Vor dem Python-Aufruf muss der Hindsight-Dienst bereit sein. Prüfen, bis
`status` den Wert `healthy` meldet; der erste Modelldownload kann dauern:

```powershell
Invoke-RestMethod http://127.0.0.1:8889/health
```

Danach einen neuen Bericht schreiben, damit der datierte Nachweis erhalten bleibt:

```powershell
python hindsight_pilot.py --report ..\artifacts\hindsight-pilot\report-repeat.json --restart-container mica-hindsight-pilot-hindsight-1
```

Der Bericht enthält Treffer-Rangfolgen und gemessene Laufzeiten sowie
Prüfungen für Neustart, Korrektur und Löschung. Ein Fehlerbericht bewahrt
Speicherkennung und lokalen Synchronisierungsstand für die Nachprüfung.
Das ist ein kleiner Funktionstest, kein Nachweis allgemeiner Überlegenheit.
Die Neustartoption prüft zuerst das Compose-Projektlabel und stoppt ausschließlich
den isolierten Pilot-Dienst, um den lokalen Rückfall und Datenbank-Neustart zu messen.
Die Testcontainer danach beenden; ihre Daten und Modellcaches bleiben erhalten:

```powershell
docker compose -p mica-hindsight-pilot -f docker-compose.hindsight-pilot.yml down
```

Vor dauerhafter Aktivierung mit echten, freigegebenen Beispielen vergleichen:
sinngleiche Vorlieben, Projektentscheidungen und Fehlerlösungen; Trefferqualität
gegen die lokale Suche, Recall-/Reflect-Laufzeiten und Ressourcenverbrauch messen.
Die im Pilot bestandenen Ausfall-, Neustart-, Korrektur- und Löschprüfungen auch
für die vorgesehene Installation wiederholen. Vertragstests mit einem Testserver
ersetzen diese Modell-/Betriebsabnahme nicht.

Quellen: [Hindsight](https://github.com/vectorize-io/hindsight),
[API](https://hindsight.vectorize.io/developer/api/retain),
[Recall/Reflect](https://hindsight.vectorize.io/blog/2026/07/24/recall-vs-reflect).
