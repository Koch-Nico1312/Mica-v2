# Neues lokales Projekt vorbereiten

Stand: 2026-10-04. Die bisherige Remote-Verknüpfung und
Plattform-Konfiguration wurden entfernt. Die alten Git-Metadaten im Projektstamm
und im historischen Quellcode-Snapshot wurden außerhalb des Projekts archiviert.
Das neue lokale Repository auf `main` enthält keine Commits, Tags, Remotes oder
alte Reflogs. Aktuelle Quellcodeänderungen und lokale Installationsdaten bleiben
erhalten. Es wurde nichts gestaged oder committet.

Vor dem Neustart wurde das Projekt unter
`C:\Users\kochn_lrehka5\Documents\MICA-Projektsicherungen\vor-git-neustart-20261004-200038`
vollständig gesichert. 3.593 Quellcode- und Git-Dateien wurden anhand ihrer
SHA-256-Prüfsummen mit der Sicherung verglichen; es gab keine Abweichungen.
Die Sicherung enthält private lokale Daten und darf nicht veröffentlicht werden.
Die alten Historien bleiben ausschließlich außerhalb des aktiven Projekts
wiederherstellbar. Ein bisheriges Repository auf einer Hosting-Plattform wurde
nicht gelöscht.

## Dateien vor einem neuen Projektstart prüfen

```powershell
git status --short
git ls-files --others --exclude-standard
git check-ignore .env backend/.env desktop/config/api_keys.json
```

Quellcode, Tests, Dokumentation, Lizenz, Konfigurationsbeispiele und
Dependency-Manifeste können nach Prüfung übernommen werden. Zugangsdaten,
Laufzeitdaten, Datenbanken, Modelle und virtuelle Umgebungen bleiben lokal.
`.gitignore` ist weiterhin vorhanden. Es wurde nichts neu gestaged oder committet.

Führe die [lokalen Prüfungen](repository-maintenance.md#prüfungen) vor dem
ersten Commit aus und stage anschließend gezielt die geprüften Dateien.

## Installation und Updates

Das Projekt besitzt keine Update-Quelle. Der Installer überspringt deshalb
Quellcodeupdates; die lokale Installation und der Start bleiben verfügbar.
Eine neue Remote-Anbindung kann später bewusst eingerichtet werden.
