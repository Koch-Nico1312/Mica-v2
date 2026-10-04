# Phase 3A: Task Manager und einfache Automationen

## Betriebsmodell

Phase 3A erweitert den vorhandenen lokalen Scheduler. Aufgaben und Regeln liegen
additiv in derselben SQLite-Datei; bestehende Zeitpläne bleiben kompatibel.
Es gibt keinen freien Regelcode, keine Shell-Ausführung und keinen neuen
Netzwerkpfad.

Der Pilot ist standardmäßig aus:

- `MICA_PHASE3_ENABLED=1` schaltet die Task-Manager-API frei.
- `MICA_AUTOMATIONS_ENABLED=1` erlaubt zusätzlich Aktivierung und Auswertung
  der Regeln.
- Jede Regel startet deaktiviert. Die erstmalige Aktivierung benötigt eine
  parametergebundene lokale Freigabe.
- Der Not-Aus stoppt sowohl fällige Zeitpläne als auch Regeln.

## Unterstützte Regeln

- `task.overdue` → `reminder.create`
- `schedule.failed` → `task.create`

Jede Regel besitzt mindestens 60 Sekunden Cooldown, ein endliches Budget von
höchstens 100 Läufen und eine Deduplizierung je betroffenem Objekt.

## Automatisch geprüft

- [x] Additive SQLite-Migration für bestehende Schedule-Daten.
- [x] Aufgabenvalidierung und erlaubte Statusübergänge.
- [x] Endliche Regeln, Cooldown, Budget und Deduplizierung.
- [x] API bleibt bei deaktiviertem Pilot geschlossen.
- [x] Aktivierung benötigt eine lokale Freigabe.
- [x] Trockenlauf verändert keine Daten.
- [x] Not-Aus verhindert Schedule- und Regelausführung.
- [x] Ein fehlerhafter Zeitplan stoppt den Scheduler nicht und erzeugt genau eine lokale Folgeaufgabe.
- [x] Backup/Restore stellt Markdown und Audit wieder her und baut den SQLite-Index neu auf.
- [x] PWA zeigt Aufgaben, Regeln, Restbudget und Fehlerstatus.
- [x] Phase-0/1/2-Regressionen bleiben grün.

## Isolierte Laufzeitabnahme

- [x] Pilot mit separatem Testdatensatz aktiviert und eine einmalige Aufgabe angelegt.
- [x] Zwei endliche Wiederholungen mit verknüpfter Aufgabe ausgeführt.
- [x] Eine überfällige Aufgabe genau einmal in eine lokale Erinnerung überführt.
- [x] Einen fehlgeschlagenen Zeitplan isoliert und genau einmal in eine Aufgabe überführt.
- [x] Aufgabe, Regel, Aktivstatus, Zeitplan und Verknüpfung nach Prozessneustart erneut gelesen.
- [x] Aktiver Not-Aus hielt einen bereits fälligen Zeitplan bis zur Freigabe zurück.

## Noch im echten Betrieb abzunehmen

- [ ] Pilot auf dem vorgesehenen MICA-System bewusst aktivieren; die Standardwerte bleiben bis dahin `0`.
- [ ] Phase 3A mehrere Tage stabil im Alltag verwenden.

Phase 3A ist technisch und mit isolierten Laufzeitdaten abgenommen, aber noch
nicht im echten Alltag abgeschlossen.
