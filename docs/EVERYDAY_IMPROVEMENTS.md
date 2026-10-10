# Neue Alltagshilfen

## Aufgaben im Blick

Unter **MICA im Alltag → Aufgaben** kannst du den Aufgabenstand nach Dringlichkeit,
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

Unter **MICA im Alltag → Listen** kannst du Einkaufs-, Pack- und Prüflisten anlegen.
Einträge lassen sich abhaken und wieder öffnen. Zum Entfernen eines Eintrags
oder einer ganzen Liste bestätigst du die Auswahl ausdrücklich.

Die Listen bleiben lokal auf diesem Gerät gespeichert. Sie sind unabhängig von
den Backend-Aufgaben und lösen keine Bestellungen oder andere Aktionen aus.
Im Modus ohne Speicherung werden Listenänderungen abgelehnt. Wenn eine andere
MICA-Instanz denselben Stand geändert hat, wird die Ansicht aktualisiert; prüfe
den neuen Stand vor einem erneuten Änderungsversuch.
