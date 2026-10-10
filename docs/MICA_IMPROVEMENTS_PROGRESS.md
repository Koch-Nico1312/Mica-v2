# MICA Improvements – Arbeits- und Prüfstand

Stand: **11.10.2026**. Verbesserungsbranch: **MICA-Improvements**.
Basis des ersten Zyklus: `e0c2133`. Aktueller Auftrag: Featurearbeit bis 06:00 Uhr,
Dokumentationsüberarbeitung ab 08:30 Uhr am 11.10.2026, Europe/Vienna.

## Aktueller Status

| Bereich | Stand |
|---|---|
| Erster Funktionszyklus | Zehn Funktionen im Quellcode und ihren Bedienwegen implementiert |
| Breite Regression | 953 Tests und 79 Untertests bestanden; ein Integrationstest ausgeschlossen |
| Text-/Codeaufbereitung | Zwei zusätzliche Tests mit den festgelegten Versionen bestanden |
| Quellcode und Links | Ruff bestanden; nach Dokumentationsüberarbeitung 377 Python-Dateien und 164 lokale Links ohne Fehler geprüft |
| Veröffentlichung | Alle bisherigen Änderungen auf GitHub; letzter Prüfcheckpoint `1d8e134` |
| Codeprüfung | Nutzer hat Bugbot ausdrücklich ausgeschlossen; eigene Codeprüfung und passende Tests |
| Jira | Weitere Einrichtung und echte Kontoabnahme bis zum Nachmittag zurückgestellt |
| Dokumentation | Einstieg, Übersicht, Bedienwege, Git-Stand und Prüfbericht überarbeitet; bisherige Einstiegslinks erhalten |

Diese Angaben beschreiben Quellcode und ausgeführte Prüfungen. Sie bestätigen
keine aktuell laufende Desktop-/Backend-Version, physische Audio-Abnahme oder
Verbindung mit einem echten Jira-Konto. Der ausgeschlossene Integrationstest
benötigt einen separat laufenden Dienst. Erfolgreiche Tests sind keine Garantie
einer vollständig fehlerfreien Codebase.

## Neuer Funktionszyklus

**Wiederverwendbare Checklisten:** Unter Betrieb → Listen bieten Einkauf, Reise
und Arbeitsbeginn eine sichtbare Vorlage vor dem ausdrücklichen Anlegen.
Bestehende Listen lassen sich als neue, vollständig offene Liste kopieren oder
nach Bestätigung für den nächsten Durchlauf wieder öffnen. Neue IDs trennen
Kopien vom Original; Namenkonflikte, veraltete Revisionen und Speicherfehler
überschreiben keine vorhandenen Listen. Der Modus ohne Speicherung bleibt wirksam.

Prüfung dieses Pakets: **10 Tests bestanden** für Checklisten und integrierte
Alltagsseiten, einschließlich Neustart, Revision, Kopieridentität,
Speicherfehler, Bestätigungsabbruch und dynamischem Datenschutz. Die Prüfung
verwendet Qt-Offscreen; eine sichtbare laufende Desktop-Abnahme steht aus.
Die folgenden breiten Ergebnisse beziehen sich auf den vorherigen Checkpoint.

**Lokaler Notizblock:** Betrieb → Notizblock bietet neue Notizen, Bearbeiten,
wörtliche Suche in Titel und Text, ausdrückliches Speichern und bestätigtes
Entfernen. Ungespeicherte Entwürfe bleiben bei Filterwechsel, Speicherfehlern und
Revisionkonflikten erhalten. Vor dem Wechsel der Notiz und dem Neuladen muss das
Verwerfen bestätigt werden. Gespeicherte Notizen bleiben über Neustarts erhalten;
ungespeicherte Entwürfe gehen beim Beenden verloren. Keine Backend-/Modellanfrage;
Speicherungsfreigabe wird bei jedem Schreibvorgang neu geprüft.

Prüfung nach diesem Paket: **20 Tests bestanden** für Notizblock, Checklisten und
integrierte Alltag-Seiten. Neue Prüfungen decken Größen-/Anzahlgrenzen, Neustart,
Suche, Revisionkonflikt, atomaren Speicherfehler, beschädigte Daten,
Bestätigungsabbruch und den integrierten Datenschutzwechsel ab. Ruff und
Konsistenzprüfung bestanden: 380 Python-Dateien, 164 lokale Links, keine Fehler.
Die anschließende Prüfung des Notizblocks zusammen mit integrierten Seiten,
Aufgabenübersicht und Startfenster bestand mit **34 Tests**. Die beiden Läufe
überschneiden sich; ihre Testzahlen werden nicht addiert.

**Markdown-Export für Listen und Notizen:** Eigene Schaltflächen speichern den
sichtbaren Stand in einer gewählten Datei. Listen behalten ihre Haken und warnen
bei veraltetem Stand. Notizen kennzeichnen ungespeicherte Entwürfe, ohne sie
zusätzlich im Notizblock zu speichern. HTML, Bilder und Links werden als
wörtlicher Text maskiert. Der Modus ohne Speicherung sperrt auch den Export;
die Freigabe wird nach dem Dateidialog erneut geprüft. Atomarer Dateiaustausch
erhält alte Dateien bei Fehlern.

Prüfung dieses Pakets: **24 Tests bestanden** für Export, Notizen, Checklisten
und integrierte Alltagsseiten; Ruff bestanden. Neue Tests decken sichtbare
Entwürfe, Revisionhinweise, Abbruch, Freigabewechsel während des Dateidialogs,
Textmaskierung und gescheiterten Dateiaustausch ab. Diese Prüfung ist eine lokale
Quellcode-/Qt-Offscreen-Prüfung; der laufende Desktop muss die Änderungen durch
einen Neustart laden.

**Notizen anheften und Suchvorschau:** Gespeicherte Notizen lassen sich dauerhaft
anheften/lösen. Angeheftete stehen zuerst, andere nach Titel; jede Suche zeigt
eine begrenzte Textvorschau am ersten passenden Texttreffer und die Trefferzahl.
Die Vorschau berücksichtigt Unicode-Groß-/Kleinschreibung, etwa Straße/STRASSE.
Anheften erhält offene Textentwürfe und speichert deren Inhalt nicht. Alte
Notizdateien ohne Markierung bleiben lesbar; ungültige Markierungen werden
abgelehnt. Revision und Speicherungsfreigabe schützen auch diese Änderung.

**18 Tests bestanden** für Notizen, Markdown-Export und integrierte Alltagsseiten;
Ruff bestanden. Die neue Anheft-Prüfung deckt Neustart, alte Dateiformate,
veraltete Revisionen, Speicherfehler und offene Entwürfe ab. Eine beim ersten
Testlauf gefundene falsche Einfügung im Neuladeweg wurde korrigiert; der erneute
Lauf und die statische Prüfung bestehen.

**Notiz-Papierkorb:** Entfernen verschiebt den gespeicherten Text nach Bestätigung
in einen lokalen Papierkorb. Eine separate schreibgeschützte Ansicht ermöglicht
Wiederherstellen oder bestätigtes endgültiges Entfernen. Normale Suche blendet
entfernte Notizen aus. Die Identität, Texte und Anheft-Markierung bleiben bei
Wiederherstellung erhalten; es gibt keine automatische Leerung. Das Limit von
100 Notizen schließt den Papierkorb ein. Ungespeicherte Änderungen werden beim
Verschieben nach dem ausdrücklichen Hinweis verworfen.

**20 Tests bestanden** für Notizfunktionen, Export und integrierte Alltagsseiten;
Ruff bestanden. Neue Prüfungen decken Neustart, Wiederherstellen, Zustandsgrenzen,
Revisionkonflikte, gescheiterte endgültige Entfernung, Abbruch und Datenschutz ab.

**Mehrere Listen-Einträge einfügen:** Ein ausdrücklicher Textdialog verarbeitet
Zeilen, Aufzählungen, Nummerierungen und Markdown-Haken. Vorschau und Bestätigung
gehen einer gemeinsamen atomaren Änderung voraus; bereits erledigte Haken werden
übernommen. Duplikate, ungültige Einträge und das 200-Einträge-Limit führen zu
keiner Teiländerung. Ziel und Revision dürfen während der Dialoge nicht wechseln.
Dateien und Zwischenablage werden nicht automatisch gelesen.

**21 Tests bestanden** für Checklisten, lokale Markdown-Exporte und integrierte
Alltagsseiten. Neue Prüfungen decken Formatübernahme, Duplikate, Eingabegrenzen,
veraltete Revision, Dateiaustauschfehler, Vorschauabbruch und Speicherfreigabe ab.
Lange Parametertest-Namen verursachten im ersten Lauf einen Windows-Testaufbaufehler;
kurze explizite Fallnamen beseitigen diesen, der erneute Lauf besteht.

## Die zehn Funktionen

Öffne links **Betrieb**; die Seite trägt die Überschrift „MICA im Alltag“.
Die ausführliche Bedienung steht unter [Neue Alltagshilfen](EVERYDAY_IMPROVEMENTS.md).

| Nr. | Funktion und Bedienweg | Umfang und Grenzen |
|---|---|---|
| 1 | Betrieb → Jira | Lesende MCP-Verbindung über E-Mail und eingeschränkten API-Token im Windows Credential Manager. Website wählen, Vorgänge suchen/lesen; kein Browser-OAuth oder Jira-Schreiben. Zurückgestellt. |
| 2 | Betrieb → Aufgaben | Priorität und Wiener Termine, Filter für heute/überfällig/hohe Priorität; Sortierung nach Dringlichkeit, Fälligkeit oder Titel. Auswahl bleibt an die Aufgaben-ID gebunden. |
| 3 | Aufgaben → Markdown-Export | Genau die sichtbare Ansicht speichern; veralteten Stand kennzeichnen. Keine Aktionsparameter oder Ausführungsergebnisse. Atomischer Dateiaustausch. |
| 4 | Chat: Einheiten umrechnen | Länge, Masse, Volumen, Fläche, Zeit und Temperatur mit Dezimalarithmetik. Offline-Desktop unterstützt; gemischte Dimensionen und Temperaturen unter dem absoluten Nullpunkt abgelehnt. |
| 5 | Dateien → Infos / Suche | Wort-/Zeichenzahl, Absätze, geschätzte Lesedauer und wörtliche Suche in ausgewählten, bereits eingelesenen Texten. Änderungen/Kürzungen sichtbar; keine zusätzliche Dateilese- oder Modellanfrage. |
| 6 | Jira → lokale Aufgabe | Vorgang nach Vorschau und Bestätigung lokal übernehmen. Feste Website/Vorgangs-Identität verhindert überschreibende Duplikate. Speicherung erforderlich; Jira bleibt unverändert. Zurückgestellt. |
| 7 | Betrieb → Listen | Einkaufs-, Pack- und Checklisten lokal speichern, umbenennen, abhaken und nach Bestätigung entfernen. Revision, Prozesssperre und atomisches Schreiben schützen vorhandene Änderungen. |
| 8 | Chat: Rechner/Prozentfragen | Grundrechenarten und Klammern mit begrenzter Dezimalarithmetik, ohne Ausdrucksausführung oder Modellanfrage. Beispiel: `rechne (5 + 3) * 2`. |
| 9 | Betrieb → Kennwort | Lokal 12–128 Zeichen erzeugen, standardmäßig 20; maskierte Anzeige und ausdrückliches Kopieren. Anzeige/eigene unveränderte Kopie nach 60 Sekunden oder Seitenwechsel entfernen. Windows-Clipboard-Verlauf bleibt unberührt. |
| 10 | Betrieb → Dateigrößen | Metadaten eines ausgewählten Ordners lesen, Größen summieren und größte 20 Dateien zeigen. Links/Reparse-Punkte überspringen, Abbruch und begrenzte Teilprüfungen; keine Inhalte öffnen oder Dateien verändern. |

Details zur bestehenden Jira-Anbindung: [Jira-MCP](JIRA_MCP.md).
Beim lokalen Jira-Import ist die anfängliche 30-Minuten-Dauer ausdrücklich
ein anpassbarer Platzhalter. Wechsel von Website oder Vorgangsnummer verwirft
die Vorschau. Unbekannte Antwortformate werden nicht in geratene Aufgaben umgewandelt.

## Aktuelle Prüfergebnisse

Der breite erfolgreiche Lauf umfasst `tests/` und die Backend-Prüfungen für
TTS, Docker-Lernen sowie Deployment-Verträge. Ein separat erforderlicher
Integrationstest war ausdrücklich ausgeschlossen. Ergebnis: **953 Tests und
79 Untertests bestanden**, Laufzeit 224,96 Sekunden. Eine vorhandene
Starlette-Testclient-DeprecationWarning bleibt.

Für eine Wiederholung mit den erforderlichen Desktop-/Testabhängigkeiten:

```powershell
pytest tests backend/tests/test_tts_service.py backend/tests/test_docker_learning_acceptance.py backend/tests/test_deployment_acceptance.py -q -m "not integration"
```

Die Text-/Codeaufbereitung wurde separat unter Windows mit exakt
`chonkie[code]==1.7.0` und `tree-sitter-language-pack==1.8.1` geprüft:
**zwei Tests bestanden**. Das ist kein Beleg einer Docker-Abnahme; der lokale
Docker-Daemon war zu diesem Zeitpunkt nicht erreichbar.

Ruff über sämtliche im Branch geänderten Python-Dateien bestand. Die letzte
Konsistenzprüfung nach der Dokumentationsüberarbeitung erfasste 377 Python-Dateien
und 164 lokale Dokumentationslinks ohne Fehler. Nach Dokumentationsänderungen
wird die Linkprüfung erneut ausgeführt.

### Nachgewiesene Fehler und Stabilisierung

- **Ordnerprüfung:** Ein nach der ersten Auflistung durch einen Link ersetzter
  Unterordner wurde noch betreten. Jetzt werden die Metadaten unmittelbar vor
  dem Betreten erneut ohne Linkverfolgung geprüft. Der zuvor fehlschlagende
  Regressionstest besteht. Gleichzeitig veränderte Dateisysteme liefern
  weiterhin keinen atomaren Schnappschuss.
- **Checklisten:** Ein echter zweiter Python-Prozess kann während der Dateisperre
  nicht schreiben. Nach Freigabe gelingt Schreiben wieder. Ein Fehler beim
  atomaren Dateiaustausch erhält den alten Stand und entfernt die temporäre Datei.
- **Zusammengesetzte Oberfläche:** Dynamische Speicherungsfreigabe, Entfernen
  des Kennworts beim Tabwechsel und unterdrückte Backend-Aktualisierung auf lokalen
  Seiten wurden geprüft. Tests konstruierten auch die Hauptoberfläche im Qt-Offscreen-Modus.

### Frühere Testläufe richtig lesen

Die folgenden Zahlen sind Zwischenstände mit überlappenden Tests. Sie werden
**nicht** addiert und ersetzen den aktuellen breiten Lauf nicht.

| Zwischenstand | Ergebnis |
|---|---|
| Jira-Protokoll/UI, Secure Store und Aufgabenübersicht | 33 bestanden |
| Dokumentinfos und angrenzende Funktionen | 57 bestanden |
| Jira-Import und angrenzende Offline-/Planungsfunktionen | 80 bestanden |
| Erste Checklisten-/UI-Prüfungen | 32 bestanden |
| Rechner und angrenzende Funktionen | 73 bestanden |
| Kennwort und angrenzende Funktionen | 41 bestanden |
| Früher erweiterter Lauf plus zusätzlicher Offline-Umrechnungstest | 160 plus ein zusätzlicher Test bestanden |
| Alle zehn Erweiterungen und angrenzende Funktionen | 231 bestanden |
| Ordnerkorrektur und angrenzende Prüfungen | 30 bestanden |
| Checklisten-Prozess-/Speicherfehler, Ordner und Kennwort | 12 bestanden |
| Integrierte Alltag-Seiten, Hauptoberfläche und Startvertrag | 27 bestanden |

Im ersten erweiterten Lauf fehlten Testabhängigkeiten (`numpy`, `pypdf`,
`uvicorn`); der Wiederholungslauf mit ihnen bestand. Im ersten breiten Lauf
bestanden 940 Tests, ein Test scheiterte am in der isolierten Umgebung fehlenden
`sounddevice`. Diese Abhängigkeit steht bereits im Projektmanifest. Der einzelne
Test und anschließend der gesamte breite Lauf bestanden mit ihr; dafür wurde
kein Produktcode geändert.

## Veröffentlichte Checkpoints

| Commit | Inhalt |
|---|---|
| `c2cb11a` | Jira-MCP und lesende Desktop-Bedienung |
| `3bdac36` | Aufgabenansicht, Markdown-Export und Umrechnung |
| `0b498b9` | Dokumentinfos und lokale Suche |
| `b724ecc` | Geprüfter lokaler Jira-Aufgabenimport |
| `0d87440` | Arbeitsstand und Überwachungsorganisation |
| `5f5b01f` | Lokale Checklisten |
| `679d945` | Rechner und Kennwortgenerator |
| `4e6a14a` | Dateigrößen und kombinierte Zehn-Funktions-Prüfung |
| `35f2beb` | Erneute Prüfung wartender Ordner vor dem Betreten |
| `19c9825` | Checklisten-Prozesssperre und atomare Speicherfehler |
| `aed840c` | Integrierte Navigation, Datenschutz und Kennwort-Lebenszyklus |
| `1d8e134` | Breiter erfolgreicher Prüfstand |

## Fortsetzung und laufende Organisation

Auf die neue Dokumentationsanweisung hin wurden die Projekt-README und der
Dokumentationsindex nach konkreten Nutzerzielen neu geordnet und auf Deutsch
formuliert. Die Alltagshilfe nennt die tatsächliche Navigation **Betrieb**.
Git-Neustart vom 04.10. und heutige GitHub-Anbindung sind getrennt beschrieben.
Dieser Bericht zeigt die aktuelle Abnahme zuerst und die früheren Zwischenstände
gesondert. Alle vorherigen Linkziele der beiden Einstiegsseiten bleiben erreichbar.

Der Nutzer hat im aktuellen Auftrag ausdrücklich angewiesen, Bugbot nie zu
verwenden und neue Features weiterzuentwickeln. Die frühere Bugbot-Stufe gilt
damit nicht mehr; Änderungen werden mit eigener Codeprüfung und passenden
Tests geprüft. Unveränderte Tests werden nicht fortlaufend wiederholt.

Neue authentifizierte Instruktionen, einschließlich der separat beauftragten
Dokumentationspflege, werden weiterhin bearbeitet. Statusmails werden alle
20 Minuten anhand des letzten gespeicherten Versandzeitpunkts gesendet.

Die Überwachung heißt `mica-verbesserungen-bis-09-uhr`. Private Mail-IDs,
bearbeitete Instruktionen und Versandzeiten stehen ausschließlich im lokalen
Laufzeitstand `.mica-data/improvement-run/status.json`, der nicht committet wird.
Die Überwachung gehört jetzt zum aktuellen Verbesserungsauftrag; eine separate
einmalige Fortsetzung beginnt die Dokumentationsüberarbeitung um 08:30 Uhr.
Bei mindestens 95 Prozent Verbrauch eines relevanten Nutzungsfensters wird
Entwicklungsarbeit erst nach dem zugehörigen Reset fortgesetzt; Reset-Credits
werden nicht verwendet. Nach 06:00 werden keine neuen Funktionen begonnen;
Abschlussprüfung, Veröffentlichung und Abschlussmail folgen, dann endet die Überwachung.

Zugangsdaten, Datenbanken, Modelle, virtuelle Umgebungen und private Mailinhalte
werden nicht als Projekt-Checkpoints veröffentlicht.
