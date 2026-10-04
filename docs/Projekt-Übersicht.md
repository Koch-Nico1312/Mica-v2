# MICA V2 – Projektübersicht

Stand: 2026-10-04. MICA V2 besteht aus einer lokalen Windows-Desktop-App und
einem separat gestarteten Backend. Der Desktop ist eine PyQt-Oberfläche mit
Chat- und Spracheingabe. Das Backend stellt die lokale API und die Dienste für
Sprachverarbeitung, LLM-Inferenz, Brain-Suche, Aufgabenplanung und kontrollierte
Aktionen bereit. Desktop und Backend verwenden getrennte Module und
Laufzeitumgebungen.

## Projektstruktur

```text
desktop/                 Windows-HUD, Audio, API-Client, Aktionen, Ressourcen
backend/                 FastAPI, gemeinsame Dienste, Scheduler, Docker Compose
mica_shared/             Gemeinsame Verträge ohne UI-/Backend-Abhängigkeiten
legacy/                  Archivierter Gemini-Live-Code und historische Tests
scripts/                 Repository- und Dokumentationsprüfung
backend/windows_host_agent/
                         Separater nativer Windows-Dienst für freigegebene Aktionen
docs/                    Bedienung, Architektur, Sicherheitsgrenzen, Abnahmen
tests/                   Desktop-/Projektprüfungen
backend/tests/           API-, Service- und Deploymentprüfungen
.mica-data/              Desktop-lokale Laufzeitdaten; nicht versioniert
backend/.env             Container-Zielpfad und Betriebsparameter; nicht versioniert
Start MICA.cmd           Lokaler Gesamtstart von Backend und Desktop
install_and_start.ps1    Desktop-Abhängigkeiten vorbereiten und UI starten
```

Die Verzeichnisse `desktop/core/` und `backend/services/common/` sind keine
gemeinsame Bibliothek. Die Desktop-App spricht mit dem Backend über dessen
lokalen HTTPS-Endpunkt. Standardmäßig ist das `https://mica.local`; für eine
abweichende lokale Installation dienen `MICA_CORE_URL` und optional
`MICA_CORE_CA_FILE`.

## Laufzeit und Bereitstellung

`install_and_start.ps1` richtet eine lokale, gepinnte Python-3.13-Umgebung ein
und startet die Oberfläche. `Start MICA.cmd` führt mit dem Python aus PATH
`desktop.start_mica` aus: Docker Desktop starten, bestehende lokale
Konfiguration ergänzen, Compose starten, HTTPS prüfen und die UI öffnen.
Dieser Gesamtstart setzt installierte Python-Abhängigkeiten und Docker voraus.
Für einen anderen Backend-Host kann die UI weiter separat gestartet werden.
Auf Windows liest
`backend/windows_launcher.py` die ausdrücklich erlaubten Zugangsdaten-Namen
aus Windows Credential Manager und übergibt deren Werte dem Compose-Prozess,
ohne sie in `.env` zu schreiben.

Für Linux-Server sind ZimaOS und eine Proxmox-VM dokumentierte Zielpfade. LXC
ist eine eingeschränkte CPU-only-Testvariante. Der Backend-Leitfaden beschreibt
erforderliche lokale Modelle, Volumes, Preflight, HTTPS und Backup-Drill:
[backend/README.md](../backend/README.md).

## Funktionsbereiche

- **Desktop und Sprache:** lokaler API-Client, Text-Chat, Push-to-talk,
  Unterbrechung, Stummschaltung und optionales lokales Wake-Word.
- **Lokale Inferenz:** llama.cpp-Server im Backend; lokaler Fallback ist als
  Compose-Profil optional. Cloud-Provider sind gesondert zu konfigurieren.
- **Wissensspeicher:** Markdown-Dateien sind die maßgeblichen Brain-Daten;
  Suchindizes werden lokal aufgebaut und können neu erstellt werden.
- **Optionales Langzeitgedächtnis:** Hindsight übernimmt ausgewählte kurze
  Nutzeraussagen und Werkzeugberichte. Exakte lokale Treffer behalten Vorrang;
  explizite Reflexionen bleiben gekennzeichnete Ableitungen mit Quellen.
  Die Erweiterung betrifft das Backend und ist standardmäßig ausgeschaltet.
  Einrichtung und Grenzen stehen in [hindsight.md](hindsight.md).
- **Aktionen und Freigaben:** Capability-Regeln, Broker, Audit, begrenzte
  Freigaben und Not-Aus schützen externe oder native Aktionen.
- **Sprachdienste:** Whisper für STT; die TTS-Auswahl ist providerbezogen und
  kann lokale oder ausdrücklich aktivierte Cloud-Stimmen verwenden.
- **Planung und Automatisierung:** Scheduler und Phasenfunktionen sind
  separat abschaltbar und standardmäßig weitgehend deaktiviert.
- **Recherche und Selbstverbesserung:** Phase 2, Phase 4, Dream-RSI und
  optionale Integrationen haben eigene Aktivierungs- und Abnahmebedingungen.

Die detaillierte Zuordnung der Dienste und Sicherheitsgrenzen steht in
[Architektur.md](Architektur.md). Die Abnahmeseiten im
[Dokumentationsindex](README.md#phasen-und-abnahme) halten Code-Unterstützung,
Testnachweise und externe Zielhost-Prüfungen getrennt.

## Konfigurationsregeln

- Desktop- und Backend-Konfiguration sind getrennt: `.env.example` im
  Projektstamm bezieht sich auf optionale Desktop-/Feature-Einstellungen;
  `backend/.env.example` beschreibt Docker-Deploymentparameter.
- Beide Beispieldateien enthalten absichtlich keine echten Schlüssel.
- Die meisten erweiterten Fähigkeiten bleiben standardmäßig ausgeschaltet.
- Feature-Flags ändern die Konfiguration, sind aber kein Nachweis, dass eine
  Funktion mit echten Modellen, Hardware, Zertifikaten oder Providern geprüft
  wurde.

## Aktueller Abnahmestatus

Der [Hindsight-Pilot vom 30. September 2026](../artifacts/hindsight-pilot/acceptance.md)
hat Speicherung, Suche, Reflexion, Ausfall, Neustart, Korrektur und Löschung
mit einem echten lokalen Server geprüft. Die drei Testbeispiele zeigen keinen
Suchvorteil gegenüber dem lokalen Brain; CPU-Reflexion dauerte rund 131 Sekunden.
Das belegt die geprüften Funktionen, keine allgemeine Qualitätssteigerung oder
Produktionsabnahme. Die produktive Konfiguration wurde nicht aktiviert.

Implementierung und automatisierte Tests belegen nur ihre geprüften Pfade. Die
konkreten Betriebsnachweise hängen vom Zielsystem ab: Dazu zählen physische
Mikrofon- und Offline-Sprachtests, GPU- und Modell-Lasttests, produktives LAN-
HTTPS/mTLS, Backupziel und echte Provider-Sandboxes. Siehe den datierten
[Backend-Abnahmeaudit](../backend/IMPLEMENTATION_STATUS.md) und führe die dort
genannten Prüfungen für den aktuellen Host erneut aus.
