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
