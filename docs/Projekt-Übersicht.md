# MICA V2 - Projekt-Übersicht

## Projektname
MICA V2 (Multi-Agent Intelligent Control Assistant)

## Beschreibung
MICA V2 ist ein fortschrittlicher KI-Assistent mit Multi-Agent-Fähigkeiten, lokaler Projektverwaltung, intelligentem Model-Routing und Prozess-isolierten Plugins. Das System ist local-first konzipiert mit Cloud Opt-in für erweiterte Fähigkeiten.

## Technologie-Stack

### Kern-Technologien
- **Sprache:** Python 3.x
- **LLM-Integration:** Google Gemini API, OpenAI API, Ollama (Local)
- **Audio:** Sounddevice, NumPy
- **UI:** Qt-basiert (windsurf/ui)
- **Async:** Asyncio für Multi-Agent-Koordination
- **Prozess-Isolation:** Multiprocessing für Plugins

### Haupt-Dependencies
- `google-genai` - Gemini API Client
- `requests` - HTTP Client
- `sounddevice` - Audio I/O
- `numpy` - Audio Processing
- `httpx` - HTTP Client (für Cloud LLM)

## Projektstruktur

```
Mica V2/
├── desktop/                   # Windows-Oberfläche, Aktionen, Kernmodule und Ressourcen
│   ├── actions/                # Desktop-Aktionen
│   ├── core/                   # Desktop-Core (Audio, LLM, Sicherheit)
│   ├── dashboard/              # Desktop-Dashboard
│   ├── memory/                 # Desktop-Gedächtnis
│   ├── plugins/                # Desktop-Plugins
│   ├── config/                 # Desktop-Konfiguration
│   ├── assets/                 # UI- und Audio-Ressourcen
│   ├── models/                 # Lokale Modelle
│   ├── main.py                 # Gemini-Live-Einstiegspunkt
│   ├── local_main.py           # Lokaler Einstiegspunkt
│   └── ui.py                   # PyQt-Oberfläche
├── backend/                    # Separater API-/Docker-Backenddienst
│   ├── services/               # API und Hintergrunddienste
│   ├── windows_host_agent/     # Sicherer Windows-Aktionsdienst
│   └── docker-compose.yml
├── .mica-data/                  # Versteckte lokale Daten und Laufzeit-Ausgaben
├── docs/                      # Dokumentation
├── tests/                     # Projektprüfungen
├── docker/                    # Test-Sandbox
└── install_and_start.ps1      # Aktualisieren und Desktop-App starten
```

## Haupt-Features

### 1. Advanced Agent System
- **Code Agent:** Lokale Projektverwaltung für SysCore, CyberDeck
- **Multi-Agent Coordinator:** Koordination von Research, Code, Server Agents
- **Model Router:** Intelligente Model-Selektion nach Kosten/Komplexität
- **Isolated Plugin Loader:** Prozess-isolierte Plugins mit Crash-Schutz

### 2. Voice-Interaktion
- Echtzeit-Spracherkennung
- Text-to-Speech mit verschiedenen Stimmen
- Affective Dialog (Emotionserkennung)
- Proaktive Audio-Verarbeitung

### 3. Computer-Steuerung
- Browser-Automatisierung (Chrome, Edge, Firefox, etc.)
- Direkte Computer-Steuerung (Tastatur, Maus, Hotkeys)
- Datei-Management und -Verarbeitung
- Desktop-Organisation und Wallpaper-Management

### 4. Vision-Fähigkeiten
- Screen-Capture und Analyse
- Webcam-Integration
- OCR und Bildverarbeitung
- Live Camera Stream

### 5. Web-Integration
- Web-Suche mit verschiedenen Modi (search, news, research, price, compare)
- YouTube-Steuerung
- Flight-Finder
- Game-Updater (Steam, Epic Games)

### 6. Memory-System
- Langzeit-Memory für persönliche Fakten
- Session-Memory für Gesprächskontext
- Markdown Brain für Wissensmanagement
- Such- und Retrieval-Funktionen

### 7. Background-Monitoring
- Themen-Monitoring mit täglichen Checks
- Proaktive Benachrichtigungen
- System-Monitoring (CPU, RAM, GPU, Temperatur)

## Konfiguration

### API-Keys
Konfiguriert in `desktop/config/api_keys.json`:
- `gemini_api_key` - Google Gemini API Key
- `assistant_name` - Name des Assistenten
- `user_name` - Name des Benutzers

### LLM-Provider
Umgebungsvariablen oder Konfiguration:
- `MICA_LLM_PROVIDER` - ollama, openai, openai_api, gemini
- `MICA_LLM_URL` - URL für Local LLM Server
- `MICA_LLM_MODEL` - Model-Name
- `OPENAI_API_KEY` - OpenAI API Key (für openai_api)
- `GEMINI_API_KEY` - Gemini API Key (für gemini)

### Audio-Konfiguration
- Mikrofon- und Lautsprecher-Auswahl
- Stimmen-Auswahl (verschiedene Gemini Voices)
- Audio-Device-Konfiguration

## Nutzung

### Starten des Systems
```bash
# Local Start
python desktop/local_main.py

# Oder mit PowerShell Script
.\install_and_start.ps1
```

### Voice-Interaktion
- Sprechen Sie mit dem Assistenten nach dem Start
- Verwenden Sie natürliche Sprache für Kommandos
- Der Assistent erkennt Absicht und führt entsprechende Actions aus

### Text-Interaktion
- Nutzen Sie das UI für Text-Eingabe
- Geben Sie Kommandos direkt ein
- Sehen Sie live Ergebnisse und Logs

### Advanced Agent Nutzung
Verwenden Sie die `advanced_agent` Action für erweiterte Funktionen:
- Projekt-Inspektion
- Code-Task-Analyse und -Execution
- Multi-Agent-Koordination
- Intelligentes Model-Routing
- Plugin-Management

## Sicherheit

### Local-First Design
- Standardmäßig lokale LLMs (Ollama)
- Keine Daten an Cloud ohne explizite Konfiguration
- API-Keys nur bei Bedarf

### Prozess-Isolation
- Plugins laufen in isolierten Subprozessen
- Resource-Limits verhalten DoS-Angriffe
- Crash-Isolation schützt Main-Prozess

### Path-Validation
- Code Agent beschränkt auf erlaubte Verzeichnisse
- Keine Datei-Operationen außerhalb Workspace
- Automatische Backups vor Modifikationen

### Memory-Schutz
- Persönliche Daten lokal gespeichert
- Cloud-Opt-in für private Context-Daten
- Audit-Logging für alle Actions

## Performance

### Optimierungen
- KV-Cache Priming für Ollama
- Sliding-Window Compression für Sessions
- Async-Task-Verarbeitung
- Intelligente Model-Selektion

### Resource-Usage
- Memory: ~200-500MB Base + LLM Model Size
- CPU: Minimal bei Idle, hoch bei LLM-Inference
- GPU: Optional für LLM-Beschleunigung
- Network: Nur bei Cloud LLM oder Web-Actions

## Troubleshooting

### Häufige Probleme

**Ollama nicht gefunden:**
- Installieren Sie Ollama von https://ollama.com
- Starten Sie mit `ollama serve`
- Prüfen Sie Port 11434

**API-Key Fehler:**
- Prüfen Sie `desktop/config/api_keys.json`
- Setzen Sie Umgebungsvariablen für Cloud-Provider
- Verifizieren Sie Key-Format und Berechtigungen

**Audio-Probleme:**
- Prüfen Sie Audio-Device-Konfiguration
- Stellen Sie sicher, dass Mikrofon verfügbar ist
- Testen Sie mit system audio tools

**Plugin-Probleme:**
- Prüfen Sie Plugin-Syntax und Dependencies
- Erhöhen Sie Memory-Limits bei Bedarf
- Überprüfen Sie Health-Status mit `plugin_health`

## Development

### Hinzufügen neuer Actions
1. Erstellen Sie Datei in `desktop/actions/`
2. Implementieren Sie Action-Funktion mit Standard-Signatur
3. Fügen Sie Tool-Deklaration in `main.py` hinzu
4. Fügen Sie Execution-Logic in `_execute_tool` hinzu
5. Testen Sie mit Voice/Text-Kommandos

### Hinzufügen neuer Plugins
1. Erstellen Sie Datei in `desktop/plugins/`
2. Implementieren Sie `PLUGIN` dict und `run()` Funktion
3. Validieren Sie mit Plugin-Loader
4. Testen Sie mit Isolated Plugin Loader

### Erweitern des Agent Systems
1. Nutzen Sie `AgentIntegration` Klasse
2. Fügen Sie neue Agent-Typen in Coordinator hinzu
3. Implementieren Sie Routing-Logik in Model Router
4. Dokumentieren Sie neue Features

## License
Das Projekt folgt den in der LICENSE-Datei definierten Lizenzbedingungen.

## Support
Für Support und Fragen:
- Prüfen Sie die Dokumentation im `docs/` Ordner
- Sehen Sie Troubleshooting-Sektion
- Konsultieren Sie API-Dokumentation
