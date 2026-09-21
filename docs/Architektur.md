# MICA V2 - Architektur-Dokumentation

## System-Architektur

### High-Level Überblick

```
┌─────────────────────────────────────────────────────────────────┐
│                         MICA V2 System                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    User Interface Layer                  │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │  │
│  │  │ Voice Input  │  │  Text Input  │  │   Remote     │  │  │
│  │  │ (Audio)      │  │  (UI)        │  │  Control     │  │  │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                  Main Orchestration Layer                 │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │  │
│  │  │ JarvisLive   │  │  Tool Router │  │ Session Mgmt │  │  │
│  │  │ Controller   │  │              │  │              │  │  │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    Advanced Agent System                 │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │  │
│  │  │  Code Agent  │  │ Coordinator  │  │ Model Router │  │  │
│  │  │              │  │              │  │              │  │  │
│  │  │ - Inspection │  │ - Research   │  │ - Routing    │  │  │
│  │  │ - Analysis   │  │ - Code       │  │ - Cost Opt   │  │  │
│  │  │ - Execution  │  │ - Server     │  │ - Fallback   │  │  │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  │  │
│  │                                                             │  │
│  │  ┌──────────────┐                                        │  │
│  │  │ Isolated     │                                        │  │
│  │  │ Plugin       │                                        │  │
│  │  │ Loader       │                                        │  │
│  │  └──────────────┘                                        │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                      Action Layer                         │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │  │
│  │  │ Browser  │ │ Computer│ │  File    │ │  Web     │   │  │
│  │  │ Control  │ │ Control │ │ Manager  │ │ Search   │   │  │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘   │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │  │
│  │  │  Vision  │ │  Code    │ │ System   │ │  Media   │   │  │
│  │  │          │ │ Helper   │ │ Monitor  │ │ Player   │   │  │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘   │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    Core Services Layer                    │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │  │
│  │  │  LLM Client  │  │ Memory Mgmt  │  │  Plugin     │  │  │
│  │  │  (Multi-     │  │              │  │  Discovery  │  │  │
│  │  │   Provider)  │  │              │  │              │  │  │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                   External Services                       │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐│  │
│  │  │ Ollama   │  │ Gemini   │  │ OpenAI   │  │ Browser  ││  │
│  │  │ (Local)  │  │ (Cloud)  │  │ (Cloud)  │  │ Drivers  ││  │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘│  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Komponenten-Architektur

### 1. User Interface Layer

#### Voice Input
- **Verantwortlich:** Audio-Erfassung und Speech-to-Text
- **Technologien:** Sounddevice, Google Gemini STT
- **Features:**
  - Echtzeit-Audio-Streaming
  - Noise-Cancellation
  - Multi-Sprache-Support
  - Affective Dialog (Emotionserkennung)

#### Text Input
- **Verantwortlich:** Text-basierte Interaktion
- **Technologien:** Qt UI, Text-Eingabe-Felder
- **Features:**
  - Live Chat-Interface
  - Command History
  - File Upload Support
  - Content Panel für Ergebnisse

#### Remote Control
- **Verantwortlich:** Fernsteuerung via Web/Dashboard
- **Technologien:** FastAPI, WebSockets
- **Features:**
  - Remote Key Authentication
  - Auto-Login
  - Status-Monitoring
  - Command Execution

### 2. Main Orchestration Layer

#### JarvisLive Controller
- **Verantwortlich:** Haupt-Koordinator und Session-Management
- **Key Features:**
  - Gemini Live API Integration
  - Tool-Execution und Result-Handling
  - Session Resumption
  - Context Window Compression
  - Vision Integration
  - Audio Management

#### Tool Router
- **Verantwortlich:** Routing von Kommandos zu passenden Actions
- **Mechanismus:**
  - Function Calling via Gemini
  - Tool-Deklaration Matching
  - Parameter-Validierung
  - Error-Handling und Retry

#### Session Management
- **Verantwortlich:** Session-State und Memory
- **Features:**
  - Session Resumption Handles
  - Memory Integration
  - Context Management
  - Summary Generation

### 3. Advanced Agent System

#### Code Agent
- **Verantwortlich:** Lokale Projektverwaltung
- **Architektur:**
  ```
  CodeAgent
  ├── ProjectContext (Metadaten)
  ├── CodeTask (Task-Analyse)
  ├── TaskResult (Execution Results)
  └── Security Layer (Path Validation)
  ```
- **Workflow:**
  1. Projekt-Inspektion
  2. Task-Analyse (Tier-Klassifizierung)
  3. Code-Generierung/Modifikation
  4. Testing und Validierung
  5. Status-Reporting

#### Multi-Agent Coordinator
- **Verantwortlich:** Koordination spezialisierter Agenten
- **Architektur:**
  ```
  AgentCoordinator
  ├── Task Queue (Priority-based)
  ├── Agent Pool (Research, Code, Server, Orchestrator)
  ├── Result Registry
  └── Health Monitor
  ```
- **Workflow:**
  1. Task-Submission
  2. Agent-Selection
  3. Parallel/Sequential Execution
  4. Result-Aggregation
  5. Error-Handling und Retry

#### Model Router
- **Verantwortlich:** Intelligente Model-Selektion
- **Architektur:**
  ```
  ModelRouter
  ├── Model Configs (Tier-based)
  ├── Task Classifier (Complexity)
  ├── Cost Tracker (Budget Management)
  └── Fallback Manager (Reliability)
  ```
- **Routing-Logik:**
  1. Task-Komplexitäts-Analyse
  2. Cost/Benefit Evaluation
  3. Budget-Check
  4. Model-Selektion
  5. Fallback bei Ausfall

#### Isolated Plugin Loader
- **Verantwortlich:** Prozess-isolierte Plugin-Execution
- **Architektur:**
  ```
  IsolatedPluginLoader
  ├── Plugin Registry
  ├── Process Pool (One per Plugin)
  ├── IPC Manager (Pipe Communication)
  └── Health Monitor (Heartbeat-based)
  ```
- **Isolation-Mechanismen:**
  - Separate Subprocess per Plugin
  - Memory Limits (RLIMIT_AS)
  - Timeout Protection
  - IPC-only Communication
  - Automatic Restart

### 4. Action Layer

#### Browser Control
- **Verantwortlich:** Web-Browser Automatisierung
- **Support:** Chrome, Edge, Firefox, Opera, Brave, Vivaldi
- **Actions:** Navigation, Search, Click, Type, Fill Forms, Screenshots

#### Computer Control
- **Verantwortlich:** Direkte Hardware-Steuerung
- **Actions:** Typing, Clicking, Hotkeys, Mouse Movement, Screenshots

#### File Manager
- **Verantwortlich:** Datei-System Operationen
- **Actions:** List, Create, Delete, Move, Copy, Rename, Read, Write, Search

#### Web Search
- **Verantwortlich:** Web-Information Retrieval
- **Modes:** Search, News, Research, Price, Compare
- **Engines:** Google, Bing, DuckDuckGo, Yandex

#### Vision
- **Verantwortlich:** Bild- und Screen-Analyse
- **Sources:** Screen Capture, Webcam
- **Capabilities:** OCR, Object Detection, Scene Understanding

#### Code Helper
- **Verantwortlich:** Code-Generation und -Assistenz
- **Actions:** Write, Edit, Explain, Run, Build

#### System Monitor
- **Verantwortlich:** System-Metriken
- **Metrics:** CPU, RAM, GPU, Temperature, Uptime, Process Count

### 5. Core Services Layer

#### LLM Client
- **Verantwortlich:** Multi-Provider LLM Integration
- **Provider:**
  - Ollama (Local)
  - OpenAI-Compatible (LM Studio, LocalAI, Jan)
  - OpenAI API (Cloud)
  - Gemini API (Cloud)
- **Features:**
  - Streaming und Non-Streaming
  - Tool Calling Support
  - Auto-Retry und Fallback
  - Cost Tracking

#### Memory Management
- **Verantwortlich:** Persistent Memory und Session-Kontext
- **Komponenten:**
  - Memory Manager (Langzeit-Memory)
  - Config Manager (Konfiguration)
  - Session Memory (Kurzzeit-Kontext)
- **Storage:** SQLite für structured Daten, JSON für Konfiguration

#### Plugin Discovery
- **Verantwortlich:** Plugin-Loading und Validation
- **Features:**
  - Plugin Registry
  - Collision Detection
  - Enable/Disable Management
  - UI Integration

### 6. External Services Layer

#### Ollama (Local)
- **Zweck:** Local LLM Inference
- **Models:** Llama 3.2, Qwen, Mistral, etc.
- **Advantage:** Privacy, Cost, Latency

#### Gemini (Cloud)
- **Zweck:** Cloud LLM mit Advanced Features
- **Features:** Vision, Audio, Multimodal
- **Advantage:** Quality, Capabilities

#### OpenAI (Cloud)
- **Zweck:** Alternative Cloud LLM
- **Models:** GPT-4.1, GPT-3.5
- **Advantage:** Ecosystem, Tools

#### Browser Drivers
- **Zweck:** Browser Automatisierung
- **Drivers:** Selenium, Playwright (via browser_control)
- **Support:** Multi-Browser, Multi-Platform

## Datenfluss

### Typical Voice Command Flow

```
1. User Speech
   ↓
2. Audio Capture (sounddevice)
   ↓
3. STT (Gemini Native Audio)
   ↓
4. Transcript Cleaning
   ↓
5. Tool Selection (Gemini Function Calling)
   ↓
6. Parameter Extraction
   ↓
7. Action Execution
   ↓
8. Result Processing
   ↓
9. Response Generation (Gemini)
   ↓
10. TTS (Gemini Native Audio)
    ↓
11. Audio Output (sounddevice)
```

### Advanced Agent Flow

```
1. User Request (advanced_agent action)
   ↓
2. Action Router (main.py)
   ↓
3. Agent Integration (agent_integration.py)
   ↓
4. Component Selection:
   - Code Agent → Project Management
   - Coordinator → Multi-Agent Workflow
   - Model Router → Intelligent LLM Selection
   - Plugin Loader → Isolated Execution
   ↓
5. Execution
   ↓
6. Result Processing
   ↓
7. Response Generation
   ↓
8. User Feedback
```

## Security-Architektur

### Defense in Depth

1. **Application Layer:**
   - Input Validation
   - Path Traversal Protection
   - Command Injection Prevention

2. **Process Layer:**
   - Plugin Isolation (Subprocesses)
   - Resource Limits (Memory, CPU)
   - Timeout Protection

3. **Network Layer:**
   - API Key Management
   - TLS Encryption
   - Request Validation

4. **Data Layer:**
   - Local-First Storage
   - Encryption at Rest (optional)
   - Audit Logging

### Threat Mitigation

| Threat | Mitigation |
|--------|------------|
| Code Injection | Input Validation, Parameter Sanitization |
| Path Traversal | Path Validation, Restricted Workspace |
| DoS Attacks | Resource Limits, Rate Limiting |
| Data Exfiltration | Local-First, Cloud Opt-in |
| Plugin Compromise | Process Isolation, Resource Limits |
| API Key Theft | Environment Variables, No Logging |

## Performance-Architektur

### Optimierungs-Strategien

1. **LLM Optimization:**
   - KV-Cache Priming
   - Context Window Compression
   - Model Routing (Cost/Performance)
   - Response Caching (geplant)

2. **I/O Optimization:**
   - Async Operations
   - Connection Pooling
   - Batch Processing
   - Lazy Loading

3. **Memory Optimization:**
   - Streaming für große Responses
   - Memory Limits für Plugins
   - Efficient Data Structures
   - Garbage Collection Tuning

### Scalability

**Current:** Single-User, Single-Machine
**Planned:**
- Multi-User Support
- Distributed Agent Coordination
- Horizontal Scaling
- Load Balancing

## Deployment-Architektur

### Local Deployment
```
User Machine
├── MICA V2 Application
├── Ollama (Optional)
├── Browser Drivers
└── Local Files
```

### Cloud-Enhanced Deployment
```
User Machine
├── MICA V2 Application
├── Ollama (Optional)
└── Browser Drivers
     ↕ (API Calls)
Cloud Services
├── Gemini API
├── OpenAI API
└── Web Services
```

### Distributed Deployment (Geplant)
```
User Machines
├── MICA V2 Clients
     ↕ (WebSocket)
Coordination Server
├── Agent Coordinator
├── Model Router
└── Plugin Registry
     ↕ (IPC)
Agent Workers
├── Research Agents
├── Code Agents
└── Server Agents
```

## Monitoring und Observability

### Logging
- Application Logs (stdout/stderr)
- UI Logs (Log Panel)
- Audit Logs (backend/services/common/audit.py)
- Plugin Logs (Isolated Process)

### Metrics
- System Metrics (CPU, RAM, GPU)
- LLM Usage (Tokens, Cost, Latency)
- Agent Performance (Task Time, Success Rate)
- Plugin Health (Uptime, Restart Count)

### Health Checks
- LLM Provider Connectivity
- Plugin Process Health
- System Resource Availability
- Network Connectivity

## Backup und Recovery

### Data Backup
- Memory Database (SQLite)
- Configuration Files (JSON)
- Plugin Files (Python)
- Brain/Knowledge Base (Markdown)

### Recovery Procedures
1. Configuration Restore aus Backup
2. Memory Database Import
3. Plugin Re-Installation
4. Brain Re-Indexing

## Future Architecture Enhancements

### Phase 1: Enhanced Caching
- LLM Response Cache
- File Operation Cache
- Web Request Cache
- Plugin Result Cache

### Phase 2: Distributed Agents
- Agent Communication Protocol
- Distributed Task Queue
- Result Aggregation Service
- Failover Mechanisms

### Phase 3: Advanced Security
- Plugin Sandboxing (Containers)
- Network Isolation
- Advanced Authentication
- Audit Trail Enhancement

### Phase 4: Performance
- GPU Acceleration für LLMs
- Distributed Inference
- Model Quantization
- Edge Deployment
