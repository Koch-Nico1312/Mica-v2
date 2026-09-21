# MICA V2 - Vollständige Projektdokumentation

## Inhaltsverzeichnis
1. [Projekt-Übersicht](#projekt-übersicht)
2. [Schnellstart](#schnellstart)
3. [Installation](#installation)
4. [Konfiguration](#konfiguration)
5. [Architektur](#architektur)
6. [Features](#features)
7. [Advanced Agent System](#advanced-agent-system)
8. [Entwicklung](#entwicklung)
9. [Troubleshooting](#troubleshooting)
10. [Migration Guide](#migration-guide)

## Projekt-Übersicht

MICA V2 (Multi-Agent Intelligent Control Assistant) ist ein fortschrittlicher KI-Assistent mit:

- **Multi-Agent-Fähigkeiten:** Koordinierte Ausführung von Research, Code und Server-Tasks
- **Lokale Projektverwaltung:** Dedicated Code Agent für SysCore, CyberDeck und andere Projekte
- **Intelligentes Model-Routing:** Dynamische LLM-Selektion nach Kosten und Task-Komplexität
- **Prozess-isolierte Plugins:** Echte Crash-Isolation für sichere Plugin-Execution
- **Voice-Interaktion:** Echtzeit-Spracherkennung und Text-to-Speech
- **Computer-Steuerung:** Browser-Automatisierung, Datei-Management, System-Kontrolle
- **Vision-Fähigkeiten:** Screen-Capture, Webcam-Integration, OCR
- **Memory-System:** Langzeit-Memory und Session-Kontext

### Technologie-Stack
- **Sprache:** Python 3.x
- **LLM-Integration:** Google Gemini, OpenAI, Ollama (Local)
- **Audio:** Sounddevice, NumPy
- **UI:** Qt-basiert
- **Async:** Asyncio für Multi-Agent-Koordination
- **Prozess-Isolation:** Multiprocessing

## Schnellstart

### Minimum Requirements
- Python 3.8 oder höher
- 4GB RAM (8GB empfohlen)
- 2GB freier Festplattenplatz
- Mikrofon und Lautsprecher (für Voice-Interaktion)

### Quick Start (Windows)
```powershell
# 1. Repository klonen
git clone <repository-url>
cd Mica V2

# 2. Dependencies installieren
pip install -r requirements.txt

# 3. Konfiguration einrichten
# Erstellen Sie desktop/config/api_keys.json (siehe Abschnitt Konfiguration) und
# fügen Sie Ihren Gemini-API-Key hinzu - eine .example-Datei existiert nicht im Repo

# 4. Starten
python desktop/local_main.py
# Oder nutzen Sie das PowerShell Script:
.\install_and_start.ps1
```

### Quick Start (Linux/Mac)
```bash
# 1. Repository klonen
git clone <repository-url>
cd "Mica V2"

# 2. Dependencies installieren
pip install -r requirements.txt

# 3. Konfiguration einrichten
# Erstellen Sie desktop/config/api_keys.json (siehe Abschnitt Konfiguration) und
# fügen Sie Ihren Gemini-API-Key hinzu - eine .example-Datei existiert nicht im Repo

# 4. Starten
python desktop/local_main.py
```

## Installation

### System-Requirements

#### Windows
- Windows 10 oder höher
- Python 3.8+ (von python.org oder Microsoft Store)
- Visual C++ Redistributable (für einige Python-Packages)

#### Linux
- Ubuntu 20.04+ oder äquivalent
- Python 3.8+ (system python oder pyenv)
- Build-essentials für einige Python-Packages

#### macOS
- macOS 10.15+ (Catalina oder höher)
- Python 3.8+ (von python.org oder Homebrew)
- Xcode Command Line Tools

### Python Dependencies

#### Core Dependencies
```bash
pip install google-genai requests sounddevice numpy
```

#### Optional Dependencies
```bash
# Für Browser-Automatisierung
pip install selenium playwright

# Für Vision-Funktionen
pip install opencv-python pillow pytesseract

# Für Advanced Features
pip install httpx chonkie
```

#### LLM-Provider

**Ollama (Local - Empfohlen für Privacy):**
```bash
# Download von https://ollama.com
# Installieren und starten:
ollama serve
# Model herunterladen:
ollama pull llama3.2
```

**Gemini API (Cloud - Für Advanced Features):**
- API Key von https://ai.google.dev
- Konfiguration in `desktop/config/api_keys.json`

**OpenAI API (Cloud - Alternative):**
- API Key von https://platform.openai.com
- Konfiguration in `desktop/config/api_keys.json`

### Browser-Drivers

Für Browser-Automatisierung werden folgende Drivers benötigt:

**Chrome/Edge:**
- Automatisch über WebDriver Manager

**Firefox:**
- Geckodriver von https://github.com/mozilla/geckodriver

**Andere Browser:**
- Siehe Browser-spezifische Dokumentation

## Konfiguration

### API-Konfiguration

Erstellen Sie `desktop/config/api_keys.json`:
```json
{
  "gemini_api_key": "your-gemini-api-key",
  "openai_api_key": "your-openai-api-key",
  "assistant_name": "JARVIS",
  "user_name": "Your Name"
}
```

### LLM-Provider-Konfiguration

**Umgebungsvariablen:**
```bash
# Local Ollama (Default)
export MICA_LLM_PROVIDER=ollama
export MICA_LLM_URL=http://localhost:11434
export MICA_LLM_MODEL=llama3.2

# OpenAI-Compatible (LM Studio, LocalAI)
export MICA_LLM_PROVIDER=openai
export MICA_LLM_URL=http://localhost:1234
export MICA_LLM_MODEL=qwen2.5

# Gemini Cloud
export MICA_LLM_PROVIDER=gemini
export MICA_GEMINI_MODEL=gemini-2.5-flash

# OpenAI Cloud
export MICA_LLM_PROVIDER=openai_api
export MICA_OPENAI_MODEL=gpt-4.1-mini
```

### Audio-Konfiguration

Audio-Devices können über das UI konfiguriert werden:
- Mikrofon-Auswahl
- Lautsprecher-Auswahl
- Stimmen-Auswahl (verschiedene Gemini Voices)

### Advanced Agent Konfiguration

**Code Agent:**
```python
from core.code_agent import CodeAgent

agent = CodeAgent(
    project_root="/path/to/project",
    allowed_roots=[
        Path.home() / "Desktop" / "JarvisProjects",
        Path.home() / "Projects",
    ],
    logger=print
)
```

**Model Router:**
```python
from core.model_router import ModelRouter

router = ModelRouter(
    logger=print,
    budget_limit_hourly=1.0,  # USD per hour
)
```

**Plugin Loader:**
```python
from core.isolated_plugin_loader import IsolatedPluginLoader

loader = IsolatedPluginLoader(
    plugins_dir="/path/to/plugins",
    core_tool_names={"existing_tool_names"},
    logger=print,
    max_plugin_memory_mb=512,
    plugin_timeout_seconds=30,
)
```

## Architektur

### High-Level-Architektur

Das System besteht aus mehreren Schichten:

1. **User Interface Layer:** Voice, Text, Remote Control
2. **Main Orchestration Layer:** JarvisLive Controller, Tool Router, Session Management
3. **Advanced Agent System:** Code Agent, Coordinator, Model Router, Plugin Loader
4. **Action Layer:** Browser Control, Computer Control, File Manager, etc.
5. **Core Services Layer:** LLM Client, Memory Management, Plugin Discovery
6. **External Services Layer:** Ollama, Gemini, OpenAI, Browser Drivers

Detaillierte Architektur-Informationen finden Sie in [Architektur.md](Architektur.md).

### Komponenten-Beziehungen

```
User Input → JarvisLive → Tool Router → Actions → Core Services → External Services
                ↓
          Advanced Agent System (Code Agent, Coordinator, Model Router, Plugin Loader)
```

## Features

### Voice-Interaktion
- Echtzeit-Spracherkennung mit Gemini Native Audio
- Text-to-Speech mit verschiedenen Stimmen
- Affective Dialog (Emotionserkennung)
- Proaktive Audio-Verarbeitung

### Computer-Steuerung
- **Browser Control:** Chrome, Edge, Firefox, Opera, Brave, Vivaldi
- **Computer Control:** Typing, Clicking, Hotkeys, Mouse Movement
- **File Controller:** List, Create, Delete, Move, Copy, Rename, Search
- **Desktop Control:** Wallpaper, Organization, Clean, Stats

### Vision-Fähigkeiten
- Screen Capture und Analyse
- Webcam Integration mit Live Stream
- OCR und Bildverarbeitung
- Scene Understanding

### Web-Integration
- **Web Search:** Search, News, Research, Price, Compare modes
- **YouTube Control:** Play, Summarize, Get Info, Trending
- **Flight Finder:** Google Flights Integration
- **Game Updater:** Steam und Epic Games

### Memory-System
- **Langzeit-Memory:** Persönliche Fakten, Präferenzen, Projekte
- **Session-Memory:** Gesprächskontext und history
- **Markdown Brain:** Wissensmanagement mit FTS und Vectors
- **Search und Retrieval:** Schnelle Suche nach gespeicherten Informationen

### Background-Monitoring
- Themen-Monitoring mit täglichen Checks
- Proaktive Benachrichtigungen bei neuen Entwicklungen
- System-Monitoring (CPU, RAM, GPU, Temperatur)

## Advanced Agent System

Das Advanced Agent System ist eines der mächtigsten Features von MICA V2.

### Code Agent

Der Code Agent ist ein dedicated Agent für lokale Projektverwaltung.

**Funktionen:**
- Projekt-Inspektion mit Metadaten-Extraktion
- Code-Task-Analyse mit Komplexitäts-Klassifizierung
- File-Modifikationen mit automatischen Backups
- Automatisiertes Testing und Validierung
- Umfassende Status-Reporting

**Verwendung über `advanced_agent` Action:**
```
Use advanced_agent with action "inspect_project" and project_path "/path/to/project"
Use advanced_agent with action "analyze_task", task_description "Add authentication", and project_path "/path/to/project"
Use advanced_agent with action "execute_task", task_description "Add authentication", and project_path "/path/to/project"
```

### Multi-Agent Coordinator

Koordiniert zwischen spezialisierten Agenten für komplexe Workflows.

**Agent-Typen:**
- **Research Agent:** Information Gathering, Analyse, Dokumentation
- **Code Agent:** Code-Generierung, Modifikation, Testing
- **Server Agent:** API-Services, Background-Tasks, Monitoring
- **Orchestrator:** High-Level Task-Planung und Koordination

**Verwendung:**
```
Use advanced_agent with action "submit_task", agent_type "research", and task_description "Research API security"
```

### Model Router

Intelligente Model-Selektion basierend auf Task-Komplexität und Kosten.

**Model-Tiers:**
- **LOCAL_FAST:** Schnelle lokale Modelle (Ollama, kleine Modelle)
- **LOCAL_BALANCED:** Ausgewogene lokale Modelle
- **CLOUD_ECONOMY:** Kosteneffektive Cloud-Modelle
- **CLOUD_PERFORMANCE:** Hochleistungs-Cloud-Modelle

**Verwendung:**
```
Use advanced_agent with action "route_llm" and task_description "Implement secure authentication"
```

### Isolated Plugin Loader

Prozess-isolierte Plugin-Execution mit echter Crash-Isolation.

**Features:**
- Jedes Plugin im eigenen Subprozess
- Resource-Limits (Memory, Timeout)
- Automatischer Restart bei Fehlern
- Health-Monitoring via Heartbeats

**Verwendung:**
```
Use advanced_agent with action "plugin_health"
```

Detaillierte Dokumentation finden Sie in [docs/ADVANCED_AGENTS.md](../docs/ADVANCED_AGENTS.md).

## Entwicklung

### Projektstruktur

```
Mica V2/
├── desktop/             # Desktop-App, Kernmodule und Ressourcen
├── backend/              # Separater API-/Docker-Backenddienst
├── docs/                # Dokumentation
├── tests/               # Projektprüfungen
├── docker/              # Test-Sandbox
└── install_and_start.ps1
```

### Hinzufügen neuer Actions

1. Erstellen Sie eine neue Datei in `desktop/actions/`
2. Implementieren Sie die Action-Funktion:
```python
def my_action(parameters, response=None, player=None, session_memory=None, speak=None) -> str:
    # Implementierung
    return "Result"
```

3. Fügen Sie Tool-Deklaration in `desktop/main.py` hinzu:
```python
{
    "name": "my_action",
    "description": "Description of the action",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "param1": {"type": "STRING", "description": "Parameter description"},
        },
        "required": ["param1"]
    }
}
```

4. Fügen Sie Execution-Logic in `_execute_tool` hinzu:
```python
elif name == "my_action":
    r = await loop.run_in_executor(None, lambda: my_action(parameters=args, player=self.ui, speak=self.speak))
    result = r or "Done."
```

### Hinzufügen neuer Plugins

1. Erstellen Sie eine neue Datei in `plugins/`
2. Implementieren Sie Plugin-Struktur:
```python
PLUGIN = {
    "name": "my_plugin",
    "description": "Description of the plugin",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "Action to perform"},
        },
        "required": ["action"]
    }
}

def run(parameters, player=None, session_memory=None) -> str:
    # Implementierung
    return "Result"
```

3. Plugin wird automatisch entdeckt und geladen

### Testing

**Unit Tests:**
```bash
python -m pytest tests/
```

**Integration Tests:**
```bash
python -m pytest tests/integration/
```

**Manual Testing:**
```bash
python desktop/local_main.py
```

### Code-Style

- PEP 8 konform
- Type Hints für Funktionen
- Docstrings für öffentliche Funktionen
- Maximale Zeilenlänge: 100 Zeichen

## Troubleshooting

### Häufige Probleme

**Ollama nicht gefunden:**
```bash
# Installieren Sie Ollama
# Windows: Download von https://ollama.com
# Linux/Mac: curl -fsSL https://ollama.com/install.sh | sh

# Starten Sie Ollama
ollama serve

# Laden Sie ein Model
ollama pull llama3.2
```

**API-Key Fehler:**
- Prüfen Sie `desktop/config/api_keys.json`
- Verifizieren Sie API Key Format
- Stellen Sie sicher, dass Umgebungsvariablen gesetzt sind

**Audio-Probleme:**
- Prüfen Sie Audio-Device-Konfiguration im UI
- Stellen Sie sicher, dass Mikrofon verfügbar ist
- Testen Sie mit System Audio Tools

**Plugin-Probleme:**
- Prüfen Sie Plugin-Syntax
- Erhöhen Sie Memory-Limits bei Bedarf
- Überprüfen Sie Health-Status mit `plugin_health`

**Memory-Probleme:**
- Prüfen Sie Available Memory
- Reduzieren Sie Context Window Size
- Nutzen Sie Local Models statt Cloud

### Logging

Logs werden in folgenden Orten gespeichert:
- Console Output (stdout/stderr)
- UI Log Panel
- Audit Logs (`.mica-data/audit/`)
- Plugin Logs (Isolated Process)

### Debug-Modus

Aktivieren Sie Debug-Logging:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Migration Guide

### Von Legacy dev_agent zu Advanced Agent

**Alt:**
```python
from actions.dev_agent import dev_agent
result = dev_agent(parameters={"description": "Build a web app"})
```

**Neu:**
```
Use advanced_agent with action "execute_task", task_description "Build a web app", and project_path "/path/to/project"
```

### Von Legacy Plugin Loader zu Isolated Plugin Loader

**Alt:**
```python
from core.plugin_loader import discover_plugins
registry = discover_plugins(plugins_dir, core_tool_names)
result = registry.run("plugin_name", parameters)
```

**Neu:**
```python
from core.isolated_plugin_loader import IsolatedPluginLoader
loader = IsolatedPluginLoader(plugins_dir, core_tool_names)
loader.start_plugin("plugin_name")
result = loader.execute_plugin("plugin_name", parameters)
```

## Zusätzliche Ressourcen

### Dokumentation
- [Projekt-Übersicht](Projekt-Übersicht.md) - Allgemeine Projektinformationen
- [Architektur](Architektur.md) - Detaillierte System-Architektur
- [Advanced Agents](../docs/ADVANCED_AGENTS.md) - Advanced Agent System Dokumentation
- [Devin Changes](20.09.26-DevinChanges.md) - Änderungen vom 20.09.2026

### Externe Ressourcen
- [Gemini API Documentation](https://ai.google.dev/docs)
- [Ollama Documentation](https://github.com/ollama/ollama)
- [Python Documentation](https://docs.python.org/3/)

### Community
- Issues und Feature Requests: GitHub Issues
- Diskussionen: GitHub Discussions
- Wiki: GitHub Wiki

## License

Dieses Projekt folgt den in der LICENSE-Datei definierten Lizenzbedingungen.

## Support

Für Support und Fragen:
- Prüfen Sie die Dokumentation
- Sehen Sie Troubleshooting-Sektion
- Öffnen Sie ein GitHub Issue
- Kontaktieren Sie das Development Team

---

**Version:** 2.0  
**Letzte Aktualisierung:** 19.09.2026  
**Maintainer:** Development Team
