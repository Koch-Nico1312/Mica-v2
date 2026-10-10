# Neue Alltagshilfen

Stand: **11.10.2026**. Öffne in der linken Navigation **Betrieb**.
Die dortige Seite heißt „MICA im Alltag“. Wähle anschließend den passenden Reiter.
Rechenbefehle gibst du im Chat ein; Dokumentinfos erreichst du über **Dateien**.

| Dein Ziel | Wo? | Beispiel oder Ergebnis |
|---|---|---|
| Offene Aufgaben priorisieren | Betrieb → Aufgaben | Heute fällig, überfällig oder hohe Priorität |
| Angezeigte Aufgaben mitnehmen | Betrieb → Aufgaben | Sichtbare Aufgaben als Markdown speichern |
| Einheiten umrechnen | Chat | `12 Zoll in cm` |
| Rechnen oder Prozentwert bestimmen | Chat | `Was sind 15 Prozent von 80` |
| Wörter zählen oder Text suchen | Dateien → Infos / Suche | Wortzahl oder Treffer mit Textzeile |
| Einkauf oder Reise vorbereiten | Betrieb → Listen | Einträge hinzufügen und abhaken |
| Ein Kennwort erzeugen | Betrieb → Kennwort | Maskiertes Kennwort, auf Klick kopieren |
| Große Dateien finden | Betrieb → Dateigrößen | Größte 20 Dateien eines ausgewählten Ordners |

Aufgaben aus dem Backend benötigen eine Verbindung für einen aktuellen Stand.
Rechner, Umrechnung, Dokumentinfos, Kennwortgenerator und Ordnerprüfung arbeiten
lokal. Listenänderungen benötigen den Modus mit Speicherung. Die
[Jira-Anbindung](JIRA_MCP.md) wird separat beschrieben und ist bis zum Nachmittag
zurückgestellt. Der [Prüfstand](MICA_IMPROVEMENTS_PROGRESS.md) zeigt die Testbelege.

## Aufgaben im Blick

Unter **Betrieb → Aufgaben** kannst du den Aufgabenstand nach Dringlichkeit,
Fälligkeit oder Titel sortieren. Priorität und Termine sind in der Tabelle sichtbar.
**Heute fällig oder überfällig**, **Überfällig** und **Hohe Priorität** zeigen die
passenden offenen Aufgaben. Termine verwenden die Zeitzone Europe/Vienna.
Erledigte Aufgaben werden durch diese Terminfilter nicht als überfällig gezeigt.

**Sichtbare Aufgaben als Markdown speichern** exportiert die aktuelle Ansicht
in eine lokale Datei. Die Datei enthält Titel, Beschreibung, Status, Priorität
und gegebenenfalls Fälligkeit. Sie enthält keine Aktionsparameter oder
Ausführungsergebnisse. Ein veralteter Backend-Stand wird im Export kenntlich gemacht.

## Einheiten umrechnen

MICA versteht diese kurzen Befehle ohne Sprachmodell:

- `Mica, rechne 2,5 kg in Gramm um`
- `12 Zoll in cm`
- `500 ml in Liter`
- `1 Hektar in m2`
- `1,5 Stunden in Minuten`
- `32 Fahrenheit in Celsius`

Das funktioniert im Desktop auch im Offline-Modus. Unterstützt werden Länge,
Masse, Volumen, Fläche, Zeit und Temperatur. Werte sind auf zwölf signifikante
Stellen gerundet. Die Umrechnung verbindet ausschließlich Einheiten derselben
Größe; etwa Kilogramm und Liter brauchen zusätzliche Angaben wie die Dichte.
Währungsumrechnung und Maße wie Cups sind nicht Teil dieser Funktion.

Die Backend-Version muss neu gestartet/gebaut werden, bevor die neuen
Chatbefehle im bereits laufenden Backend verfügbar sind.

## Dokumentinfos und lokale Suche

Unter **Dateien → Infos / Suche** siehst du die Wort-/Zeichenzahl der ausgewählten
Dokumente. MICA zählt die bereits eingelesene Textversion und kennzeichnet
gekürzte oder nachträglich geänderte Dateien. Die Lesedauer ist eine Schätzung
mit 200 Wörtern pro Minute.

Im selben Fenster kannst du wörtlichen Text in allen angehakten Dokumenten
suchen. Treffer enthalten den Dokumentnamen, die Textzeile und einen Ausschnitt.
Suchzeichen wie `.*` sind normale Zeichen, keine regulären Ausdrücke.
Es werden weder zusätzliche Dateien gelesen noch Texte an ein Modell gesendet.

Die Befehle `Wörter zählen`, `Zeichen zählen` und `Dokumentinfos` zeigen die
Zählung auch im Offline-Desktop und im Modus ohne Speicherung an.

## Lokale Listen

Unter **Betrieb → Listen** kannst du Einkaufs-, Pack- und Prüflisten anlegen.
Einträge lassen sich abhaken und wieder öffnen. Zum Entfernen eines Eintrags
oder einer ganzen Liste bestätigst du die Auswahl ausdrücklich.

Für einen schnellen Einstieg wähle **Einkauf**, **Reise** oder **Arbeitsbeginn**.
Die Einträge der Vorlage werden vor dem Anlegen angezeigt. **Vorlage als neue
Liste** speichert sie unter dem eingegebenen Namen, andernfalls unter dem
Vorlagennamen; vorhandene Listen werden dabei nicht überschrieben.

**Als neue Liste kopieren** übernimmt die Einträge der ausgewählten Liste unter
einem neuen Namen. Alle Einträge der Kopie sind offen; die ursprüngliche Liste
bleibt erhalten. Für wiederkehrende Abläufe setzt **Alle wieder öffnen** nach
Bestätigung alle Haken der ausgewählten Liste zurück. Beides benötigt den Modus
mit Speicherung und bleibt auch nach einem Neustart erhalten.

Die Listen bleiben lokal auf diesem Gerät gespeichert. Sie sind unabhängig von
den Backend-Aufgaben und lösen keine Bestellungen oder andere Aktionen aus.
Im Modus ohne Speicherung werden Listenänderungen abgelehnt. Wenn eine andere
MICA-Instanz denselben Stand geändert hat, wird die Ansicht aktualisiert; prüfe
den neuen Stand vor einem erneuten Änderungsversuch.

## Rechner

Im Chat funktionieren `rechne (5 + 3) * 2`, `was ist 0,1 + 0,2` oder
`Was sind 15 Prozent von 80`. MICA berechnet das lokal mit Dezimalarithmetik,
auch im Offline-Desktop ohne Speicherung. Unterstützt sind +, -, *, / und
Klammern, mit höchstens zwölf signifikanten Stellen in der Ergebnisanzeige.

## Kennwort erzeugen

Unter **Betrieb → Kennwort** erzeugst du ein zufälliges Kennwort lokal.
Die Anzeige ist zunächst maskiert; **Kopieren** übernimmt es auf deinen Klick
in die Zwischenablage. MICA speichert das Kennwort nicht im Chat oder in Dateien.
Nach 60 Sekunden oder beim Verlassen der Seite entfernt MICA die Anzeige und
die noch unveränderte eigene Zwischenablagekopie. Der Windows-Zwischenablageverlauf
bleibt davon unberührt. Vorher neu kopierter fremder Text wird nicht gelöscht.

## Große Dateien finden

Unter **Betrieb → Dateigrößen** wählst du einen Ordner aus. MICA zeigt
die gefundenen logischen Dateigrößen und die größten 20 Dateien an. Es liest
Dateinamen und Größen, ohne Dateiinhalte zu öffnen oder Dateien zu verändern.
Links und Windows-Reparse-Punkte werden übersprungen; UNC-Netzwerkfreigaben
werden abgelehnt. Du kannst die Prüfung abbrechen. Bei Abbruch, erreichtem
Budget oder nicht lesbaren Bereichen ist das Ergebnis ausdrücklich eine
Teilprüfung. Die logische Größe kann vom belegten Speicherplatz abweichen.
