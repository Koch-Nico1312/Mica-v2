# Projektstände, Dokumentquellen und Fensterhilfe

Die Erweiterungen verwenden die bestehende Windows-Oberfläche
`desktop/local_main.py` und die lokale Backend-API. Nach einem Update müssen
Oberfläche und API neu gestartet beziehungsweise das API-Image neu gebaut werden.

## Mehrere Projektstände

**Arbeitsstand** öffnet die Projektauswahl. Wähle einen bestehenden Namen oder
gib einen neuen ein, trage den nächsten Schritt ein und bestätige **Aktuellen
Arbeitsstand speichern**. Gespeichert werden die ausgewählten Dokumentfassungen,
die aktuelle Aufgabe und der nächste Schritt. „Wechsle zu MICA“ oder „Wechsle
zu Projekt Schule“ öffnet die Vorschau des passenden Projekts; **Gespeicherten
Arbeitsstand laden** übernimmt dessen Dokumentauswahl und Gesprächsbezug.

Es gibt bis zu 20 Projekte und die drei zuletzt ausdrücklich gespeicherten
Fassungen pro Projekt. Dateien und Aufgaben unterliegen den bisherigen Grenzen.
Gelöschte Aufgaben werden nicht wieder erzeugt. Geänderte Originaldateien
werden markiert; Laden verwendet die gespeicherte Textfassung. Die bisherigen
Einzelstände werden als `standard` angeboten und beim ersten Schreiben in den
Projektbestand übernommen. Die alte Datei bleibt erhalten und wird nach der
Migration nicht erneut automatisch eingelesen.

Projektstände liegen unter `.mica-data/project-workspaces.json`, enthalten
private Dokumenttexte im Klartext und werden nur ausdrücklich gespeichert.
Ohne Gesprächsspeicherung sind Speichern und Laden gesperrt. Gleichzeitige
Schreibzugriffe werden ausgeschlossen. Löschen entfernt alle drei Fassungen
des ausgewählten Projekts aus dem aktiven Projektbestand; eine alte
`workspace.json` oder externe Sicherungen werden dadurch nicht gelöscht.

## Dokumentquellen bei Antworten

Für ausgewählte Dokumente erhält das Sprachmodell begrenzte Textausschnitte mit
Quellmarkierungen. Es soll Aussagen mit `[Q1]`, `[Q2]` usw. belegen und
Widersprüche unter Angabe beider Quellen erklären. Das Backend löst verwendete
Markierungen auf die tatsächlich bereitgestellten Textstellen auf und ergänzt
die Antwort um Dateiname, Zeilen, bei PDFs Seitenbereich sowie den Originaltext.
PDF-Zeilen beziehen sich auf den ausgelesenen Text, nicht auf die visuelle
Seitengestaltung. Gleiche Dateinamen bleiben über Dokumentkennungen unterscheidbar.

Die API liefert außerdem `citations`, `document_sources`, `invalid_citations`
und `spoken_reply`.
Unbekannte Markierungen werden als unbelegt gekennzeichnet. Nennt das Modell
keine Textstelle, erscheint ein entsprechender Hinweis. Die bereitgestellten
Ausschnitte werden dann getrennt als vom Modell nicht
zugeordnete Textstellen angezeigt. Eine gültige Markierung
beweist die Herkunft der Textstelle; sie beweist nicht, dass jede Modellbehauptung
aus ihr folgt. Auslassungen und widersprüchliche Aussagen müssen geprüft werden.
Sprachausgabe liest die kurze Antwort und verweist auf die sichtbaren Quellen.
Dokumenttexte und Quellen gelangen nur mit dem bestehenden privaten Cloud-Opt-in
zu einem Cloudanbieter. Das Erstellen der Quellen selbst speichert keine Dokumente.

## Dokumentänderungen erklären

**Dateien → Änderungen**, „Dokumentänderungen zeigen“ oder „Was hat sich seit
gestern geändert?“ öffnet den Vergleich. Wähle eine eingelesene Fassung oder
eine der drei gespeicherten Projektfassungen. **Mit aktueller Datei vergleichen**
liest die Originaldatei lokal und zeigt hinzugefügte und entfernte Zeilen.
**Änderungen erklären** fordert anschließend eine Modell-Erklärung an.

Die Ausgangszeit wird sichtbar angezeigt. Ohne eine gestern bekannte Fassung
kann Mica keine Änderungen seit gestern feststellen. Ein Projekt-Speicherzeitpunkt
bezeichnet den gespeicherten Snapshot und garantiert nicht, dass eine inzwischen
geänderte Originaldatei damals erneut eingelesen wurde. Vergleiche ändern weder
die Originaldatei noch die Gesprächsauswahl. Fehlende Dateien erzeugen einen
Hinweis. Extraktionen und lange Vergleiche können gekürzt sein; die Oberfläche
zeigt diese Einschränkung. Temporäre Fensteraufnahmen ohne Originaldatei lassen
sich nicht mit einer aktuellen Datei vergleichen.

## Bedienelemente in der Fensterhilfe

**Fensterhilfe**, „Erklär mir diese Fehlermeldung“ oder „Wo ändere ich diese
Einstellung?“ erfasst das zuletzt gewählte fremde Fenster einmalig. Die Vorschau
zeigt sowohl das Bild als auch die per Windows UI Automation erkannten sichtbaren
Beschriftungen, etwa Buttons, Tabs und Fehlermeldungstexte. Der Haken für
Bedienelemente kann vor **Als Kontext verwenden** entfernt werden.

Es werden keine Buttons angeklickt und keine Eingabewerte ausgelesen.
Passwortfelder, unsichtbare Elemente und fremde Prozesse werden ausgelassen.
Auslesen ist auf 200 Elemente, 12.000 Textzeichen und sechs Sekunden begrenzt.
Ein verändertes Fenster wird abgelehnt. Bei fehlender Unterstützung bleibt OCR
verfügbar; umgekehrt können bestätigte Beschriftungen auch ohne lesbaren OCR-Text
verwendet werden. Die Unterstützung hängt von der Anwendung und ihren Rechten ab.

## Timer bei geschlossener Oberfläche

Die Windows-Oberfläche registriert jeden Timer zusätzlich in der Windows-
Aufgabenplanung. Nach dem Schließen übernimmt ein eigener Prozess die Zustellung
und zeigt eine native MICA-Timerbenachrichtigung mit Signalton. Bei geöffneter
Oberfläche bleiben die bestehenden Timerhinweise zuständig. Eine gemeinsame
Dateisperre und die gespeicherte Timerkennung verhindern doppelte Zustellung.
Stoppen, Korrigieren und Not-Aus machen alte Zustellaufträge unwirksam.

Es sind weder Administratorrechte noch optionale Toast-Pakete erforderlich.
Der Nutzer muss angemeldet sein; bei ausgeschaltetem Rechner erfolgt keine
Zustellung. Windows kann verpasste Termine nach dem nächsten verfügbaren Start
zustellen. Verschieben der Python-Installation oder des Projekts erfordert
erneutes Starten der Oberfläche zur Registrierung der aktuellen Pfade.
Scheitert die Registrierung eines neuen Timers, wird kein Erfolg bestätigt.
Bei Problemen mit bereits gespeicherten Timern wird die eingeschränkte
Zustellung ausdrücklich gemeldet. Auf anderen Betriebssystemen bleibt die
bisherige Zustellung in der geöffneten Oberfläche bestehen.

## Projektgedächtnis auf Zuruf

„Was weißt du über Projekt MICA?“ öffnet **Gedächtnis**, setzt die Suche auf den
Projektnamen und lädt den aktuellen Backend-Stand. Die vorhandene Übersicht
zeigt Herkunft, bestätigte beziehungsweise abgeleitete Informationen sowie
Änderungszeitpunkte. Auswählen, Bearbeiten und Löschen verwenden weiterhin die
bestehenden Freigaben. Der Sprachbefehl selbst verändert keine gespeicherte
Information. Ungespeicherte Bearbeitungsentwürfe bleiben erhalten.

## Prüfung

`tests/test_project_assistance.py` prüft Projektmigration und Versionen,
Quellenauflösung und Cloudgrenzen, echte Dateivergleiche, exklusive Timerzustellung,
veraltete Timeraufträge, Registrierungsausfälle sowie die neuen Dialoge.
`scripts/check_project_assistance_windows.py` prüft mit temporären Daten echte
UI-Automation-Beschriftungen einschließlich Passwortausschluss und eine sichtbare
Windows-Timerbenachrichtigung nach Beenden der Desktop-Timerverwaltung. Produktive
Timer, Projektstände und Gedächtnisinhalte werden dabei nicht verändert.
`scripts/check_project_assistance_core.py` prüft die konfigurierte HTTPS-API mit
dem echten lokalen Modell, ohne neue Gespräche oder Aufgaben zu speichern.
Die Ergebnisse und ihre Grenzen stehen im [Abnahmenachweis](project-assistance-acceptance.md).
