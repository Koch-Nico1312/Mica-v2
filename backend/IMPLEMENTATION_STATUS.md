# MICA – Implementierungs- und Abnahmeaudit

Stand: 2026-09-10. Dieser Audit trennt reproduzierbar lokal bewiesene
Implementierung von Abnahmen, die nur auf dem späteren ZimaOS- oder
Proxmox-Zielhost mit den echten Modellen, Zertifikaten und Providerkonten
erbracht werden können.

## Aktuelle lokale Prüfgrenze

- Alle von Compose gebauten Images (`mica-api`, STT, TTS, Brain-Indexer,
  Broker, Scheduler und Web-UI) sowie das separate Host-Agent-Image wurden
  erfolgreich neu gebaut.
- 45 Core-/API-/Deploymenttests bestanden im gepinnten Python-Image.
- 5 Host-Agent-Sicherheitstests bestanden im Host-Agent-Image.
- 14 PyQt-HUD-Tests bestanden getrennt in der Windows-QA-Laufzeit.
- Die PWA wurde im lokalen Browser als Desktop und bei 390 x 844 Pixeln
  geprüft. Der echte Markdown -> Audit -> Markdown-Rückweg wurde geklickt.
- Ein physisches Windows-Mikrofon lieferte bei 16 kHz 47 Blöcke ohne Overflow;
  40 Blöcke erzeugten einen von null verschiedenen HUD-Pegel. Roh-Audio wurde
  nicht gespeichert.

## Anforderungsmatrix

| Plananforderung | Aktueller Stand | Lokaler Nachweis | Verbleibende Zielabnahme |
|---|---|---|---|
| Acht geplanter Core-Dienste, persistente Volumes und lokale Netzgrenzen | lokal bewiesen | `docker-compose.yml`; Compose-Konfiguration gültig; alle gebauten Images erfolgreich; Modelle erhalten keinen Docker-Socket | Gesamten Stack mit echten Volumes auf ZimaOS oder in der Proxmox-VM starten |
| ZimaOS-Preflight | implementiert | `preflight.py` prüft Docker/Compose, Schreibrechte im Host und Container, Modelle, Ports, DNS/Zeit, HTTPS, Backup sowie NVIDIA/CUDA/llama-Last | Auf dem echten ZimaOS-Host ausführen und JSON-Bericht ablegen |
| Proxmox-Kompatibilität | lokal bewiesen | bevorzugter KVM/QEMU-Linux-VM-Pfad; `docker-compose.lxc.yml` als expliziter CPU-only-LXC-Overlay; 5 Proxmox-Preflighttests; zusammengeführte Compose-Konfiguration gültig | IOMMU/VFIO, PCI-Passthrough, Gast-`nvidia-smi`, Firewall, CA-Vertrauen und Modelllast im echten PVE-Gast |
| Deutscher Offline-Voice-Loop | lokale Dienste real gestartet, physische Abnahme offen | SHA-256-geprüfte Modelle; Qwen antwortet über `/v1/turns` exakt lokal; Piper-Audio wurde von fest auf Deutsch gesetztem Whisper verständlich transkribiert; sieben Core-Container gesund | 20 kontrollierte Sätze über das echte Mikrofon, Offline-Betrieb und TTS-Abbruch physisch abnehmen |
| Markdown als Wahrheit, rebuildbarer FTS-/Vektorindex und Graph | lokal bewiesen | `brain.py`, Backup-Drill und Coretests rekonstruieren SQLite ausschließlich aus Markdown; kein Embedding-API-Egress | Restore mit dem produktiven Backupziel wiederholen |
| Chonkie direkt und reproduzierbar | lokal bewiesen | `chonkie[code]==1.7.0` und `tree-sitter-language-pack==1.8.1`; TokenChunker- und syntaxbewusster CodeChunker-Test im Container | keine lokale Implementierungslücke |
| Retrieval vor Planung und Tool-Dispatch | lokal bewiesen | Orchestrator und Broker suchen vor Policy/Dispatch; kontrollierter Dockerfehler-Test beweist Reihenfolge, Lesson-Einfluss und unveränderte freigegebene Parameter | denselben Drill später gegen den echten mTLS-Host-Agent/Docker-Daemon wiederholen |
| Fehler-Evidenz/Lesson/Testentwurf und Erfolgs-Runbook | lokal bewiesen | unveränderte Evidenz mit SHA-256, Markdown-Verlinkung, Reproduktionsentwurf und Optimierungsanalyse; kontrollierter Fehler -> Lesson -> Retry-Test bestanden | reale Provider-/Dockerfehler zusätzlich sammeln |
| Verlustfreie `long_term.json`-Migration | lokal bewiesen | Roh-JSON-Snapshot plus einzeln suchbare Markdown-Einträge; Migrationstest bestanden | reale Nutzerdatei einmalig migrieren und Archiv vergleichen |
| Browser-Sessions, parametergebundene Freigaben und Policy | lokal bewiesen | HttpOnly-/SameSite-Session, Intent-Header, single-use destructive approvals, widerrufbare reversible Scopes und Manipulationsabwehr getestet | Cookie-/Origin-Verhalten hinter dem produktiven LAN-Zertifikat prüfen |
| Tool-Broker und separater mTLS-Host-Agent | lokal bewiesen, Zertifikatskette extern | Host-Agent akzeptiert nur verifizierten Zertifikatssubjekt-Header, kurze UUID-Requests, Replay-Schutz und lokale Scopes; ohne vollständige mTLS-Dateien fällt der Broker geschlossen aus | echte CA/Client-/Server-Zertifikate installieren und Transporttest fahren |
| Dateien, Docker, Netzwerk und Admin sicher kapseln | lokal bewiesen | Datei-Löschen ist ein wiederherstellbarer Trash-Move; Docker nur für erlaubte Container; Netzwerk/Admin wählen ausschließlich operator-definierte argv-Profile; kein Request kann Shelltext oder Zusatzargumente einschleusen; Host-Agent verlangt Freigabe erneut | plattformspezifische Netzwerk-/Admin-Profile auf dem Zielhost durch Administrator festlegen |
| Not-Aus bis Host-Agent | lokal bewiesen | API/Broker widerrufen Freigaben und Warteschlangen; Host-Agent beendet verfolgte Prozesse, persistiert den Stop über Neustarts und fällt bei beschädigtem Marker geschlossen aus | unter echter mTLS-Kette einen laufenden Zielprozess abbrechen |
| Append-only Hash-Audit und gegenseitige Visualisierung | lokal bewiesen | Audit-Verifikation, Brain-Referenzen, eindeutige Graphkanten und Browserprüfung Markdown -> Audit -> Markdown; Desktop- und Mobilviewport geprüft | Darstellung mit produktiver Datenmenge beobachten |
| Telegram, WhatsApp, Push und SIP/VoIP opt-in | implementiert, Provider-E2E offen | Registry standardmäßig aus; Telegram Secret/Chat-Allowlist/Dedupe; WhatsApp Challenge/HMAC/Parsing; Push und Asterisk-ARI/SIP erlauben nur konfigurierte Ziele; Inbound-Ereignisse erzeugen nur Dry Runs | Sandbox-/Live-Webhooks, Push-Ziel und Asterisk-Audiopfad mit echten Zugangsdaten testen |
| Zeitpläne und Reminder | lokal bewiesen | persistente einmalige und endliche Wiederholungen; fällige externe Nachrichten warten auf frische Freigabe; `reminder.dispatch` nutzt denselben Brokerpfad | eine reale freigegebene Provider-Nachricht ausliefern |
| Selbstverbesserung mit Git, Shadow, Promotion und Rollback | lokal bewiesen | Cross-Process-Lock/SQLite-Transaktion; Git-Branch/Worktree; SHA-verifiziertes Runtime-Manifest; Prompts/Config/Skills wirken live; Code läuft nur im netzlosen Read-only-Wegwerfcontainer; Parallel-/Quarantäne-/Health-Rollbacktests und echter isolierter Code-Probelauf bestanden | Shadow-Build und Rollback noch einmal auf dem Ziel-Dockerhost ausführen |
| Bildgetreues PyQt-HUD | lokal bewiesen | Referenzvergleich 1600 x 990, Minimalgröße 960 x 680, physischer Mikrofonbeweis, 14 Tests; Navigation, Kontext, Zustände, reduzierte Bewegung, Drag-and-drop, Esc/F4 und fehlender Benutzeravatar geprüft | keine lokale Implementierungslücke; optional mit höherem Sprachpegel dokumentieren |
| Bestehender Mark-Pfad bleibt erhalten | erfüllt | der neue Backenddienst ist additiv unter `backend`; bestehende Desktopdateien und uncommittete Änderungen wurden erweitert statt zurückgesetzt | Gemini erst nach erfolgreicher Offline-Zielabnahme aus dem aktiven Betrieb entfernen |

## Verbleibende externe Abnahmen

1. ZimaOS oder Proxmox-VM mit echten persistenten Pfaden, Besitzrechten,
   Netzwerk/Firewall und Backupziel bereitstellen.
2. GTX 970 durchreichen, NVIDIA Container Toolkit konfigurieren und den
   konservativen llama.cpp-Lasttest ausführen.
3. Qwen3-, Whisper- und Piper-Modelle einlegen und den deutschen Sprachdialog
   bei deaktiviertem Internet auf Desktop und Smartphone testen.
4. LAN-HTTPS sowie die produktive mTLS-Host-Agent-Kette installieren und
   Not-Aus/Restart unter laufender Arbeit prüfen.
5. Telegram-/WhatsApp-/Push-/Asterisk-Sandboxes mit echten Secrets und
   ausdrücklich freigegebenen Empfängern abnehmen.

Diese Punkte sind keine fehlenden lokalen Codepfade. Sie benötigen den
konkreten Zielhost, Hardware, Zertifikate oder externe Providerzugänge und
dürfen deshalb nicht durch simulierte Erfolgsbehauptungen ersetzt werden.
