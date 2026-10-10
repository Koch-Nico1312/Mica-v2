# Git, Sicherungen und Updates

Stand: **11.10.2026**. Das aktive Projekt besitzt Commits und ist über `origin`
mit [Koch-Nico1312/Mica-v2](https://github.com/Koch-Nico1312/Mica-v2) verbunden.
Die laufenden Verbesserungen liegen auf **MICA-Improvements**. Die Beschreibung
eines leeren Repositorys vom 04.10. ist inzwischen ein historischer Stand.

## Vor einem Commit

Prüfe zuerst, welche Dateien sich geändert haben:

```powershell
git status --short
git ls-files --others --exclude-standard
git check-ignore .env backend/.env desktop/config/api_keys.json
```

Übernimm gezielt geprüften Quellcode, Tests, Dokumentation, Lizenz,
Konfigurationsbeispiele und Abhängigkeitsdateien. Zugangsdaten, Laufzeitdaten,
Datenbanken, Modelle und virtuelle Umgebungen bleiben lokal. Führe die
[passenden lokalen Prüfungen](repository-maintenance.md#prüfungen) aus.

Ein lokaler Commit speichert den Stand im Repository. Erst ein erfolgreicher
Push veröffentlicht ihn auf GitHub. Der [Verbesserungsstand](MICA_IMPROVEMENTS_PROGRESS.md)
nennt die bisher veröffentlichten Checkpoints.

## Quellcodeupdates

Für automatische Updates über `install_and_start.ps1` braucht MICA einen
sauberen Arbeitsstand und eine geprüfte Sicherung des aktuellen Commits,
höchstens 24 Stunden alt. Erstelle sie unter
**Betrieb → Backup → Update-Sicherung erstellen** nach dem Entsperren.
Die Sicherung enthält lokale Daten und committeten Quellcode, jedoch keine
Python-Umgebung, Modelle oder Windows-Credential-Manager-Zugangsdaten.

Fehlt eine gültige Sicherung, überspringt der Installer das Quellcodeupdate.
Installation und Start bleiben möglich. `-NoUpdate` überspringt die Updateprüfung
ausdrücklich. Die konkrete Update-Quelle hängt vom Tracking des ausgecheckten
Branches ab; eine vorhandene Remote-Verbindung allein bestätigt kein Update.

## Historischer Git-Neustart vom 04.10.2026

Damals wurden die vorherige Remote-Verknüpfung und Plattform-Konfiguration
entfernt sowie alte Git-Metadaten außerhalb des Projekts archiviert. Das neu
angelegte lokale Repository war zu diesem Zeitpunkt leer. Diese Aussage gilt
für den damaligen Neustart, nicht für den heutigen Arbeitsstand.

Vor dem Neustart wurde eine vollständige Sicherung außerhalb des Projekts
angelegt. Der damalige Prüfbericht dokumentierte 3.593 Quellcode-/Git-Dateien
mit übereinstimmenden SHA-256-Prüfsummen. Diese Sicherung enthält private Daten
und darf nicht veröffentlicht werden. Ein extern gehostetes Repository wurde
durch den lokalen Neustart nicht gelöscht. Die aktuellen Projektdateien und
Installationsdaten wurden erhalten.
