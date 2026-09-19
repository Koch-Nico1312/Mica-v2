"""
Advanced Agent Action

Demonstrates usage of the new agent capabilities:
- Code Agent for local project management
- Multi-Agent Coordinator for task orchestration
- Model Router for intelligent model selection
- Isolated Plugin Loader for safe plugin execution
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from core.agent_integration import AgentIntegration


def advanced_agent(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None,
) -> str:
    """
    Advanced agent action with multi-agent coordination.
    
    Parameters:
        action: The action to perform
        - inspect_project: Inspect a project and return metadata
        - analyze_task: Analyze a code task complexity
        - execute_task: Execute a code task on a project
        - project_status: Generate project status report
        - submit_task: Submit task to multi-agent coordinator
        - route_llm: Route LLM request with intelligent model selection
        - plugin_health: Check plugin health status
        
        project_path: Path to project (for code agent actions)
        task_description: Description of the task (for code/agent tasks)
        agent_type: Type of agent (research, code, server, orchestrator)
        task_context: Additional context for routing/analysis
        force_model_tier: Force specific model tier (local_fast, local_balanced, cloud_economy, cloud_performance)
    """
    p = parameters or {}
    action = p.get("action", "").strip().lower()
    
    # Initialize agent integration
    integration = AgentIntegration(
        logger=lambda msg: (print(f"[AdvancedAgent] {msg}"), player.write_log(msg) if player else None),
        project_root=p.get("project_path"),
        plugins_dir=Path(__file__).parent.parent / "plugins",
        core_tool_names={"advanced_agent"},  # This action's name
    )
    
    try:
        if action == "inspect_project":
            project_path = p.get("project_path")
            if not project_path:
                return "Please provide project_path parameter."
            
            result = integration.inspect_project(project_path)
            output = f"""
Project Inspection Results:
- Name: {result['name']}
- Language: {result['language']}
- Files: {result['file_count']}
- Dependencies: {len(result['dependencies'])}
- Entry Points: {', '.join(result['entry_points']) or 'None'}
- Description: {result['description']}
"""
            if speak:
                speak(f"Project {result['name']} inspected. {result['file_count']} files in {result['language']}.")
            return output.strip()
        
        elif action == "analyze_task":
            task_description = p.get("task_description")
            project_path = p.get("project_path")
            
            if not task_description or not project_path:
                return "Please provide task_description and project_path parameters."
            
            result = integration.analyze_code_task(task_description, project_path)
            output = f"""
Task Analysis:
- Description: {result['description']}
- Tier: {result['tier']}
- Target Files: {', '.join(result['target_files']) or 'None'}
- Test Required: {result['test_required']}
"""
            if speak:
                speak(f"Task analyzed as {result['tier']} complexity.")
            return output.strip()
        
        elif action == "execute_task":
            task_description = p.get("task_description")
            project_path = p.get("project_path")
            
            if not task_description or not project_path:
                return "Please provide task_description and project_path parameters."
            
            result = integration.execute_code_task(task_description, project_path)
            
            if result['success']:
                output = f"""
Task Executed Successfully:
- Message: {result['message']}
- Modified Files: {', '.join(result['modified_files']) or 'None'}
- Test Results: {result['test_results']}
"""
                if speak:
                    speak(f"Task completed successfully. {len(result['modified_files'])} files modified.")
            else:
                output = f"""
Task Execution Failed:
- Message: {result['message']}
- Errors: {', '.join(result['errors'])}
"""
                if speak:
                    speak(f"Task execution failed: {result['message']}")
            
            return output.strip()
        
        elif action == "project_status":
            project_path = p.get("project_path")
            if not project_path:
                return "Please provide project_path parameter."
            
            report = integration.get_project_status(project_path)
            
            if speak:
                speak("Project status report generated.")
            
            return report
        
        elif action == "submit_task":
            agent_type = p.get("agent_type", "research")
            task_description = p.get("task_description")
            task_params = p.get("task_params", {})
            priority = p.get("priority", 5)
            
            if not task_description:
                return "Please provide task_description parameter."
            
            # Run async coordinator operations
            async def submit_and_get():
                await integration.start_coordinator()
                try:
                    task_id = await integration.submit_agent_task(
                        agent_type=agent_type,
                        description=task_description,
                        parameters=task_params,
                        priority=priority,
                    )
                    
                    result = await integration.get_agent_result(task_id, timeout=120)
                    return result
                finally:
                    await integration.stop_coordinator()
            
            result = asyncio.run(submit_and_get())
            
            output = f"""
Agent Task Result:
- Task ID: {result['task_id']}
- Agent Type: {result['agent_type']}
- Success: {result['success']}
- Execution Time: {result['execution_time']:.2f}s
"""
            if result['success']:
                output += f"- Result: {result['result']}\n"
            else:
                output += f"- Error: {result['error']}\n"
            
            if speak:
                if result['success']:
                    speak(f"Agent task completed successfully by {result['agent_type']} agent.")
                else:
                    speak(f"Agent task failed: {result['error']}")
            
            return output.strip()
        
        elif action == "route_llm":
            task_description = p.get("task_description")
            context = p.get("task_context", {})
            force_tier = p.get("force_model_tier")
            
            if not task_description:
                return "Please provide task_description parameter."
            
            decision = integration.route_llm_request(task_description, context, force_tier)
            
            output = f"""
Model Routing Decision:
- Selected Model: {decision['selected_model']}
- Provider: {decision['provider']}
- Tier: {decision['tier']}
- Reasoning: {decision['reasoning']}
- Estimated Cost: ${decision['estimated_cost']:.4f}
- Fallback Models: {', '.join(decision['fallback_models']) or 'None'}
"""
            if speak:
                speak(f"Routed to {decision['selected_model']} ({decision['tier']} tier).")
            
            return output.strip()
        
        elif action == "plugin_health":
            health = integration.check_plugin_health()
            
            output = "Plugin Health Status:\n"
            for plugin_name, status in health.items():
                status_icon = "✓" if status['healthy'] else "✗"
                output += f"- {status_icon} {plugin_name}: "
                output += f"Alive={status['alive']}, "
                output += f"Healthy={status['healthy']}, "
                output += f"PID={status['pid']}, "
                output += f"Restarts={status['restart_count']}\n"
            
            if speak:
                healthy_count = sum(1 for s in health.values() if s['healthy'])
                speak(f"Plugin health check: {healthy_count}/{len(health)} plugins healthy.")
            
            return output.strip()
        
        elif action == "model_usage":
            stats = integration.get_model_usage_stats()
            
            output = f"""
Model Usage Statistics:
- Current Hourly Cost: ${stats['current_hourly_cost']:.4f}
- Budget Limit: ${stats['budget_limit']:.2f}
- Budget Remaining: ${stats['budget_remaining']:.2f}

Model Breakdown:
"""
            for model_key, model_stats in stats['models'].items():
                output += f"- {model_key}:\n"
                output += f"  Calls: {model_stats['call_count']}\n"
                output += f"  Tokens: {model_stats['total_tokens']:.0f}\n"
                output += f"  Cost: ${model_stats['total_cost']:.4f}\n"
            
            if speak:
                speak(f"Current hourly cost: ${stats['current_hourly_cost']:.4f}")
            
            return output.strip()
        
        else:
            return f"""
Unknown action: {action}

Available actions:
- inspect_project: Inspect a project and return metadata
- analyze_task: Analyze a code task complexity
- execute_task: Execute a code task on a project
- project_status: Generate project status report
- submit_task: Submit task to multi-agent coordinator
- route_llm: Route LLM request with intelligent model selection
- plugin_health: Check plugin health status
- model_usage: Get model usage statistics
"""
    
    except Exception as e:
        error_msg = f"Advanced agent action failed: {e}"
        print(f"[AdvancedAgent] Error: {e}")
        if speak:
            speak(f"Advanced agent encountered an error: {str(e)[:100]}")
        return error_msg