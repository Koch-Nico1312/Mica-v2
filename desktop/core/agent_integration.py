"""
Integration module for advanced agent features.

This module provides a unified interface for:
- Code Agent (local project management)
- Multi-Agent Coordinator (research, code, server agents)
- Model Router (dynamic model selection)
- Isolated Plugin Loader (process-isolated plugins)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from core.code_agent import CodeAgent, TaskTier
from core.agent_coordinator import AgentCoordinator, AgentType, AgentTask
from core.model_router import ModelRouter, ModelTier, TaskComplexity
from core.isolated_plugin_loader import IsolatedPluginLoader


class AgentIntegration:
    """
    Unified interface for advanced agent features.
    
    This class provides a simple API to access all the new agent capabilities
    while maintaining backward compatibility with the existing system.
    """

    def __init__(
        self,
        logger: Callable[[str], None] = print,
        project_root: Optional[Path | str] = None,
        plugins_dir: Optional[Path | str] = None,
        core_tool_names: Optional[set[str]] = None,
        allowed_roots: Optional[list[Path | str]] = None,
    ):
        self.logger = logger
        # Sandbox for the code agent; None keeps CodeAgent's own defaults.
        self.allowed_roots = allowed_roots
        
        # Initialize components
        self.code_agent: Optional[CodeAgent] = None
        self.coordinator: Optional[AgentCoordinator] = None
        self.model_router: Optional[ModelRouter] = None
        self.plugin_loader: Optional[IsolatedPluginLoader] = None
        
        # Initialize code agent if project root provided
        if project_root:
            self.code_agent = CodeAgent(
                project_root=project_root,
                allowed_roots=allowed_roots,
                logger=logger,
            )
        
        # Initialize coordinator
        self.coordinator = AgentCoordinator(logger=logger, code_agent=self.code_agent)
        
        # Initialize model router
        self.model_router = ModelRouter(logger=logger)
        
        # Initialize isolated plugin loader if plugins dir provided
        if plugins_dir and core_tool_names:
            self.plugin_loader = IsolatedPluginLoader(
                plugins_dir=plugins_dir,
                core_tool_names=core_tool_names,
                logger=logger,
            )

    # Code Agent Methods
    def inspect_project(self, project_root: Path | str) -> dict[str, Any]:
        """
        Inspect a project and return metadata.
        
        Args:
            project_root: Path to project root
            
        Returns:
            Project metadata dictionary
        """
        if not self.code_agent:
            self.code_agent = CodeAgent(
                project_root,
                allowed_roots=self.allowed_roots,
                logger=self.logger,
            )
        
        context = self.code_agent.inspect_project()
        return {
            "name": context.name,
            "root_path": str(context.root_path),
            "language": context.language,
            "file_count": len(context.files),
            "dependencies": context.dependencies,
            "entry_points": context.entry_points,
            "description": context.description,
        }

    def analyze_code_task(self, task_description: str, project_root: Path | str) -> dict[str, Any]:
        """
        Analyze a code task and determine complexity.
        
        Args:
            task_description: Description of the task
            project_root: Path to project root
            
        Returns:
            Task analysis dictionary
        """
        if not self.code_agent:
            self.code_agent = CodeAgent(
                project_root,
                allowed_roots=self.allowed_roots,
                logger=self.logger,
            )
        
        task = self.code_agent.analyze_task(task_description)
        return {
            "description": task.description,
            "tier": task.tier.value,
            "target_files": [str(f) for f in task.target_files],
            "test_required": task.test_required,
        }

    def execute_code_task(
        self,
        task_description: str,
        project_root: Path | str,
    ) -> dict[str, Any]:
        """
        Execute a code task on a project.
        
        Args:
            task_description: Description of the task
            project_root: Path to project root
            
        Returns:
            Execution result dictionary
        """
        if not self.code_agent:
            self.code_agent = CodeAgent(
                project_root,
                allowed_roots=self.allowed_roots,
                logger=self.logger,
            )
        
        task = self.code_agent.analyze_task(task_description)
        result = self.code_agent.execute_task(task)
        
        return {
            "success": result.success,
            "message": result.message,
            "modified_files": [str(f) for f in result.modified_files],
            "test_results": result.test_results,
            "errors": result.errors,
        }

    def get_project_status(self, project_root: Path | str) -> str:
        """
        Generate a status report for a project.
        
        Args:
            project_root: Path to project root
            
        Returns:
            Status report string
        """
        if not self.code_agent:
            self.code_agent = CodeAgent(
                project_root,
                allowed_roots=self.allowed_roots,
                logger=self.logger,
            )
        
        return self.code_agent.generate_status_report()

    # Multi-Agent Coordinator Methods
    async def submit_agent_task(
        self,
        agent_type: str,
        description: str,
        parameters: dict[str, Any] | None = None,
        priority: int = 5,
    ) -> str:
        """
        Submit a task to the multi-agent coordinator.
        
        Args:
            agent_type: Type of agent (research, code, server, orchestrator)
            description: Task description
            parameters: Task parameters
            priority: Task priority (1-10)
            
        Returns:
            Task ID
        """
        if not self.coordinator:
            raise RuntimeError("Coordinator not initialized")
        
        task = AgentTask(
            task_id=f"task_{id(description)}",
            agent_type=AgentType(agent_type),
            description=description,
            parameters=parameters or {},
            priority=priority,
        )
        
        return await self.coordinator.submit_task(task)

    async def get_agent_result(self, task_id: str, timeout: float = 300.0) -> dict[str, Any]:
        """
        Get result from an agent task.
        
        Args:
            task_id: Task ID to wait for
            timeout: Maximum wait time in seconds
            
        Returns:
            Task result dictionary
        """
        if not self.coordinator:
            raise RuntimeError("Coordinator not initialized")
        
        result = await self.coordinator.get_result(task_id, timeout)
        
        return {
            "task_id": result.task_id,
            "agent_type": result.agent_type.value,
            "success": result.success,
            "result": result.result,
            "error": result.error,
            "execution_time": result.execution_time,
        }

    async def start_coordinator(self) -> None:
        """Start the multi-agent coordinator."""
        if not self.coordinator:
            raise RuntimeError("Coordinator not initialized")
        
        await self.coordinator.start()

    async def stop_coordinator(self) -> None:
        """Stop the multi-agent coordinator."""
        if not self.coordinator:
            raise RuntimeError("Coordinator not initialized")
        
        await self.coordinator.stop()

    def get_coordinator_status(self) -> dict[str, Any]:
        """Get coordinator status."""
        if not self.coordinator:
            raise RuntimeError("Coordinator not initialized")
        
        return self.coordinator.get_status()

    # Model Router Methods
    def route_llm_request(
        self,
        task_description: str,
        context: dict[str, Any] | None = None,
        force_tier: str | None = None,
    ) -> dict[str, Any]:
        """
        Route an LLM request to the appropriate model.
        
        Args:
            task_description: Description of the task
            context: Additional context for routing
            force_tier: Optional forced model tier
            
        Returns:
            Routing decision dictionary
        """
        if not self.model_router:
            raise RuntimeError("Model router not initialized")
        
        tier = ModelTier(force_tier) if force_tier else None
        decision = self.model_router.route_request(task_description, context, tier)
        
        return {
            "selected_model": decision.selected_config.model_name,
            "provider": decision.selected_config.provider,
            "tier": decision.selected_config.tier.value,
            "reasoning": decision.reasoning,
            "estimated_cost": decision.estimated_cost,
            "fallback_models": [c.model_name for c in decision.fallback_configs],
        }

    def execute_with_routing(
        self,
        prompt: str,
        system_prompt: str | None = None,
        task_description: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        """
        Execute an LLM call with automatic routing.
        
        Args:
            prompt: The prompt to send
            system_prompt: Optional system prompt
            task_description: Description for routing
            context: Additional context for routing
            
        Returns:
            LLM response text
        """
        if not self.model_router:
            raise RuntimeError("Model router not initialized")
        
        return self.model_router.execute_with_routing(
            prompt, system_prompt, task_description, context
        )

    def get_model_usage_stats(self) -> dict[str, Any]:
        """Get model usage statistics."""
        if not self.model_router:
            raise RuntimeError("Model router not initialized")
        
        return self.model_router.get_usage_stats()

    def reset_model_usage_stats(self) -> None:
        """Reset model usage statistics."""
        if not self.model_router:
            raise RuntimeError("Model router not initialized")
        
        self.model_router.reset_usage_stats()

    # Isolated Plugin Loader Methods
    def start_plugin(self, plugin_name: str) -> bool:
        """Start a plugin in an isolated process."""
        if not self.plugin_loader:
            raise RuntimeError("Plugin loader not initialized")
        
        return self.plugin_loader.start_plugin(plugin_name)

    def stop_plugin(self, plugin_name: str) -> bool:
        """Stop a running plugin."""
        if not self.plugin_loader:
            raise RuntimeError("Plugin loader not initialized")
        
        return self.plugin_loader.stop_plugin(plugin_name)

    def execute_plugin(
        self,
        plugin_name: str,
        parameters: dict[str, Any],
        player=None,
        session_memory=None,
    ) -> str:
        """Execute a plugin in its isolated process."""
        if not self.plugin_loader:
            raise RuntimeError("Plugin loader not initialized")
        
        return self.plugin_loader.execute_plugin(
            plugin_name, parameters, player, session_memory
        )

    def check_plugin_health(self) -> dict[str, Any]:
        """Perform health check on all running plugins."""
        if not self.plugin_loader:
            raise RuntimeError("Plugin loader not initialized")
        
        return self.plugin_loader.health_check()

    def get_plugin_declarations(self) -> list[dict]:
        """Get tool declarations for enabled plugins."""
        if not self.plugin_loader:
            raise RuntimeError("Plugin loader not initialized")
        
        return self.plugin_loader.get_tool_declarations()

    def list_plugins(self) -> list[dict]:
        """List all plugins for UI display."""
        if not self.plugin_loader:
            raise RuntimeError("Plugin loader not initialized")
        
        return self.plugin_loader.list_for_ui()

    def shutdown_all_plugins(self) -> None:
        """Stop all running plugins."""
        if not self.plugin_loader:
            raise RuntimeError("Plugin loader not initialized")
        
        self.plugin_loader.shutdown_all()


def id(s: str) -> str:
    """Generate a simple ID from a string."""
    import hashlib
    return hashlib.md5(s.encode()).hexdigest()[:8]