# Advanced Agent System Documentation

## Overview

The Advanced Agent System provides four major capabilities for MICA V2:

1. **Code Agent** - Local-first project management for SysCore, CyberDeck, and other developer projects
2. **Multi-Agent Coordinator** - Orchestrates Research, Code, and Server agents with a main coordinator
3. **Model Router** - Dynamic model selection based on task complexity and cost optimization
4. **Isolated Plugin Loader** - Process-isolated plugin execution with true crash isolation

## Features

### 1. Code Agent (`core/code_agent.py`)

A dedicated code agent for managing local developer projects with restricted workspace access.

**Capabilities:**
- Project inspection and metadata extraction
- Code task analysis and complexity classification
- File modifications (edits/generation)
- Automated testing and validation
- Status reporting

**Task Tiers:**
- `SIMPLE` - Single file, <100 lines, no dependencies
- `MEDIUM` - Multi-file, <500 lines, standard dependencies
- `COMPLEX` - Multi-file, >500 lines, complex dependencies
- `CRITICAL` - Production code, security-sensitive, complex logic

**Usage Example:**
```python
from core.code_agent import CodeAgent

# Initialize with project root
agent = CodeAgent(
    project_root="/path/to/project",
    allowed_roots=["/allowed/paths"],
    logger=print
)

# Inspect project
context = agent.inspect_project()
print(f"Project: {context.name}, Files: {len(context.files)}")

# Analyze task
task = agent.analyze_task("Add user authentication to the app")
print(f"Task tier: {task.tier}")

# Execute task
result = agent.execute_task(task)
print(f"Success: {result.success}")
```

### 2. Multi-Agent Coordinator (`core/agent_coordinator.py`)

Coordinates between specialized agents with a main orchestrator.

**Agent Types:**
- `RESEARCH` - Information gathering, analysis, documentation
- `CODE` - Code generation, modification, testing
- `SERVER` - API services, background tasks, monitoring
- `ORCHESTRATOR` - High-level task planning and coordination

**Usage Example:**
```python
import asyncio
from core.agent_coordinator import AgentCoordinator, AgentType, AgentTask

async def main():
    coordinator = AgentCoordinator(logger=print)
    await coordinator.start()
    
    try:
        # Submit research task
        task = AgentTask(
            task_id="research_1",
            agent_type=AgentType.RESEARCH,
            description="Research best practices for API authentication",
            priority=8,
        )
        task_id = await coordinator.submit_task(task)
        
        # Get result
        result = await coordinator.get_result(task_id, timeout=120)
        print(f"Result: {result.result}")
        
    finally:
        await coordinator.stop()

asyncio.run(main())
```

### 3. Model Router (`core/model_router.py`)

Dynamic model routing based on task complexity, cost considerations, and availability.

**Model Tiers:**
- `LOCAL_FAST` - Fast local models (Ollama, small models)
- `LOCAL_BALANCED` - Balanced local models
- `CLOUD_ECONOMY` - Cost-effective cloud models
- `CLOUD_PERFORMANCE` - High-performance cloud models

**Task Complexity:**
- `TRIVIAL` - Simple queries, single-step tasks
- `SIMPLE` - Basic tasks, clear requirements
- `MODERATE` - Multi-step tasks, some complexity
- `COMPLEX` - Complex tasks, deep reasoning required
- `CRITICAL` - Mission-critical, high accuracy needed

**Usage Example:**
```python
from core.model_router import ModelRouter

router = ModelRouter(logger=print, budget_limit_hourly=1.0)

# Route request
decision = router.route_request(
    task_description="Implement secure authentication system",
    context={"file_count": 15, "dependency_count": 25}
)
print(f"Selected model: {decision.selected_config.model_name}")
print(f"Reasoning: {decision.reasoning}")

# Execute with automatic routing
result = router.execute_with_routing(
    prompt="Generate authentication code",
    task_description="Implement secure authentication",
    context={"security_sensitive": True}
)

# Check usage stats
stats = router.get_usage_stats()
print(f"Hourly cost: ${stats['current_hourly_cost']:.4f}")
```

### 4. Isolated Plugin Loader (`core/isolated_plugin_loader.py`)

Process-isolated plugin system with true crash isolation and security.

**Features:**
- Each plugin runs in its own subprocess
- Crash isolation - plugin crashes don't affect main process
- Resource limits (CPU, memory, timeout)
- Automatic restart on failure
- Health monitoring via heartbeats
- IPC-based communication

**Usage Example:**
```python
from core.isolated_plugin_loader import IsolatedPluginLoader

loader = IsolatedPluginLoader(
    plugins_dir="/path/to/plugins",
    core_tool_names={"core_tool_names"},
    logger=print,
    max_plugin_memory_mb=512,
    plugin_timeout_seconds=30,
)

# Start plugin
loader.start_plugin("my_plugin")

# Execute plugin
result = loader.execute_plugin(
    plugin_name="my_plugin",
    parameters={"action": "do_something"},
    player=ui,
    session_memory=None
)

# Health check
health = loader.health_check()
print(f"Plugin health: {health}")

# Stop plugin
loader.stop_plugin("my_plugin")
```

## Integration via `advanced_agent` Action

The `actions/advanced_agent.py` provides a unified interface to access all advanced agent capabilities through the existing tool system.

**Available Actions:**

### `inspect_project`
Inspect a project and return metadata.
```json
{
  "action": "inspect_project",
  "project_path": "/path/to/project"
}
```

### `analyze_task`
Analyze a code task complexity.
```json
{
  "action": "analyze_task",
  "task_description": "Add user authentication",
  "project_path": "/path/to/project"
}
```

### `execute_task`
Execute a code task on a project.
```json
{
  "action": "execute_task",
  "task_description": "Add user authentication",
  "project_path": "/path/to/project"
}
```

### `project_status`
Generate project status report.
```json
{
  "action": "project_status",
  "project_path": "/path/to/project"
}
```

### `submit_task`
Submit task to multi-agent coordinator.
```json
{
  "action": "submit_task",
  "agent_type": "research",
  "task_description": "Research API authentication best practices",
  "priority": 8
}
```

### `route_llm`
Route LLM request with intelligent model selection.
```json
{
  "action": "route_llm",
  "task_description": "Implement secure authentication",
  "task_context": {"security_sensitive": true},
  "force_model_tier": "cloud_performance"
}
```

### `plugin_health`
Check plugin health status.
```json
{
  "action": "plugin_health"
}
```

### `model_usage`
Get model usage statistics.
```json
{
  "action": "model_usage"
}
```

## Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    Advanced Agent System                    │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │  Code Agent  │  │ Coordinator  │  │ Model Router │    │
│  │              │  │              │  │              │    │
│  │ - Inspection │  │ - Research   │  │ - Routing    │    │
│  │ - Analysis   │  │ - Code       │  │ - Cost Opt   │    │
│  │ - Execution  │  │ - Server     │  │ - Fallback   │    │
│  │ - Testing    │  │ - Orchest.   │  │ - Stats      │    │
│  └──────────────┘  └──────────────┘  └──────────────┘    │
│         │                 │                 │              │
│         └─────────────────┴─────────────────┘              │
│                           │                                 │
│                   ┌───────▼───────┐                         │
│                   │   Integration │                         │
│                   │    Module     │                         │
│                   └───────┬───────┘                         │
│                           │                                 │
│                   ┌───────▼───────┐                         │
│                   │advanced_agent │                         │
│                   │    Action     │                         │
│                   └───────┬───────┘                         │
│                           │                                 │
│  ┌────────────────────────┼──────────────────────────┐    │
│  │                        │                          │    │
│  ▼                        ▼                          ▼    │
│ ┌────────┐           ┌─────────┐              ┌──────────┐ │
│ │ Plugins│           │ Projects│              │   LLM    │ │
│ │(Isolated)           │ (Local) │              │ Providers│ │
│ └────────┘           └─────────┘              └──────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### Security Considerations

1. **Code Agent Security:**
   - Restricted to allowed project roots
   - Path validation before file operations
   - Automatic backup before modifications
   - No execution outside project directory

2. **Plugin Isolation:**
   - Each plugin in separate subprocess
   - Memory limits (configurable)
   - Timeout protection
   - IPC communication only
   - No shared memory access

3. **Model Router Security:**
   - No API keys in logs
   - Cost budget limits
   - Credential validation
   - Local-first by default

## Configuration

### Code Agent Configuration

```python
agent = CodeAgent(
    project_root="/path/to/project",
    allowed_roots=[
        Path.home() / "Desktop" / "JarvisProjects",
        Path.home() / "Projects",
        # Add your custom paths
    ],
    logger=print
)
```

### Model Router Configuration

```python
router = ModelRouter(
    logger=print,
    custom_models={
        ModelTier.LOCAL_FAST: ModelConfig(
            tier=ModelTier.LOCAL_FAST,
            provider="ollama",
            model_name="your-custom-model",
            cost_per_1k_tokens=0.0,
            max_tokens=2000,
            timeout=30,
        ),
    },
    budget_limit_hourly=2.0,  # USD per hour
)
```

### Plugin Loader Configuration

```python
loader = IsolatedPluginLoader(
    plugins_dir="/path/to/plugins",
    core_tool_names={"existing_tool_names"},
    logger=print,
    max_plugin_memory_mb=1024,  # Memory limit per plugin
    plugin_timeout_seconds=60,   # Execution timeout
)
```

## Migration from Legacy Systems

### From `actions/dev_agent.py`

The legacy `dev_agent.py` used an embedded API key and was desktop-centric. The new Code Agent:

- **Local-first design** - No embedded API keys
- **Restricted workspace** - Security-focused path validation
- **Task tier analysis** - Intelligent complexity detection
- **Testing integration** - Automated test execution
- **Status reporting** - Comprehensive project insights

To migrate:
1. Replace `dev_agent` calls with `advanced_agent` action
2. Use `execute_task` action for code modifications
3. Use `inspect_project` for project analysis
4. Configure allowed project roots for security

### From `core/plugin_loader.py`

The legacy plugin loader ran plugins in-process with try/except. The new Isolated Plugin Loader:

- **True process isolation** - Each plugin in separate subprocess
- **Crash protection** - Plugin crashes don't affect main process
- **Resource limits** - Memory and timeout controls
- **Health monitoring** - Automatic restart on failure
- **IPC communication** - Secure message passing

To migrate:
1. Replace `discover_plugins` with `IsolatedPluginLoader`
2. Use `execute_plugin` instead of direct function calls
3. Configure memory and timeout limits
4. Monitor plugin health with `health_check()`

## Performance Considerations

### Code Agent Performance
- File inspection is O(n) where n = number of files
- LLM calls for task analysis and code generation
- Test execution can be time-consuming (configurable timeout)

### Model Router Performance
- Task classification is O(1) (heuristic-based)
- LLM routing adds minimal overhead
- Cost tracking in-memory (no database)

### Plugin Loader Performance
- Process creation overhead (~50-100ms per plugin)
- IPC communication overhead (~1-5ms per message)
- Memory overhead per plugin (~10-50MB base + plugin memory)

## Troubleshooting

### Code Agent Issues

**Problem:** "Project root not in allowed directories"
**Solution:** Add the project path to `allowed_roots` during initialization

**Problem:** "LLM description failed"
**Solution:** Check LLM provider configuration and connectivity

### Coordinator Issues

**Problem:** "Task timed out"
**Solution:** Increase timeout in `get_result()` call or check agent performance

**Problem:** "All model routing attempts failed"
**Solution:** Verify LLM provider configuration and fallback model availability

### Plugin Loader Issues

**Problem:** "Plugin failed to start"
**Solution:** Check plugin file syntax and dependencies

**Problem:** "Plugin execution timed out"
**Solution:** Increase `plugin_timeout_seconds` or optimize plugin code

**Problem:** "Unhealthy plugin detected"
**Solution:** Check plugin logs, increase memory limit, or fix plugin code

## Future Enhancements

Planned improvements for the Advanced Agent System:

1. **Distributed Agent Coordination** - Support for agents across multiple machines
2. **Advanced Caching** - LLM response caching for repeated tasks
3. **Plugin Marketplace** - Centralized plugin discovery and distribution
4. **Model Fine-tuning** - Support for custom fine-tuned models
5. **Real-time Collaboration** - Multi-user agent coordination
6. **Advanced Analytics** - Detailed usage analytics and optimization

## Contributing

When contributing to the Advanced Agent System:

1. Follow existing code patterns and architecture
2. Add comprehensive tests for new features
3. Update documentation for API changes
4. Consider security implications of all changes
5. Test with various LLM providers and models

## License

This component is part of MICA V2 and follows the project's license terms.