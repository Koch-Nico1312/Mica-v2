"""
Multi-Agent Coordinator System

Coordinates between Research, Code, and Server agents with a main orchestrator.
Each agent runs as a specialized service with clear responsibilities.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional
from pathlib import Path

from llm_client import call_llm_text, get_llm_settings
from code_agent import CodeAgent, TaskTier


class AgentType(Enum):
    """Types of specialized agents."""
    RESEARCH = "research"
    CODE = "code"
    SERVER = "server"
    ORCHESTRATOR = "orchestrator"


@dataclass
class AgentTask:
    """A task to be executed by an agent."""
    task_id: str
    agent_type: AgentType
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    priority: int = 5  # 1-10, higher is more important
    dependencies: list[str] = field(default_factory=list)  # task_ids this depends on


@dataclass
class AgentResult:
    """Result from an agent execution."""
    task_id: str
    agent_type: AgentType
    success: bool
    result: Any
    error: Optional[str] = None
    execution_time: float = 0.0


class AgentCoordinator:
    """
    Main coordinator for multi-agent system.
    
    Coordinates between:
    - Research Agent: Information gathering, analysis, documentation
    - Code Agent: Code generation, modification, testing
    - Server Agent: API services, background tasks, monitoring
    - Orchestrator: High-level task planning and coordination
    """

    def __init__(
        self,
        logger: Callable[[str], None] = print,
        code_agent: Optional[CodeAgent] = None,
    ):
        self.logger = logger
        self.code_agent = code_agent
        self.task_queue: list[AgentTask] = []
        self.completed_tasks: dict[str, AgentResult] = {}
        self.running_tasks: dict[str, asyncio.Task] = {}
        self._shutdown = False

    async def submit_task(self, task: AgentTask) -> str:
        """
        Submit a task to the coordinator.
        
        Args:
            task: AgentTask to execute
            
        Returns:
            Task ID
        """
        self.logger(f"[Coordinator] Task submitted: {task.task_id} ({task.agent_type.value})")
        self.task_queue.append(task)
        return task.task_id

    async def get_result(self, task_id: str, timeout: float = 300.0) -> AgentResult:
        """
        Wait for a task result.
        
        Args:
            task_id: Task ID to wait for
            timeout: Maximum time to wait in seconds
            
        Returns:
            AgentResult with task outcome
        """
        start_time = asyncio.get_event_loop().time()
        
        while task_id not in self.completed_tasks:
            if asyncio.get_event_loop().time() - start_time > timeout:
                raise TimeoutError(f"Task {task_id} timed out after {timeout}s")
            
            if self._shutdown:
                raise RuntimeError("Coordinator is shutting down")
            
            await asyncio.sleep(0.1)
        
        return self.completed_tasks[task_id]

    async def start(self) -> None:
        """Start the coordinator and begin processing tasks."""
        self.logger("[Coordinator] Starting multi-agent coordinator")
        self._shutdown = False
        
        # Start task processor
        asyncio.create_task(self._process_tasks())

    async def stop(self) -> None:
        """Stop the coordinator gracefully."""
        self.logger("[Coordinator] Stopping coordinator")
        self._shutdown = True
        
        # Cancel running tasks
        for task_id, task in self.running_tasks.items():
            task.cancel()
            self.logger(f"[Coordinator] Cancelled task: {task_id}")
        
        # Wait for tasks to complete
        if self.running_tasks:
            await asyncio.gather(*self.running_tasks.values(), return_exceptions=True)

    async def _process_tasks(self) -> None:
        """Main task processing loop."""
        while not self._shutdown:
            if not self.task_queue:
                await asyncio.sleep(0.1)
                continue
            
            # Sort by priority (higher first)
            self.task_queue.sort(key=lambda t: t.priority, reverse=True)
            
            # Get next task with satisfied dependencies
            task = None
            for t in self.task_queue:
                if all(dep_id in self.completed_tasks for dep_id in t.dependencies):
                    task = t
                    self.task_queue.remove(t)
                    break
            
            if task is None:
                await asyncio.sleep(0.1)
                continue
            
            # Execute task
            asyncio.create_task(self._execute_task(task))

    async def _execute_task(self, task: AgentTask) -> None:
        """Execute a single task using the appropriate agent."""
        self.logger(f"[Coordinator] Executing task: {task.task_id} ({task.agent_type.value})")
        
        start_time = asyncio.get_event_loop().time()
        
        try:
            result = await self._route_to_agent(task)
            execution_time = asyncio.get_event_loop().time() - start_time
            
            agent_result = AgentResult(
                task_id=task.task_id,
                agent_type=task.agent_type,
                success=True,
                result=result,
                execution_time=execution_time,
            )
            
        except Exception as e:
            execution_time = asyncio.get_event_loop().time() - start_time
            agent_result = AgentResult(
                task_id=task.task_id,
                agent_type=task.agent_type,
                success=False,
                result=None,
                error=str(e),
                execution_time=execution_time,
            )
            self.logger(f"[Coordinator] Task failed: {task.task_id} - {e}")
        
        self.completed_tasks[task.task_id] = agent_result
        self.logger(
            f"[Coordinator] Task completed: {task.task_id} "
            f"({'✓' if agent_result.success else '✗'}) in {execution_time:.2f}s"
        )

    async def _route_to_agent(self, task: AgentTask) -> Any:
        """Route task to the appropriate specialized agent."""
        if task.agent_type == AgentType.RESEARCH:
            return await self._research_agent(task)
        elif task.agent_type == AgentType.CODE:
            return await self._code_agent(task)
        elif task.agent_type == AgentType.SERVER:
            return await self._server_agent(task)
        elif task.agent_type == AgentType.ORCHESTRATOR:
            return await self._orchestrator_agent(task)
        else:
            raise ValueError(f"Unknown agent type: {task.agent_type}")

    async def _research_agent(self, task: AgentTask) -> str:
        """
        Research Agent: Information gathering and analysis.
        
        Handles:
        - Web searches and information retrieval
        - Documentation generation
        - Data analysis and summarization
        - Report generation
        """
        self.logger(f"[ResearchAgent] Processing: {task.description[:100]}...")
        
        prompt = f"""
You are a research agent. Gather and analyze information for the following task:

Task: {task.description}
Parameters: {json.dumps(task.parameters, indent=2)}

Provide a comprehensive research report with:
1. Key findings
2. Relevant data/sources
3. Analysis and insights
4. Recommendations

Report:"""

        try:
            result = call_llm_text(prompt, timeout=120)
            return result
        except Exception as e:
            raise RuntimeError(f"Research agent failed: {e}")

    async def _code_agent(self, task: AgentTask) -> str:
        """
        Code Agent: Code generation and modification.
        
        Handles:
        - Code generation
        - File modifications
        - Testing and validation
        - Code review
        """
        self.logger(f"[CodeAgent] Processing: {task.description[:100]}...")
        
        if not self.code_agent:
            raise RuntimeError("Code agent not initialized")
        
        # Extract project path from parameters
        project_path = task.parameters.get("project_path")
        if project_path:
            self.code_agent = CodeAgent(project_path, logger=self.logger)
        
        # Analyze task
        code_task = self.code_agent.analyze_task(task.description)
        
        # Execute task
        result = self.code_agent.execute_task(code_task)
        
        if result.success:
            return f"Code task completed: {result.message}\nTest results: {result.test_results}"
        else:
            raise RuntimeError(f"Code task failed: {result.message}")

    async def _server_agent(self, task: AgentTask) -> str:
        """
        Server Agent: API services and background tasks.
        
        Handles:
        - API endpoint management
        - Background task execution
        - Service monitoring
        - Server configuration
        """
        self.logger(f"[ServerAgent] Processing: {task.description[:100]}...")
        
        prompt = f"""
You are a server agent. Handle the following server-related task:

Task: {task.description}
Parameters: {json.dumps(task.parameters, indent=2)}

Provide:
1. Action taken or configuration applied
2. Service status
3. Any relevant logs or output

Response:"""

        try:
            result = call_llm_text(prompt, timeout=60)
            return result
        except Exception as e:
            raise RuntimeError(f"Server agent failed: {e}")

    async def _orchestrator_agent(self, task: AgentTask) -> str:
        """
        Orchestrator Agent: High-level planning and coordination.
        
        Handles:
        - Task decomposition
        - Agent selection
        - Workflow planning
        - Result synthesis
        """
        self.logger(f"[Orchestrator] Processing: {task.description[:100]}...")
        
        prompt = f"""
You are an orchestrator agent. Plan and coordinate the following task:

Task: {task.description}
Parameters: {json.dumps(task.parameters, indent=2)}

Decompose this task into subtasks for specialized agents:
- research: Information gathering
- code: Code generation/modification
- server: Server/API tasks

Return a JSON plan with:
{{
  "subtasks": [
    {{"agent_type": "research", "description": "...", "priority": 7}},
    {{"agent_type": "code", "description": "...", "priority": 8}}
  ],
  "workflow": "sequential|parallel",
  "final_output": "..."
}}

Plan:"""

        try:
            plan_str = call_llm_text(prompt, timeout=90)
            
            # Parse the plan (basic parsing, in production use proper JSON parsing)
            try:
                plan = json.loads(plan_str)
                
                # Create and submit subtasks
                subtask_ids = []
                for i, subtask in enumerate(plan.get("subtasks", [])):
                    subtask_id = f"{task.task_id}_sub{i}"
                    subtask = AgentTask(
                        task_id=subtask_id,
                        agent_type=AgentType(subtask["agent_type"]),
                        description=subtask["description"],
                        priority=subtask.get("priority", 5),
                        dependencies=subtask_ids if plan.get("workflow") == "sequential" else [],
                    )
                    await self.submit_task(subtask)
                    subtask_ids.append(subtask_id)
                
                # Wait for all subtasks to complete
                results = []
                for subtask_id in subtask_ids:
                    result = await self.get_result(subtask_id)
                    results.append(result)
                
                # Synthesize final result
                success_count = sum(1 for r in results if r.success)
                return f"Orchestration complete: {success_count}/{len(results)} subtasks succeeded"
            
            except json.JSONDecodeError:
                # If JSON parsing fails, return the raw plan
                return f"Orchestration plan generated:\n{plan_str}"
        
        except Exception as e:
            raise RuntimeError(f"Orchestrator agent failed: {e}")

    def get_status(self) -> dict[str, Any]:
        """Get current coordinator status."""
        return {
            "queue_size": len(self.task_queue),
            "completed_count": len(self.completed_tasks),
            "running_count": len(self.running_tasks),
            "shutdown": self._shutdown,
        }