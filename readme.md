# MICA V2

MICA ist ein persönlicher Assistent für Windows. Du kannst mit ihm schreiben,
sprechen, ausgewählte Dokumente nutzen und Aufgaben planen. Die Oberfläche
läuft auf deinem PC; das lokale Backend stellt Sprachmodelle, Spracherkennung,
Sprachausgabe und die geschützte Ausführung von Aktionen bereit.
Cloud-Anbieter und externe Verbindungen werden ausdrücklich eingerichtet.

## Schnell starten

1. Öffne **Start MICA.cmd** per Doppelklick.
2. Warte, bis das Startfenster Docker, Dienste und die lokale HTTPS-Verbindung
   geprüft hat. Beim ersten Start können Dienstabbilder und Modelle vorbereitet werden.
3. Öffne MICA. Unter **Betrieb** findest du Aufgaben, Diagnose, Backups und
   die neuen lokalen Alltagshilfen. Die Seite trägt die Überschrift „MICA im Alltag“.

Für die Einrichtung über PowerShell:

```powershell
.\install_and_start.ps1
```

Der vollständige Starter öffnet die kanonische Oberfläche
`desktop/local_main.py`. Er übernimmt die konfigurierte HTTPS-Adresse und
Caddy-Zertifizierungsstelle aus der Backend-Einrichtung. Zugangsdaten werden
über den Windows Credential Manager bereitgestellt. Vorhandene Modelle,
Hindsight-Konfiguration und die erlaubten Host-Aktionen werden berücksichtigt.

Bei einem Startfehler bietet das Startfenster Wiederholen und Hilfe zur
Backend-Einrichtung an. Eingeschränkte Phase-0-Funktionen werden angezeigt.
Ein erfolgreicher Verbindungscheck ersetzt den Mikrofon- und Lautsprechertest nicht.
Der Konsolenstart bleibt über `python -m desktop.start_mica --console` verfügbar.

## Was möchtest du tun?

| Dein Ziel | Anleitung |
|---|---|
| Mikrofon, Satzende-Pause und Unterbrechen einstellen | [Sprache einrichten](docs/voice-improvements.md) |
| Mit Text, Sprache und ausgewählten Dateien arbeiten | [Gespräche und Dokumente](docs/dialog-improvements.md) |
| Rechnen, Einheiten umrechnen, Listen führen oder große Dateien finden | [Neue Alltagshilfen](docs/EVERYDAY_IMPROVEMENTS.md) |
| Programme öffnen, Timer korrigieren und Fenster prüfen | [Alltagshilfe](docs/daily-assistance.md) |
| Aufgaben, Erinnerungen, Diktate und Lernkarten nutzen | [Aufgaben und Weiterarbeiten](docs/assistance-extensions.md) |
| Tagespläne erstellen und offline abgleichen | [Tagesplanung und Offline](docs/planning-offline-results.md) |
| Planänderungen, Kalenderdateien und Lernblöcke prüfen | [Flexible Planung](docs/planning-extensions.md) |
| Einen Projektstand sichern und wieder aufnehmen | [Projektassistenz](docs/project-assistance.md) und [Arbeitsstände](docs/productivity-extensions.md) |
| Lernen und Weiterentwicklung einrichten | [Weiterentwicklung](docs/evolution.md) |
| Backend auf Windows, ZimaOS oder Proxmox betreiben | [Backend-Einrichtung](backend/README.md) |
| Weitere Anleitungen oder technische Details finden | [Dokumentationsübersicht](docs/README.md) |

## Aktueller Stand

Die zehn Erweiterungen des ersten Verbesserungszyklus sind im Quellcode und
ihren Bedienwegen implementiert. Die [Funktionsübersicht](docs/EVERYDAY_IMPROVEMENTS.md)
zeigt, wo du sie findest; der [Prüfstand](docs/MICA_IMPROVEMENTS_PROGRESS.md)
trennt Implementierung, Tests und noch offene Abnahmen.

Stand 11.10.2026: **953 Tests und 79 Untertests bestanden**, ein Test mit einem
separat benötigten Dienst wurde ausgeschlossen. Zwei Tests der Text- und
Codeaufbereitung bestanden zusätzlich. Die echte Bugbot-Prüfung ist noch offen,
weil der verlangte Reviewer in dieser Sitzung nicht verfügbar ist. Die
[Jira-Anbindung](docs/JIRA_MCP.md) ist bis zum Nachmittag zurückgestellt.

Das Projekt ist mit [GitHub](https://github.com/Koch-Nico1312/Mica-v2) verbunden.
Die aktuellen Verbesserungen werden auf dem Branch **MICA-Improvements**
veröffentlicht. Die alte Git-Neueinrichtung ist ein historischer Arbeitsstand,
keine Beschreibung des heutigen Repositorys: [Git und Updates](docs/Git-Vorbereitung.md).

## Installation und Updates

`install_and_start.ps1` richtet die Desktop-Abhängigkeiten ein. Für ein
automatisches Quellcodeupdate braucht der Installer einen sauberen Arbeitsstand
und eine geprüfte Wiederherstellungssicherung des aktuellen Commits, höchstens
24 Stunden alt. Erstelle sie nach dem Entsperren unter
**Betrieb → Backup → Update-Sicherung erstellen**.

Fehlt diese Sicherung, wird das Update übersprungen; der Start bleibt möglich.
Die Sicherung umfasst Daten und committeten Quellcode, jedoch keine Python-
Umgebung, Modelle oder Credential-Manager-Zugangsdaten.

| Option | Wirkung |
|---|---|
| `-NoUpdate` | Prüfung auf Quellcodeupdates überspringen |
| `-SetupOnly` | Installation vorbereiten und prüfen, ohne MICA zu öffnen |

Für einen manuellen UI-Start kannst du die lokale HTTPS-Adresse mit
`MICA_CORE_URL` und die Zertifizierungsstelle mit `MICA_CORE_CA_FILE` angeben.
Der vollständige Starter übernimmt diese Einstellungen aus der lokalen
Backend-Konfiguration. Zertifikatsprüfung bleibt aktiviert.

## Lokales Backend einrichten

Die vollständige Anleitung steht in [backend/README.md](backend/README.md),
einschließlich Windows, ZimaOS, Proxmox-VM und der eingeschränkten CPU-LXC-Variante.

1. Kopiere `backend/.env.example` nach `backend/.env`. Konfiguriere Datenpfad,
   Modelle und HTTPS-Adresse. Richte API-/Freigabezugang und Browser-Passwort
   nach [API und LAN-Zugriff](docs/api-access.md) ein.
2. Lege die benötigten lokalen Modelle gemäß Backend-Anleitung bereit.
   Die Standard-Spracherkennung ist [Parakeet Redux auf CPU](docs/parakeet-redux.md);
   Whisper ist eine ausdrücklich wählbare Alternative. Parakeet ist nativ auf
   Windows-CPU weiterhin nicht als funktionierender Modellpfad bestätigt.
3. Starte unter Windows über `python -m backend.windows_launcher`; für Linux
   nutze die dokumentierten Compose-Befehle.
4. Prüfe Dienstzustand und HTTPS-Verbindung vor Desktop- oder LAN-Nutzung.

Modellcontainer und Werkzeug-Broker erhalten keinen Docker-Socket.
Host-Aktionen laufen bei entsprechender Einrichtung in einem getrennten,
durch gegenseitige TLS-Authentifizierung geschützten Host-Agenten. Fähigkeiten,
Freigaben, Aktionsprotokoll und Not-Aus werden vor der Ausführung geprüft.

## Optionale Funktionen und Datenschutz

Recherche, Automatisierung, Serverfunktionen, Dream-RSI, Laya, native
Computersteuerung und externe Verbindungen besitzen eigene Einrichtung und
Freigabegrenzen. Aktiviere sie anhand ihrer jeweiligen Anleitung.

- [Dream-RSI und Laya](docs/dream-rsi.md): lokale Bewertung und begrenzte
  Weiterentwicklung. Laya bewertet Relevanz; es erteilt keine Aktionsrechte.
- [Hindsight](docs/hindsight.md): optionales Langzeitgedächtnis für ausgewählte
  Gesprächsausschnitte und Aufgabenberichte. Markdown bleibt die maßgebliche
  Quelle, lokale Suche bleibt bei Ausfällen nutzbar. Reflexionen sind als
  unbestätigte Ableitungen mit Quellen gekennzeichnet.
- [Hindsight-Pilot vom 30.09.2026](artifacts/hindsight-pilot/acceptance.md):
  historischer Test mit echtem Server. Drei Beispiele zeigten keinen allgemeinen
  Qualitätsvorteil gegenüber lokaler Suche; Standardaktivierung bleibt aus.

Zugangsdaten gehören in den Credential Manager beziehungsweise die lokale,
nicht veröffentlichte Konfiguration. Der Windows-Backend-Starter übernimmt
nur ausdrücklich konfigurierte Credential-Namen. Cloud-Nutzung und die
Übertragung privater Inhalte brauchen eine eigene Konfiguration.

## Projektaufbau und Entwicklung

| Ordner | Inhalt |
|---|---|
| `desktop/` | Windows-Oberfläche, lokaler API-Client, Audio und lokale Aktionen |
| `backend/` | API, Compose-Dienste, Modelle, Broker und optionaler Host-Agent |
| `mica_shared/` | Gemeinsame Befehls-, Sprach- und Dateiverträge |
| `.mica-data/` | Private lokale Laufzeitdaten; von Git ausgeschlossen |
| `docs/` | Bedienung, Einrichtung, Architektur und Prüfergebnisse |
| `tests/`, `backend/tests/` | Automatisierte Prüfungen |
| `scripts/` | Prüfungen von Quellcode und Dokumentationslinks |
| `legacy/` | Archivierter Gemini-Live-Pfad; außerhalb des normalen Startpfads |

Desktop und Backend sind getrennte Programme. Details stehen in
[Architektur](docs/Architektur.md) und [Projektübersicht](docs/Projekt-Übersicht.md).
Lokale Prüfbefehle findest du unter [Repository-Pflege](docs/repository-maintenance.md).
Die [Effizienzänderungen](docs/code-efficiency.md) dokumentieren Indexierung,
Datenbankzugriffe, begrenzte Audit-Prüfung und Messungen.

Erfolgreiche Tests belegen die geprüften Codepfade. Ob eine konkrete Installation
mit Zertifikaten, Modellen, Mikrofon, Lautsprecher und externen Konten funktioniert,
wird separat nach den [Abnahme-Anleitungen](docs/README.md#phasen-und-abnahme) geprüft.
Historische [Selbstquellcode-Funktionen](docs/self-source-access.md),
[Sprachrichtlinie](docs/phase1-voice.md) und [Recherche/Lernen](docs/phase2-learning.md)
bleiben über den Dokumentationsindex erreichbar.

## Lizenz

Siehe [LICENSE](LICENSE).
