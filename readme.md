# MICA V2 - Multi-Agent Intelligent Control Assistant

<div align="center">

**Advanced AI Assistant with Multi-Agent Coordination, Local Project Management, and Process-Isolated Plugins**

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()

</div>

## 🌟 Overview

MICA V2 is a sophisticated AI assistant that combines advanced multi-agent coordination with local-first architecture. It features intelligent project management, dynamic model routing, and process-isolated plugins for enhanced security and reliability.

### Key Features

- **🤖 Advanced Agent System**
  - Code Agent for local project management (SysCore, CyberDeck)
  - Multi-Agent Coordinator for Research, Code, and Server tasks
  - Model Router for intelligent LLM selection by cost/complexity
  - Isolated Plugin Loader with true process isolation

- **🎙️ Voice Interaction**
  - Real-time speech recognition with Gemini Native Audio
  - Text-to-speech with multiple voice options
  - Affective dialog (emotion recognition)
  - Proactive audio processing

- **💻 Computer Control**
  - Browser automation (Chrome, Edge, Firefox, Opera, Brave, Vivaldi)
  - Direct computer control (keyboard, mouse, hotkeys)
  - File management and processing
  - Desktop organization and wallpaper management

- **👁️ Vision Capabilities**
  - Screen capture and analysis
  - Webcam integration with live streaming
  - OCR and image processing
  - Scene understanding

- **🧠 Memory System**
  - Long-term memory for personal facts
  - Session memory for conversation context
  - Markdown brain for knowledge management
  - Search and retrieval functions

- **🌐 Web Integration**
  - Multi-mode web search (search, news, research, price, compare)
  - YouTube control
  - Flight finder
  - Game updater (Steam, Epic Games)

## 🚀 Quick Start

### Prerequisites

- Python 3.8 or higher
- 4GB RAM (8GB recommended)
- 2GB free disk space
- Microphone and speakers (for voice interaction)

### Installation

**Windows (Recommended - Automated):**

```powershell
# Clone the repository
git clone https://github.com/Koch-Nico1312/Mica-v2.git
cd Mica-v2

# Run the automated installer and launcher
.\install_and_start.ps1
```

The script will:
- ⚠️ Show a warning on first run (dependencies installation takes time)
- 📥 Automatically install `uv` package manager if needed
- 🐍 Create local Python environment
- 📦 Install all dependencies with progress bars
- 🚀 Start MICA Core after installation

**Manual Installation:**
```bash
# Clone the repository
git clone https://github.com/Koch-Nico1312/Mica-v2.git
cd Mica-v2

# Install dependencies
pip install -r requirements.txt

# Configure API keys (see Configuration section)
cp .env.example .env
# Edit .env with your API keys

# Start the application
python local_main.py
```

### Quick Start with Ollama (Local LLM)

```bash
# Install Ollama from https://ollama.com
# Start Ollama
ollama serve

# Pull a model
ollama pull llama3.2

# Start MICA V2
python local_main.py
```

## ⚙️ Configuration

### Environment Variables

Create a `.env` file in the project root:

```bash
# LLM Provider Configuration
MICA_LLM_PROVIDER=ollama  # Options: ollama, openai, openai_api, gemini
MICA_LLM_URL=http://localhost:11434
MICA_LLM_MODEL=llama3.2

# Gemini API (Cloud)
GEMINI_API_KEY=your-gemini-api-key
MICA_GEMINI_MODEL=gemini-2.5-flash

# OpenAI API (Cloud)
OPENAI_API_KEY=your-openai-api-key
MICA_OPENAI_MODEL=gpt-4.1-mini

# Assistant Configuration
ASSISTANT_NAME=JARVIS
USER_NAME=Your Name
```

### API Keys Configuration

Alternatively, configure API keys in `config/api_keys.json`:

```json
{
  "gemini_api_key": "your-gemini-api-key",
  "openai_api_key": "your-openai-api-key",
  "assistant_name": "JARVIS",
  "user_name": "Your Name"
}
```

### Audio Configuration

Audio devices can be configured through the UI:
- Microphone selection
- Speaker selection
- Voice selection (various Gemini voices)

## 📖 Usage

### Voice Interaction

1. Start the application with `python local_main.py`
2. Speak naturally to the assistant
3. The assistant recognizes intent and executes appropriate actions

### Text Interaction

1. Use the UI for text input
2. Enter commands directly
3. See live results and logs

### Advanced Agent Usage

Use the `advanced_agent` action for advanced features:

```
# Inspect a project
Use advanced_agent with action "inspect_project" and project_path "/path/to/project"

# Analyze a code task
Use advanced_agent with action "analyze_task", task_description "Add authentication", and project_path "/path/to/project"

# Execute multi-agent workflow
Use advanced_agent with action "submit_task", agent_type "research", and task_description "Research API security"

# Route LLM request intelligently
Use advanced_agent with action "route_llm" and task_description "Implement secure authentication"
```

## 🏗️ Architecture

MICA V2 consists of multiple layers:

1. **User Interface Layer:** Voice, Text, Remote Control
2. **Main Orchestration Layer:** JarvisLive Controller, Tool Router, Session Management
3. **Advanced Agent System:** Code Agent, Coordinator, Model Router, Plugin Loader
4. **Action Layer:** Browser Control, Computer Control, File Manager, etc.
5. **Core Services Layer:** LLM Client, Memory Management, Plugin Discovery
6. **External Services Layer:** Ollama, Gemini, OpenAI, Browser Drivers

For detailed architecture documentation, see [docs/Architektur.md](docs/Architektur.md).

## 🔒 Security

### Local-First Design
- Default local LLMs (Ollama)
- No data sent to cloud without explicit configuration
- API keys only when needed

### Process Isolation
- Plugins run in isolated subprocesses
- Resource limits prevent DoS attacks
- Crash isolation protects main process

### Path Validation
- Code agent restricted to allowed directories
- No file operations outside workspace
- Automatic backups before modifications

## 📊 Performance

### Optimizations
- KV-cache priming for Ollama
- Sliding-window compression for sessions
- Async task processing
- Intelligent model selection

### Resource Usage
- Memory: ~200-500MB base + LLM model size
- CPU: Minimal at idle, high during LLM inference
- GPU: Optional for LLM acceleration
- Network: Only for cloud LLM or web actions

## 🧩 Development

### Adding New Actions

1. Create a new file in `actions/`
2. Implement the action function with standard signature
3. Add tool declaration in `main.py`
4. Add execution logic in `_execute_tool`
5. Test with voice/text commands

### Adding New Plugins

1. Create a new file in `plugins/`
2. Implement plugin structure with `PLUGIN` dict and `run()` function
3. Plugin is automatically discovered and loaded

### Project Structure

```
Mica V2/
├── actions/              # Action modules
├── core/                 # Core components
│   ├── code_agent.py    # Dedicated Code Agent
│   ├── agent_coordinator.py  # Multi-Agent Coordinator
│   ├── model_router.py   # Dynamic Model Router
│   └── isolated_plugin_loader.py  # Process-Isolated Plugins
├── mica_core/           # MICA Core Services
├── memory/              # Memory management
├── plugins/             # Plugin directory
├── config/              # Configuration files
├── docs/                # Documentation
├── main.py              # Main entry point
└── local_main.py        # Local entry point
```

## 📚 Documentation

- [German Documentation](docs/Projekt-Übersicht.md) - Complete German documentation
- [English Documentation](docs/ADVANCED_AGENTS.md) - Advanced Agent System documentation
- [Architecture](docs/Architektur.md) - Detailed system architecture
- [Git Preparation](docs/Git-Vorbereitung.md) - Git repository setup guide

## 🐛 Troubleshooting

### Common Issues

**Ollama not found:**
- Install Ollama from https://ollama.com
- Start with `ollama serve`
- Check port 11434

**API key errors:**
- Check `config/api_keys.json`
- Set environment variables for cloud providers
- Verify key format and permissions

**Audio problems:**
- Check audio device configuration in UI
- Ensure microphone is available
- Test with system audio tools

**Plugin problems:**
- Check plugin syntax and dependencies
- Increase memory limits if needed
- Check health status with `plugin_health`

## 🔄 Migration from Legacy Systems

### From dev_agent to Advanced Agent
Replace `dev_agent` calls with `advanced_agent` action:
- Use `execute_task` for code modifications
- Use `inspect_project` for project analysis
- Configure allowed project roots for security

### From legacy plugin loader to isolated loader
Replace `discover_plugins` with `IsolatedPluginLoader`:
- Use `execute_plugin` instead of direct function calls
- Configure memory and timeout limits
- Monitor plugin health with `health_check()`

## 🤝 Contributing

Contributions are welcome! Please:

1. Follow the existing code style (PEP 8)
2. Add tests for new features
3. Update documentation
4. Ensure security best practices

## 📄 License

This project is licensed under the terms specified in the [LICENSE](LICENSE) file.

## 🙏 Acknowledgments

- Uses Google Gemini API for advanced AI capabilities
- Integrates Ollama for local LLM inference
- Powered by Python and the open-source community

## 📞 Support

For support and questions:
- Check the documentation in the `docs/` folder
- Review the troubleshooting section
- Open an issue on GitHub
- Contact the development team

---

**Version:** 2.0  
**Last Updated:** 2026-09-19  
**Status:** Production Ready with Advanced Agent System