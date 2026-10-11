# MICA Improvements – Arbeits- und Prüfstand

Stand: **11.10.2026**, Dokumentationsarbeit tatsächlich ab **13:08 Europe/Vienna**.
Branch: **MICA-Improvements**. Aktueller Codecheckpoint:
`0abe40ca446a06a742600ba9b17e7b66cd79ef98`.
Die Bedienung steht unter [Neue Alltagshilfen](EVERYDAY_IMPROVEMENTS.md);
alle weiteren Themen unter [Dokumentationsübersicht](README.md).

## Aktueller Status

| Bereich | Verifizierter Stand |
|---|---|
| Funktionsumfang | 20 Funktionspakete in zwei Zyklen; Erweiterungen derselben Funktion zählen als eigene Pakete |
| Aktuelle kombinierte Prüfung | 42 Tests am Codecheckpoint 0abe40c: Notizen, Checklisten, Markdown und integrierte Seiten |
| Statische Prüfung am Codecheckpoint | Ruff bestanden; 382 Python-Dateien und 164 lokale Links geprüft |
| Dokumentationsabschluss | Repository-Prüfung: 382 Python-Dateien, 171 lokale Dateilinks, keine Fehler; Abschnittslinks separat geprüft |
| Historische breite Prüfung | 953 Tests und 79 Untertests am älteren Checkpoint 1d8e134; ein Integrationstest ausgeschlossen |
| Separate historische Text-/Codeaufbereitung | Zwei Tests mit festgelegten Versionen bestanden |
| Veröffentlichung | Codecheckpoint 0abe40c auf GitHub-Branch MICA-Improvements bestätigt |
| Dokumentation | Einstieg nach Nutzerzielen, vollständige Bedienwege, Beispiele und getrennte Prüfstände überarbeitet |
| Eigene Codeprüfung | Eigene Prüfung und passende Tests; Bugbot ausdrücklich vom Nutzer ausgeschlossen |
| Jira | Einrichtung und echte Kontoabnahme separat zurückgestellt |

**Die 953 Tests sind keine aktuelle Gesamtprüfung von 0abe40c.**
Die späteren fokussierten Läufe überschneiden sich und werden nicht addiert.

Die Ergebnisse belegen Quellcode und geprüfte Codepfade. Sie bestätigen keine
aktuell laufende Desktop-/Backend-Version, physische Audio-Abnahme, Docker-
Installation oder Verbindung mit einem echten Jira-Konto. Die Oberflächentests
verwenden Qt-Offscreen; der Kopiertest eine kontrollierte Zwischenablage.
Ein Neustart des aktualisierten Desktops lädt die neuen Reiter. Neue Backend-
Befehle erfordern gegebenenfalls Neubau und Neustart.

## Aktuelle Prüfung nachvollziehen

Der letzte kombinierte Lauf am Codecheckpoint 0abe40c bestand mit **42 Tests**:

```powershell
python -m pytest tests/test_quick_notes.py tests/test_checklists.py tests/test_local_markdown_export.py tests/test_everyday_pages.py -q
```

Er umfasst Speicherung über Neustarts, alte Datenformate, Revisionkonflikte,
Eingabegrenzen, atomare Speicherfehler, Bestätigungsabbruch, dynamischen
Datenschutzwechsel, gefilterte Eintragszuordnung, Entwurfserhalt, Markdown-
Maskierung und die Übernahme einer Notiz als neue Checkliste.

Für die Dokumentationspflege wird die Repository-Prüfung verwendet:

```powershell
python -X utf8 scripts/check_repository.py
```

Sie prüft Python-Syntax und lokale Markdown-Dateilinkziele. Der heutige
Dokumentationslauf erfasste 382 Python-Dateien und 171 lokale Dateilinks ohne
Fehler. Die Abschnittslinks der vier überarbeiteten Dokumente wurden zusätzlich
geprüft. Es wurde kein neuer Produktfunktionstest gestartet, da ausschließlich
Dokumentation geändert wurde. Diese Prüfung ersetzt keine externe Link-/Dienstprüfung.

## Zweiter Zyklus: zehn weitere Funktionspakete

| Nr. | Funktion und Bedienweg | Verhalten | Checkpoint | Fokussierter Lauf nach dem Paket |
|---|---|---|---|---|
| 11 | Betrieb → Listen: Vorlagen und Wiederverwendung | Einkauf/Reise/Arbeitsbeginn; Vorschau, neue offene Kopie, bestätigtes Wiederöffnen | `030f14f` | 10 Tests |
| 12 | Betrieb → Notizblock | Ausdrückliches Speichern, Suche, Entwurfserhalt und Neustart-Persistenz | `8070f7d` | 20; anschließend 34 überlappende Tests |
| 13 | Listen/Notizblock → Markdown-Export | Sichtbaren Stand als wörtlichen Text exportieren; Entwurf/älteren Stand markieren | `3401634` | 24 Tests |
| 14 | Notizblock → Anheften und Suchvorschau | Dauerhaft anheften, Unicode-Suche, begrenzte Ausschnitte; Entwurf bleibt erhalten | `e9d5bb0` | 18 Tests |
| 15 | Notizblock → Papierkorb | Bestätigtes Verschieben, schreibgeschützte Ansicht, Wiederherstellen/endgültiges Entfernen | `4fbc5b4` | 20 Tests |
| 16 | Listen → Mehrere Einträge | Zeilen/Aufzählungen/Markdown-Haken nach Vorschau gemeinsam übernehmen | `b3ae6ae` | 21 Tests |
| 17 | Listen → Suche / Nur offene Einträge | Filter kombinieren; Export umfasst ausschließlich sichtbare Einträge | `772b500` | 23 Tests |
| 18 | Listen → Ausgewählten Eintrag bearbeiten | Text korrigieren, Identität und Erledigt-Zustand erhalten | `d8a08da` | 25 Tests |
| 19 | Notizblock → Notiz als Markdown kopieren | Ausdrückliche Kopie mit Rückprüfung, auch ohne Speicherung | `6bd63f0` | 22 Tests |
| 20 | Notizblock → Notiz als neue Checkliste | Vorschau/Bestätigung, eine vollständige neue Liste, Notiz unverändert | `0abe40c` | 42 Tests |

Diese Zahlen sind überlappende Zwischenstände. Der letzte Lauf mit 42 Tests
ist der kombinierte Nachweis für die aktuelle lokale Erweiterung.

### Grenzen und Fehlerpfade

- **Notizen:** höchstens 100 einschließlich Papierkorb, Titel 80 und Text
  20.000 Zeichen. Keine automatische Speicherung; ungespeicherte Entwürfe
  gehen beim Beenden verloren. Vor Wechsel/Neuladen wird Verwerfen bestätigt.
- **Listen:** höchstens 20 mit je 200 Einträgen; Namen 80 und Einträge 240 Zeichen.
  Ungültige Stapel oder Namenskonflikte werden vollständig abgelehnt.
- **Speicherung:** Revision, Prozesssperre und atomarer Dateiaustausch verhindern
  unbemerkte Übernahme auf veraltetem Stand und Teiländerungen bei Speicherfehlern.
  Der Modus ohne Speicherung wird auch nach Dialogen erneut geprüft.
- **Exports:** sichtbare Inhalte, kenntliche Entwürfe/ältere Ansicht und
  wörtliche Maskierung; der Notizblock wird dadurch nicht zusätzlich gespeichert.
- **Zwischenablage:** nur auf ausdrücklichen Klick. Die Notizkopie wird nicht
  automatisch gelöscht. Beim Kennwort gilt ein eigener begrenzter Löschweg;
  Windows-Zwischenablageverlauf bleibt davon unberührt.
- **Notiz zu Liste:** Vorschau vor Erstellung; Abbruch, doppelte Inhalte,
  Speicherfehler und Revisionkonflikte hinterlassen keine Teil- oder leere Liste.

## Erster Zyklus: zehn Funktionspakete

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

## Historische breite Prüfung: Checkpoint 1d8e134

Der damalige breite erfolgreiche Lauf umfasste `tests/` und die Backend-Prüfungen für
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

Ruff über sämtliche im Branch geänderten Python-Dateien bestand. Die damalige
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
**nicht** addiert und ersetzen die Prüfung einer später veränderten Codebase nicht.

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


## Zeitlicher Ablauf und Abschluss

Geplant waren Featurearbeit bis **06:00**, Dokumentation ab **08:30** und ein
separater Abschalttermin um **09:03**, jeweils am 11.10.2026 Europe/Vienna.

Um **01:48** wurde die Grenze von mindestens 95 Prozent Verbrauch erreicht;
Entwicklung und Tests wurden gestoppt. Der natürliche Reset war für **05:04:45**
vermerkt. Eine Wiederaufnahme der Featurearbeit nach diesem Reset ist im
vorliegenden Laufstand nicht belegt. Codecheckpoint 0abe40c blieb unverändert.
Nach 06:00 wurden keine neuen Funktionen begonnen.

Der letzte nächtliche bestätigte Statusversand erfolgte gegen **02:04**.
Die folgenden vorgesehenen 20-Minuten-Mails sind nicht belegt. Die Dokumentations-
automation wurde erst gegen **13:08** ausgelöst; die überfällige Statusmail
wurde daraufhin versandt. Damit wurden die verlangten Zeitfenster und der
durchgehende Mailrhythmus nicht vollständig eingehalten.

Die Dokumentationsarbeit erfolgt verspätet als eigener Abschluss. Der vergangene
Abschalttermin wird dabei nicht erneut ausgelöst oder dupliziert. Sein tatsächlicher
Vollzug wird hier nicht behauptet. Abgelaufene Entwicklungs-/Wiederaufnahmetermine
sind pausiert; nach Abschluss wird auch die einmalige Dokumentationsautomation
pausiert. Private Versandzeiten und verarbeitete Mail-IDs bleiben ausschließlich
im ignorierten lokalen Laufzeitstand.

Zugangsdaten, private Mailinhalte, Datenbanken, Modelle und virtuelle Umgebungen
werden nicht als Projekt-Checkpoints veröffentlicht.
