# Neue Alltagshilfen

Stand: **11.10.2026**, Quellcodecheckpoint **0abe40c**.
Öffne in der linken Navigation **Betrieb**. Die Seite heißt „MICA im Alltag“;
dort wählst du den passenden Reiter. Rechenbefehle gehören in den Chat,
Dokumentinfos findest du unter **Dateien**.

## Schnell zum Ziel

| Ich möchte … | Bedienweg | Anleitung |
|---|---|---|
| Eine Idee festhalten und wiederfinden | Betrieb → Notizblock | [Notizen speichern und suchen](#lokaler-notizblock) |
| Eine Einkaufsliste oder Packliste vorbereiten | Betrieb → Listen | [Listen erstellen und wiederverwenden](#lokale-listen) |
| Aus einer Notiz eine Liste machen | Betrieb → Notizblock | [Notiz in Checkliste übernehmen](#aus-einer-notiz-eine-checkliste-machen) |
| Nur offene Listeneinträge mitnehmen | Betrieb → Listen | [Suchen, filtern und exportieren](#suchen-filtern-und-exportieren) |
| Fällige Aufgaben sehen | Betrieb → Aufgaben | [Aufgaben im Blick](#aufgaben-im-blick) |
| Einheiten umrechnen | Chat | [Umrechnung mit Beispielen](#einheiten-umrechnen) |
| Einen Prozentwert berechnen | Chat | [Rechner](#rechner) |
| Wörter zählen oder eine Textstelle finden | Dateien → Infos / Suche | [Dokumentinfos und Suche](#dokumentinfos-und-lokale-suche) |
| Ein Kennwort erzeugen | Betrieb → Kennwort | [Kennwortgenerator](#kennwort-erzeugen) |
| Große Dateien finden | Betrieb → Dateigrößen | [Ordnerprüfung](#große-dateien-finden) |

Die [Jira-Anbindung](JIRA_MCP.md) hat eine eigene Anleitung. Ihre Einrichtung
und Prüfung mit einem echten Konto sind separat zurückgestellt.
Der [Prüfbericht](MICA_IMPROVEMENTS_PROGRESS.md) unterscheidet aktuelle Tests,
ältere Prüfungen und noch offene Prüfungen auf dem Zielgerät.

## Was braucht Verbindung oder Speicherung?

| Funktion | Backend-Verbindung | Modus mit Speicherung |
|---|---|---|
| Aktuelle Aufgaben laden | Erforderlich | Aufgabenexport benötigt Speicherung |
| Gespeicherte Notizen oder Listen ansehen/suchen | Nicht erforderlich | Lesen möglich; Änderungen benötigen Speicherung |
| Notizentwurf bearbeiten oder als Markdown kopieren | Nicht erforderlich | Nicht erforderlich |
| Notiz speichern, anheften, entfernen oder wiederherstellen | Nicht erforderlich | Erforderlich |
| Listen ändern oder aus einer Notiz erstellen | Nicht erforderlich | Erforderlich |
| Notizen/Listen in eine Datei exportieren | Nicht erforderlich | Erforderlich |
| Rechner und Umrechnung im Offline-Desktop | Nicht erforderlich | Nicht erforderlich |
| Bereits eingelesene Dokumenttexte zählen/suchen | Nicht erforderlich | Nicht erforderlich |
| Kennwortgenerator und Dateigrößen | Nicht erforderlich | Keine Speicherung dieser Ergebnisse nötig |

Notizblock und Listen bleiben auf diesem Gerät. Diese Seiten senden ihre Inhalte
nicht an ein Backend oder Sprachmodell. Kopieren und Exportieren sind ausdrückliche
Übernahmen: Die Zwischenablage oder deine gewählte Datei enthält anschließend den Text.
Ein Export ersetzt das Speichern im Notizblock nicht.

## Lokaler Notizblock

### Eine Notiz speichern und wiederfinden

1. Öffne **Betrieb → Notizblock → Neue Notiz**.
2. Gib einen Titel, etwa „Ideen fürs Wochenende“, und deinen Text ein.
3. Klicke **Speichern**. Erst dieser Klick speichert den Text auf dem Gerät.
4. Nutze das Suchfeld für Text aus Titel oder Inhalt. Die Suche beachtet
   Groß-/Kleinschreibung nicht und zeigt kurze Textausschnitte mit Trefferzahl.

Die Suche ist wörtlich: Zeichen wie `.*` werden als Text gesucht.
Auch Treffer weiter hinten in langen Zeilen erscheinen in der Vorschau.
Mit **Notiz anheften** hältst du eine gespeicherte Notiz oben; **Notiz lösen**
hebt die Markierung auf. Angeheftete Notizen stehen zuerst, sonst wird nach Titel
sortiert. Anheften bleibt nach Neustarts erhalten und speichert keinen offenen
Textentwurf.

### Entwürfe sicher behandeln

Es gibt keine automatische Speicherung. Suche und Anheften erhalten den offenen
Entwurf. Beim Wechsel zu einer anderen Notiz, **Neue Notiz**, **Neu laden** oder
einem Wechsel in die Papierkorbansicht bestätigst du das Verwerfen ungespeicherter
Änderungen. **Beim Beenden von MICA gehen ungespeicherte Entwürfe verloren.**

Bei einem Speicherfehler oder einem inzwischen geänderten Datenstand bleibt
der Entwurf erhalten. Kopiere ihn vor dem Neuladen, etwa mit **Notiz als Markdown
kopieren**, und prüfe anschließend den neu geladenen Stand. Ein erneuter
Speicherversuch überschreibt keine neueren Notizen stillschweigend.

### Entfernen und wiederherstellen

1. Wähle eine gespeicherte Notiz und **In Papierkorb**.
2. Lies den Hinweis und bestätige. Verschoben wird der gespeicherte Text;
   ein offener, ungespeicherter Entwurf wird verworfen.
3. Aktiviere **Papierkorb anzeigen**, um entfernte Notizen schreibgeschützt zu sehen.
4. Wähle **Notiz wiederherstellen** und blende den Papierkorb danach aus.
   Gespeicherter Text und Anheft-Markierung bleiben erhalten.

**Endgültig entfernen** benötigt eine weitere Bestätigung. Danach kann die Notiz
aus diesem Papierkorb nicht wiederhergestellt werden. Der Papierkorb wird nicht
automatisch geleert und zählt zum Limit von **100 Notizen**. Jede Notiz erlaubt
bis zu **80 Zeichen Titel** und **20.000 Zeichen Text**.

### Eine Notiz mitnehmen

| Schaltfläche | Ergebnis |
|---|---|
| **Als Markdown exportieren** | Titel und sichtbarer Text in einer selbst gewählten Datei; Speicherung erforderlich |
| **Notiz als Markdown kopieren** | Titel und sichtbarer Text in der Zwischenablage; auch ohne Speicherung möglich |

Ungespeicherte Änderungen werden als **Entwurf** gekennzeichnet und bleiben im
Editor erhalten. Die Notiz wird durch Kopieren/Exportieren nicht zusätzlich
gespeichert. HTML, Bild- und Linksyntax werden im Markdown als wörtlicher Text
maskiert. MICA prüft die kopierte Textfassung vor der Erfolgsmeldung; die
Notizkopie wird anschließend nicht automatisch aus der Zwischenablage entfernt.

### Aus einer Notiz eine Checkliste machen

Zum Beispiel: Titel „Einkauf Samstag“, Text:

```text
- [ ] Milch
- [x] Brot
- Äpfel
```

1. Wähle **Notiz als neue Checkliste**.
2. Prüfe Titel, Anzahl, Haken und alle Einträge in den Details der Vorschau.
3. Bestätige. Die vollständige neue Liste ist danach unter **Betrieb → Listen**
   auswählbar. Im Beispiel ist Brot bereits erledigt.

Jede nicht leere Textzeile wird ein Eintrag; Aufzählungen, Nummerierungen und
Markdown-Haken werden erkannt. Die Notiz und ihr offener Entwurf bleiben
unverändert. Namenskonflikte, doppelte/ungültige Einträge und ein inzwischen
geänderter Listenstand werden vollständig abgelehnt. Speicherung ist erforderlich;
Notizen im Papierkorb müssen zuerst wiederhergestellt werden.

## Lokale Listen

### Eine Liste erstellen

1. Öffne **Betrieb → Listen**.
2. Gib einen Namen ein und klicke **Liste anlegen**, oder wähle **Einkauf**,
   **Reise** bzw. **Arbeitsbeginn** und prüfe die sichtbare Vorlage.
3. **Vorlage als neue Liste** legt sie unter deinem eingegebenen Namen an;
   ohne eigenen Namen wird der Vorlagenname verwendet.
4. Ergänze einzelne Einträge mit **Hinzufügen** oder mehrere mit **Mehrere Einträge**.

Im Dialog **Mehrere Einträge** gilt ein Eintrag pro Zeile. Einfache Zeilen,
`- Milch`, Nummerierungen und `- [x] Brot` sind möglich. Prüfe Vorschau und Details;
erst deine Bestätigung übernimmt alle Einträge gemeinsam. Vorhandene Einträge
bleiben erhalten. Dateien und Zwischenablage werden nicht automatisch eingelesen.

Es sind höchstens **20 Listen** mit jeweils **200 Einträgen**, **80 Zeichen
Listenname** und **240 Zeichen pro Eintrag** möglich. Doppelte Texte, ungültige
Zeilen oder eine Überschreitung führen zu keiner Teilübernahme.

### Einträge bearbeiten und abhaken

Ein Haken erledigt ausschließlich den Listeneintrag. Für eine Textkorrektur
markiere die Tabellenzeile und wähle **Ausgewählten Eintrag bearbeiten**.
Der Haken bleibt erhalten. **Eintrag entfernen** und **Liste entfernen**
benötigen eine Bestätigung. Auch eine gefilterte Zeile bleibt dem richtigen
Eintrag zugeordnet.

Listen sind unabhängig von Backend-Aufgaben und starten keine Bestellungen
oder anderen Aktionen. Jede Änderung wird lokal gespeichert und braucht den
Modus mit Speicherung.

### Listen wiederverwenden

- **Als neue Liste kopieren**: neuer Name, dieselben Eintragstexte, alle Haken offen.
  Das Original bleibt erhalten.
- **Alle wieder öffnen**: nach Bestätigung alle Haken der ausgewählten Liste
  zurücksetzen; auch derzeit ausgeblendete Einträge.
- **Liste umbenennen**: den bestehenden Namen ändern, ohne Einträge zu verlieren.

Vorlagen und Kopien überschreiben keine vorhandenen Listen.
Gespeicherte Listen bleiben nach einem Neustart erhalten.

### Suchen, filtern und exportieren

Das Suchfeld findet wörtlichen Text innerhalb der ausgewählten Liste.
**Nur offene Einträge** blendet erledigte aus. Beide Filter lassen sich
kombinieren; die Anzeige nennt sichtbare und gesamte Einträge.
Beim Abhaken verschwindet ein Eintrag aus der offenen Ansicht, bleibt aber gespeichert.

**Sichtbare Einträge als Markdown exportieren** schreibt ausschließlich die
angezeigten Einträge mit ihren Haken in eine gewählte Datei. Der Export nennt
Suchtext und Offen-Filter. Für einen vollständigen Export lösche den Suchtext
und deaktiviere **Nur offene Einträge**. Kopieren und Wiederöffnen beziehen sich
immer auf die ganze Liste.

## Aufgaben im Blick

Unter **Betrieb → Aufgaben** sind Priorität und Termine sichtbar.
Sortiere nach Dringlichkeit, Fälligkeit oder Titel. **Heute fällig oder überfällig**,
**Überfällig** und **Hohe Priorität** zeigen passende offene Aufgaben.
Termine verwenden Europe/Vienna; erledigte Aufgaben gelten durch diese Filter
nicht als überfällig.

**Sichtbare Aufgaben als Markdown speichern** exportiert die aktuelle Ansicht:
Titel, Beschreibung, Status, Priorität und gegebenenfalls Fälligkeit.
Aktionsparameter und Ausführungsergebnisse werden nicht übernommen.
Ein veralteter Backend-Stand wird im Export gekennzeichnet.

## Einheiten umrechnen

Diese Chatbefehle benötigen kein Sprachmodell und funktionieren im Offline-Desktop:

| Eingabe | Größe |
|---|---|
| `Mica, rechne 2,5 kg in Gramm um` | Masse |
| `12 Zoll in cm` | Länge |
| `500 ml in Liter` | Volumen |
| `1 Hektar in m2` | Fläche |
| `1,5 Stunden in Minuten` | Zeit |
| `32 Fahrenheit in Celsius` | Temperatur |

Die Anzeige verwendet zwölf signifikante Stellen. Umrechnungen verbinden nur
Einheiten derselben Größe: Kilogramm in Liter braucht etwa eine Dichte.
Währungen und Cups sind nicht unterstützt. Ein bereits laufendes Backend
muss neu gestartet/gebaut werden, um neue Chatbefehle zu laden.

## Rechner

Im Chat: `rechne (5 + 3) * 2`, `was ist 0,1 + 0,2` oder
`Was sind 15 Prozent von 80`. MICA berechnet lokal mit Dezimalarithmetik,
auch im Offline-Desktop ohne Speicherung. Unterstützt sind +, -, *, / und
Klammern; die Anzeige verwendet höchstens zwölf signifikante Stellen.

## Dokumentinfos und lokale Suche

Unter **Dateien → Infos / Suche** siehst du Wort-/Zeichenzahl der ausgewählten
Dokumente und eine geschätzte Lesedauer mit 200 Wörtern pro Minute.
Die Befehle `Wörter zählen`, `Zeichen zählen` und `Dokumentinfos` zeigen die
Zählung auch im Offline-Desktop ohne Speicherung.

Gezählt und durchsucht wird die bereits eingelesene Textversion. Kürzungen und
nachträgliche Dateiänderungen werden gekennzeichnet. Die wörtliche Suche in
angehakten Dokumenten zeigt Dokumentname, Textzeile und Ausschnitt; `.*` bleibt
normaler Text. Zusätzliche Dateien werden nicht gelesen, Texte nicht an ein Modell gesendet.

## Kennwort erzeugen

Unter **Betrieb → Kennwort** erzeugst du lokal ein zufälliges Kennwort mit
12–128 Zeichen, standardmäßig 20. Die Anzeige ist maskiert; **Kopieren**
übernimmt es auf deinen Klick in die Zwischenablage. Es wird nicht im Chat
oder in Dateien gespeichert.

Nach 60 Sekunden oder beim Verlassen der Seite entfernt MICA die Anzeige und
die noch unveränderte eigene Zwischenablagekopie. Neu kopierter fremder Text
bleibt erhalten. Der Windows-Zwischenablageverlauf bleibt davon unberührt.

## Große Dateien finden

Unter **Betrieb → Dateigrößen** wählst du einen Ordner. MICA liest Dateinamen und
logische Größen und zeigt die größten 20 Dateien. Dateiinhalte werden nicht
geöffnet, Dateien nicht verändert. Links und Windows-Reparse-Punkte werden
übersprungen; UNC-Netzwerkfreigaben abgelehnt.

Du kannst abbrechen. Abbruch, erreichtes Budget und nicht lesbare Bereiche
führen zu einer ausdrücklich gekennzeichneten Teilprüfung.
Logische Größe und belegter Speicherplatz können voneinander abweichen.

## Wenn etwas nicht klappt

| Meldung oder Situation | Nächster Schritt |
|---|---|
| Speicherung ist deaktiviert | Für gespeicherte Änderungen den Modus mit Speicherung verwenden; Notizentwurf vorher kopieren |
| Daten wurden inzwischen geändert | Listen mit **Aktualisieren** neu laden; bei Notizen den Entwurf zuerst kopieren, dann **Neu laden** |
| Notiz-/Listenlimit erreicht | Nicht benötigte Einträge entfernen; bei Notizen zählt der Papierkorb mit |
| Doppelte Namen oder Einträge | Eindeutigen Namen bzw. unterschiedliche Texte verwenden; Übernahme erneut prüfen |
| Datei konnte nicht exportiert werden | Speicherort und Rechte prüfen; eine bestehende Datei bleibt bei gescheitertem Dateiaustausch erhalten |
| Aufgaben zeigen einen alten Stand | Backend-Verbindung prüfen und Aufgaben aktualisieren |
| Neuer Reiter oder Befehl fehlt | Aktualisierten Desktop neu starten; Backendbefehle nach Neubau/Neustart laden |

Abbruch eines Dateidialogs ändert die Notiz oder Liste nicht. Bei Exporten kann
ein Hinweis auf eine inzwischen ältere Ansicht erscheinen; aktualisiere vor
einem erneuten Export, wenn du den neuesten Stand benötigst.

Die dokumentierten Bedienwege sind im Quellcode und automatisierten Tests
geprüft. Eine aktuelle Prüfung des sichtbaren Desktops, Audio und externer Konten
ist separat erforderlich: [Prüfstand und Grenzen](MICA_IMPROVEMENTS_PROGRESS.md).
