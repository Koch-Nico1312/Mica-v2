"""
Dynamic Model Routing by Cost/Task Tier

Routes LLM requests to appropriate models based on task complexity,
cost considerations, and availability. Implements intelligent fallback
and cost optimization.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional

from llm_client import get_llm_provider, get_llm_settings, call_llm_text


class ModelTier(Enum):
    """Model tiers based on cost and capability."""
    LOCAL_FAST = "local_fast"      # Fast local models (Ollama, small models)
    LOCAL_BALANCED = "local_balanced"  # Balanced local models
    CLOUD_ECONOMY = "cloud_economy"    # Cost-effective cloud models
    CLOUD_PERFORMANCE = "cloud_performance"  # High-performance cloud models


@dataclass
class ModelConfig:
    """Configuration for a specific model."""
    tier: ModelTier
    provider: str
    model_name: str
    cost_per_1k_tokens: float
    max_tokens: int
    timeout: int
    requires_api_key: bool = False


# Default model configurations
DEFAULT_MODELS = {
    ModelTier.LOCAL_FAST: ModelConfig(
        tier=ModelTier.LOCAL_FAST,
        provider="ollama",
        model_name="llama3.2:3b",
        cost_per_1k_tokens=0.0,
        max_tokens=2000,
        timeout=30,
    ),
    ModelTier.LOCAL_BALANCED: ModelConfig(
        tier=ModelTier.LOCAL_BALANCED,
        provider="ollama",
        model_name="llama3.2",
        cost_per_1k_tokens=0.0,
        max_tokens=4000,
        timeout=60,
    ),
    ModelTier.CLOUD_ECONOMY: ModelConfig(
        tier=ModelTier.CLOUD_ECONOMY,
        provider="gemini",
        model_name="gemini-2.5-flash",
        cost_per_1k_tokens=0.0001,
        max_tokens=8000,
        timeout=90,
    ),
    ModelTier.CLOUD_PERFORMANCE: ModelConfig(
        tier=ModelTier.CLOUD_PERFORMANCE,
        provider="gemini",
        model_name="gemini-2.5-pro",
        cost_per_1k_tokens=0.002,
        max_tokens=16000,
        timeout=120,
    ),
}


class TaskComplexity(Enum):
    """Task complexity levels for routing."""
    TRIVIAL = "trivial"      # Simple queries, single-step tasks
    SIMPLE = "simple"        # Basic tasks, clear requirements
    MODERATE = "moderate"    # Multi-step tasks, some complexity
    COMPLEX = "complex"      # Complex tasks, deep reasoning required
    CRITICAL = "critical"    # Mission-critical, high accuracy needed


@dataclass
class RoutingDecision:
    """Result of model routing decision."""
    selected_config: ModelConfig
    reasoning: str
    estimated_cost: float
    fallback_configs: list[ModelConfig]


class ModelRouter:
    """
    Dynamic model router for cost-effective and performance-optimized LLM calls.
    
    Features:
    - Automatic model selection based on task complexity
    - Cost optimization with budget awareness
    - Intelligent fallback chains
    - Provider health monitoring
    - Usage statistics and cost tracking
    """

    def __init__(
        self,
        logger: Callable[[str], None] = print,
        custom_models: dict[ModelTier, ModelConfig] | None = None,
        budget_limit_hourly: float = 1.0,  # USD per hour
    ):
        self.logger = logger
        self.models = custom_models or DEFAULT_MODELS
        self.budget_limit_hourly = budget_limit_hourly
        self.usage_stats: dict[str, dict[str, Any]] = {}
        self.current_hourly_cost = 0.0
        self._last_cost_reset = 0.0

    def classify_task(self, task_description: str, context: dict[str, Any] | None = None) -> TaskComplexity:
        """
        Classify task complexity for routing decisions.
        
        Args:
            task_description: Description of the task
            context: Additional context (file count, dependencies, etc.)
            
        Returns:
            TaskComplexity level
        """
        context = context or {}
        
        # Heuristic classification
        desc_lower = task_description.lower()
        
        # Keywords indicating complexity
        complex_keywords = [
            "refactor", "architecture", "security", "performance",
            "optimize", "scalable", "distributed", "concurrent",
            "implement", "design", "system", "infrastructure"
        ]
        
        simple_keywords = [
            "fix", "simple", "basic", "small", "minor", "quick",
            "rename", "move", "delete", "add", "update"
        ]
        
        # Check for multi-file or large-scale operations
        file_count = context.get("file_count", 0)
        dependency_count = context.get("dependency_count", 0)
        
        # Classification logic
        if any(kw in desc_lower for kw in complex_keywords) or file_count > 10 or dependency_count > 20:
            return TaskComplexity.COMPLEX
        elif any(kw in desc_lower for kw in simple_keywords) and file_count <= 3:
            return TaskComplexity.SIMPLE
        elif "critical" in desc_lower or "security" in desc_lower or "production" in desc_lower:
            return TaskComplexity.CRITICAL
        elif file_count <= 1 and dependency_count <= 5:
            return TaskComplexity.TRIVIAL
        else:
            return TaskComplexity.MODERATE

    def route_request(
        self,
        task_description: str,
        context: dict[str, Any] | None = None,
        force_tier: ModelTier | None = None,
    ) -> RoutingDecision:
        """
        Route a request to the appropriate model.
        
        Args:
            task_description: Description of the task
            context: Additional context for routing
            force_tier: Optional forced model tier
            
        Returns:
            RoutingDecision with selected model and reasoning
        """
        context = context or {}
        
        # Reset hourly cost if needed
        self._check_budget_reset()
        
        # Classify task complexity
        complexity = self.classify_task(task_description, context)
        
        # Determine appropriate tier
        if force_tier:
            selected_tier = force_tier
            reasoning = f"Forced to use {force_tier.value} model"
        else:
            selected_tier = self._select_tier_by_complexity(complexity)
            reasoning = f"Selected {selected_tier.value} based on {complexity.value} task complexity"
        
        # Check budget constraints
        config = self.models[selected_tier]
        if config.cost_per_1k_tokens > 0:
            estimated_cost = self._estimate_cost(task_description, config)
            if self.current_hourly_cost + estimated_cost > self.budget_limit_hourly:
                # Downgrade to cheaper model
                fallback_tier = self._find_cheaper_available_tier(selected_tier)
                if fallback_tier:
                    selected_tier = fallback_tier
                    config = self.models[selected_tier]
                    reasoning += f" (downgraded due to budget limit)"
        
        # Build fallback chain
        fallback_configs = self._build_fallback_chain(selected_tier)
        
        return RoutingDecision(
            selected_config=config,
            reasoning=reasoning,
            estimated_cost=self._estimate_cost(task_description, config),
            fallback_configs=fallback_configs,
        )

    def _select_tier_by_complexity(self, complexity: TaskComplexity) -> ModelTier:
        """Select model tier based on task complexity."""
        tier_mapping = {
            TaskComplexity.TRIVIAL: ModelTier.LOCAL_FAST,
            TaskComplexity.SIMPLE: ModelTier.LOCAL_BALANCED,
            TaskComplexity.MODERATE: ModelTier.LOCAL_BALANCED,
            TaskComplexity.COMPLEX: ModelTier.CLOUD_ECONOMY,
            TaskComplexity.CRITICAL: ModelTier.CLOUD_PERFORMANCE,
        }
        return tier_mapping.get(complexity, ModelTier.LOCAL_BALANCED)

    def _find_cheaper_available_tier(self, current_tier: ModelTier) -> ModelTier | None:
        """Find a cheaper available model tier."""
        tier_order = [
            ModelTier.LOCAL_FAST,
            ModelTier.LOCAL_BALANCED,
            ModelTier.CLOUD_ECONOMY,
            ModelTier.CLOUD_PERFORMANCE,
        ]
        
        current_index = tier_order.index(current_tier)
        for tier in tier_order[:current_index]:
            if tier in self.models:
                return tier
        return None

    def _build_fallback_chain(self, primary_tier: ModelTier) -> list[ModelConfig]:
        """Build a fallback chain of models."""
        tier_order = [
            ModelTier.CLOUD_PERFORMANCE,
            ModelTier.CLOUD_ECONOMY,
            ModelTier.LOCAL_BALANCED,
            ModelTier.LOCAL_FAST,
        ]
        
        fallback_configs = []
        primary_index = tier_order.index(primary_tier)
        
        for tier in tier_order[primary_index + 1:]:
            if tier in self.models:
                fallback_configs.append(self.models[tier])
        
        return fallback_configs

    def _estimate_cost(self, task_description: str, config: ModelConfig) -> float:
        """Estimate cost for a request."""
        # Rough estimation: ~100 tokens per 75 words
        word_count = len(task_description.split())
        estimated_tokens = (word_count / 75) * 100
        total_tokens = estimated_tokens * 2  # Input + output
        
        cost = (total_tokens / 1000) * config.cost_per_1k_tokens
        return cost

    def _check_budget_reset(self) -> None:
        """Reset hourly cost if an hour has passed."""
        import time
        current_time = time.time()
        if current_time - self._last_cost_reset > 3600:  # 1 hour
            self.current_hourly_cost = 0.0
            self._last_cost_reset = current_time
            self.logger("[ModelRouter] Hourly budget reset")

    def execute_with_routing(
        self,
        prompt: str,
        system_prompt: str | None = None,
        task_description: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        """
        Execute an LLM call with automatic routing and fallback.
        
        Args:
            prompt: The prompt to send
            system_prompt: Optional system prompt
            task_description: Description for routing (defaults to prompt)
            context: Additional context for routing
            
        Returns:
            LLM response text
        """
        task_description = task_description or prompt
        context = context or {}
        
        # Get routing decision
        decision = self.route_request(task_description, context)
        self.logger(f"[ModelRouter] {decision.reasoning}")
        
        # Try primary model
        try:
            return self._execute_with_config(
                decision.selected_config,
                prompt,
                system_prompt,
            )
        except Exception as e:
            self.logger(f"[ModelRouter] Primary model failed: {e}")
            
            # Try fallback models
            for fallback_config in decision.fallback_configs:
                try:
                    self.logger(f"[ModelRouter] Trying fallback: {fallback_config.model_name}")
                    return self._execute_with_config(
                        fallback_config,
                        prompt,
                        system_prompt,
                    )
                except Exception as fallback_error:
                    self.logger(f"[ModelRouter] Fallback failed: {fallback_error}")
                    continue
            
            # All models failed
            raise RuntimeError(f"All model routing attempts failed. Last error: {e}")

    def _execute_with_config(
        self,
        config: ModelConfig,
        prompt: str,
        system_prompt: str | None = None,
    ) -> str:
        """Execute LLM call with specific model configuration."""
        # Temporarily override environment for this call
        original_provider = os.environ.get("MICA_LLM_PROVIDER")
        original_model = os.environ.get("MICA_LLM_MODEL")
        
        try:
            # Set provider and model for this call
            os.environ["MICA_LLM_PROVIDER"] = config.provider
            os.environ["MICA_LLM_MODEL"] = config.model_name
            
            # Make the call
            result = call_llm_text(
                prompt=prompt,
                system=system_prompt,
                timeout=config.timeout,
            )
            
            # Track usage
            self._track_usage(config, len(prompt), len(result))
            
            return result
        
        finally:
            # Restore original environment
            if original_provider is not None:
                os.environ["MICA_LLM_PROVIDER"] = original_provider
            else:
                os.environ.pop("MICA_LLM_PROVIDER", None)
            
            if original_model is not None:
                os.environ["MICA_LLM_MODEL"] = original_model
            else:
                os.environ.pop("MICA_LLM_MODEL", None)

    def _track_usage(self, config: ModelConfig, input_length: int, output_length: int) -> None:
        """Track usage statistics and costs."""
        model_key = f"{config.provider}:{config.model_name}"
        
        if model_key not in self.usage_stats:
            self.usage_stats[model_key] = {
                "call_count": 0,
                "total_tokens": 0,
                "total_cost": 0.0,
            }
        
        # Estimate tokens (rough approximation)
        input_tokens = (input_length / 4)  # ~4 chars per token
        output_tokens = (output_length / 4)
        total_tokens = input_tokens + output_tokens
        
        # Calculate cost
        cost = (total_tokens / 1000) * config.cost_per_1k_tokens
        
        # Update stats
        self.usage_stats[model_key]["call_count"] += 1
        self.usage_stats[model_key]["total_tokens"] += total_tokens
        self.usage_stats[model_key]["total_cost"] += cost
        self.current_hourly_cost += cost
        
        self.logger(
            f"[ModelRouter] Usage: {model_key} - "
            f"Tokens: {total_tokens:.0f}, Cost: ${cost:.4f}"
        )

    def get_usage_stats(self) -> dict[str, Any]:
        """Get current usage statistics."""
        return {
            "models": self.usage_stats,
            "current_hourly_cost": self.current_hourly_cost,
            "budget_limit": self.budget_limit_hourly,
            "budget_remaining": max(0, self.budget_limit_hourly - self.current_hourly_cost),
        }

    def reset_usage_stats(self) -> None:
        """Reset usage statistics."""
        self.usage_stats = {}
        self.current_hourly_cost = 0.0
        self.logger("[ModelRouter] Usage statistics reset")