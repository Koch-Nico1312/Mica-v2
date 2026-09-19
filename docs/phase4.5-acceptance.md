# Phase 4.5 – Technische Abnahme & Audit (Wahrnehmung & Präsenz)

Stand: 2026-09-19. Phase 4.5 schließt die Perzeptions- und Präsenzlücken gegenüber JARVIS/FRIDAY (Iron Man) sowie die mobilen Notfalleinsichten aus Sam (Swift & Hawk). Standardmäßig sicher deaktiviert (`MICA_PHASE45_ENABLED=0`).

## Implementierter Funktionsumfang

1. **Vision / Kamera-Input (`VisionEngine`)**:
   - Strukturierte Bildanalyse mit vier Arbeitsmodi: `general`, `room_state`, `server_rack`, `object_detection`.
   - Spezifische Rack-Diagnostik: Erkennung von LED-Indikatoren (Power/Disk/Alert: Grün, Amber, Rot), offene/verriegelte Racktüren und Kabelzustände.
   - Bildvalidierung: Maximale Nutzlast 5 MB, Formatprüfung (PNG, JPEG, WebP) und Header-Dimensionsparsing.
   - **Privacy Guard**: Roh-Bildbytes werden niemals in den Brain-Markdown-Dateien oder in der Hash-Auditkette (`events.jsonl`) gespeichert. Es werden ausschließlich kryptographische SHA-256-Prüfsummen und sanitierte Diagnosetexte auditiert.
   - Endpunkte: `GET /v1/vision/status`, `POST /v1/vision/analyze`, `POST /v1/vision/capture`.

2. **Ambient Awareness / Proaktives Melden (`AmbientMonitor`)**:
   - Eigenständige Trigger-Logik zur kontinuierlichen Beobachtung von System- und Umgebungszuständen (Servermetriken, bevorstehende Zeitpläne/Kalender, optische Sensoren).
   - Prioritätsstufen: `info`, `notice`, `warning`, `critical`.
   - Anti-Spam Cooldown: Deduplizierung verhindert Alarmfluten bei gleichbleibenden Zuständen.
   - Konfigurierbare Ruhezeiten (DND): Unterdrückt nicht-kritische Ereignisse während definierter Nachtstunden; nur `critical`-Meldungen durchbrechen Ruhezeiten.
   - Nahtlose Integration in den Scheduler-Durchlauf (`run_cycle`).
   - Endpunkte: `GET /v1/ambient/events`, `POST /v1/ambient/events/{id}/acknowledge`, `GET /v1/ambient/status`, `POST /v1/ambient/evaluate`.

3. **Sprach-Adressierungserkennung / Proactive Audio (`AddressingDetector`)**:
   - Inspiriert: Erkennt zuverlässig, ob Sprache direkt an MICA gerichtet ist oder aus Hintergrundgesprächen, Fernsehen/Medien oder Telefonaten stammt.
   - Mehrstufige Klassifikation:
     - Direkte Namens-Vokative (`Mica`, `JARVIS`, `Computer`) -> Hohe Konfidenz (0.95+).
     - Direkte Befehls-/Frageformulierungen (`kannst du bitte`, `wie spät ist es`, `zeige mir`, `schalte`) -> Hohe Konfidenz (0.85+).
     - 2. Person Vokative (`du`, `dir`, `dein` mit Fragepronomen).
     - Ausschlussmuster für diffuse Hintergrundgespräche und Broadcast-Medien (`er hat gesagt`, `in den nachrichten`, `hallo mama`).
   - Schützt vor Fehlaktivierungen in Always-On- und Satelliten-Umgebungen.
   - Endpunkt: `POST /v1/addressing/evaluate`.

4. **Physische Präsenz / Hardware-Anker (`SatelliteRegistry` & `SatelliteNodeClient`)**:
   - Ermöglicht ortsfeste Hardware-Anker (z. B. Raspberry Pi oder Mini-PC im Raum) mit Mikrofon, Lautsprecher und LED-Status.
   - Dynamische Satelliten-Registrierung mit Raum-Zuweisung (`Labor`, `Wohnzimmer`, `Serverraum`).
   - Heartbeat-Monitoring inklusive Hardware-Telemetrie (CPU-Temperatur, Uptime, Hostname) und automatischer Offline-Erkennung bei Timeout.
   - Gezielte Raum-Sprachdurchsagen (`queue_announcement`) sowie globale Broadcasts.
   - Endpunkte: `POST /v1/satellites/register`, `GET /v1/satellites`, `POST /v1/satellites/{id}/heartbeat`, `POST /v1/satellites/announce`.

5. **Auth- & Bestätigungs-Layer für autonome Aktionen (`AutonomousActionGuard`)**:
   - Mehrstufiges Rechtesystem für Aktionen, die autonom aus Vision- oder Ambient-Triggern vorgeschlagen werden:
     - **Tier 0 (Lesend / Telemetrie)**: Autonom sofort zulässig (`system.status`, `docker.status`, `vision.inspect_rack`).
     - **Tier 1 (Reversibel / Reparatur)**: Autonom nur ausführbar, wenn vom Betreiber über Richtlinie (`auto_allow_tier1`) explizit vordefiniert; andernfalls Freigabe-Ticket erforderlich.
     - **Tier 2 (Destruktiv / Sensitiv)**: Vollständiges Ausführungsverbot für autonome Trigger (`docker.lifecycle`, `system.admin`, `files.delete`). Erzeugt zwingend ein fälschungssicheres, befristetes Freigabe-Ticket für den Menschen.
   - Integration mit dem globalen Not-Aus: Bei aktivem Not-Aus werden alle autonomen Aktionen sofort blockiert und offene Tickets unwiderruflich entwertet.
   - Endpunkte: `GET /v1/autonomous-guard/tickets`, `POST /v1/autonomous-guard/tickets/{id}/resolve`, `PATCH /v1/autonomous-guard/policies`.

6. **Mobiler Notfall-Zugriff (`EmergencyService` & `emergency.html`)**:
   - Swift & Hawk / Sam-inspirierter Notfallmodus für unterwegs.
   - Token-basierte Authentifizierung mit Brute-Force-Schutz (Lockout nach 5 Fehlversuchen).
   - Minimalistische, extrem schnelle Notfall-Webansicht (`web_ui/emergency.html`), die auch bei schwacher Mobilfunkverbindung sofort lädt.
   - Direkter Ein-Klick-Not-Aus (System-weiter Stopp aller Pläne, WebSockets und Aktionen), Status-Dashboard und Remote-Freigabe von autonomen Tickets.
   - Endpunkte: `POST /v1/emergency/login`, `GET /v1/emergency/overview`, `POST /v1/emergency/stop`, `POST /v1/emergency/resume`, `POST /v1/emergency/tickets/{id}/resolve`.

---

## Verifikation & Testergebnisse

- `python -m unittest discover -s tests -p "test_*.py"`: **204 Tests bestanden (0 Fehler, 0 Übersprungen)**.
- `python -m unittest tests/test_phase45_perception.py`: **18 Phase-4.5-Spezifische Akzeptanztests bestanden**.
- `python -m compileall -q actions config core memory mica_core tests local_main.py main.py ui.py`: **Vollständige Syntax- und Typenvalidierung bestanden**.
