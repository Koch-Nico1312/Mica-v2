"""
Dedicated Code Agent for local-first project management.

This agent handles project inspection, code task analysis, modifications (edits/generation),
and testing within a restricted workspace. Designed for SysCore, CyberDeck, and other
developer projects with local-first architecture.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from llm_client import call_llm_text, get_llm_settings


class TaskTier(Enum):
    """Task complexity tiers for model routing."""
    SIMPLE = "simple"      # Single file, <100 lines, no dependencies
    MEDIUM = "medium"      # Multi-file, <500 lines, standard dependencies
    COMPLEX = "complex"    # Multi-file, >500 lines, complex dependencies
    CRITICAL = "critical"  # Production code, security-sensitive, complex logic


@dataclass
class ProjectContext:
    """Project metadata and context."""
    name: str
    root_path: Path
    language: str = "python"
    files: list[Path] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)
    description: str = ""


@dataclass
class CodeTask:
    """A code modification task."""
    description: str
    tier: TaskTier
    target_files: list[Path] = field(default_factory=list)
    expected_changes: list[str] = field(default_factory=list)
    test_required: bool = True


@dataclass
class TaskResult:
    """Result of a code task execution."""
    success: bool
    message: str
    modified_files: list[Path] = field(default_factory=list)
    test_results: str = ""
    errors: list[str] = field(default_factory=list)


class CodeAgent:
    """
    Local-first code agent for project management.
    
    Features:
    - Project inspection and metadata extraction
    - Code task analysis and planning
    - File modifications (edits/generation)
    - Automated testing and validation
    - Status reporting
    """

    def __init__(
        self,
        project_root: Path | str,
        allowed_roots: list[Path | str] | None = None,
        logger: Callable[[str], None] = print,
    ):
        self.project_root = Path(project_root).resolve()
        self.logger = logger
        
        # Security: restrict to allowed project roots
        self.allowed_roots = [Path(p).resolve() for p in (allowed_roots or [])]
        if not self.allowed_roots:
            # Default allowed roots
            self.allowed_roots = [
                Path.home() / "Desktop" / "JarvisProjects",
                Path.home() / "Projects",
                Path.home() / "code",
                Path.home() / "src",
            ]
        
        self._validate_project_root()
        self.context: Optional[ProjectContext] = None

    def _validate_project_root(self) -> None:
        """Ensure project root is within allowed directories."""
        if not self.project_root.exists():
            raise ValueError(f"Project root does not exist: {self.project_root}")
        
        for allowed in self.allowed_roots:
            try:
                self.project_root.relative_to(allowed)
                return
            except ValueError:
                continue
        
        raise ValueError(
            f"Project root {self.project_root} is not in allowed directories: "
            f"{self.allowed_roots}"
        )

    def inspect_project(self) -> ProjectContext:
        """
        Inspect project structure and extract metadata.
        
        Returns:
            ProjectContext with project metadata
        """
        self.logger(f"[CodeAgent] Inspecting project: {self.project_root}")
        
        # Detect language from file extensions
        language = self._detect_language()
        
        # Find all source files
        files = self._find_source_files(language)
        
        # Extract dependencies
        dependencies = self._extract_dependencies(language)
        
        # Find entry points
        entry_points = self._find_entry_points(language, files)
        
        # Generate description
        description = self._generate_description(files, language)
        
        self.context = ProjectContext(
            name=self.project_root.name,
            root_path=self.project_root,
            language=language,
            files=files,
            dependencies=dependencies,
            entry_points=entry_points,
            description=description,
        )
        
        self.logger(
            f"[CodeAgent] Project inspected: {len(files)} files, "
            f"{language}, {len(dependencies)} dependencies"
        )
        return self.context

    def _detect_language(self) -> str:
        """Detect primary programming language from file extensions."""
        extensions = {
            "python": [".py"],
            "javascript": [".js", ".jsx", ".mjs"],
            "typescript": [".ts", ".tsx"],
            "go": [".go"],
            "rust": [".rs"],
            "java": [".java"],
            "csharp": [".cs"],
            "cpp": [".cpp", ".cc", ".cxx"],
        }
        
        counts = {lang: 0 for lang in extensions}
        for file_path in self.project_root.rglob("*"):
            if file_path.is_file():
                for lang, exts in extensions.items():
                    if file_path.suffix in exts:
                        counts[lang] += 1
        
        # Return language with most files, default to python
        return max(counts, key=counts.get) if any(counts.values()) else "python"

    def _find_source_files(self, language: str) -> list[Path]:
        """Find all source files for the given language."""
        ext_map = {
            "python": [".py"],
            "javascript": [".js", ".jsx", ".mjs"],
            "typescript": [".ts", ".tsx"],
            "go": [".go"],
            "rust": [".rs"],
            "java": [".java"],
            "csharp": [".cs"],
            "cpp": [".cpp", ".cc", ".cxx"],
        }
        
        extensions = ext_map.get(language, [".py"])
        files = []
        
        for ext in extensions:
            files.extend(self.project_root.rglob(f"*{ext}"))
        
        # Filter out common exclusion patterns
        excluded_dirs = {"node_modules", ".git", "__pycache__", "venv", "env", ".venv"}
        files = [
            f for f in files
            if not any(excluded in f.parts for excluded in excluded_dirs)
        ]
        
        return sorted(files)

    def _extract_dependencies(self, language: str) -> list[str]:
        """Extract project dependencies from config files."""
        dependencies = []
        
        if language == "python":
            # Check requirements.txt, pyproject.toml, setup.py
            for dep_file in ["requirements.txt", "pyproject.toml", "setup.py"]:
                path = self.project_root / dep_file
                if path.exists():
                    if dep_file == "requirements.txt":
                        deps = path.read_text(encoding="utf-8").strip().split("\n")
                        dependencies.extend(
                            d.split("==")[0].split(">=")[0].split("<=")[0].strip()
                            for d in deps
                            if d.strip() and not d.startswith("#")
                        )
                    elif dep_file == "pyproject.toml":
                        # Simple parsing for dependencies
                        content = path.read_text(encoding="utf-8")
                        match = re.search(r"dependencies\s*=\s*\[(.*?)\]", content, re.DOTALL)
                        if match:
                            deps = re.findall(r'"([^"]+)"', match.group(1))
                            dependencies.extend(deps)
        
        elif language in ["javascript", "typescript"]:
            # Check package.json
            package_json = self.project_root / "package.json"
            if package_json.exists():
                try:
                    data = json.loads(package_json.read_text(encoding="utf-8"))
                    deps = data.get("dependencies", {})
                    dependencies.extend(deps.keys())
                except (json.JSONDecodeError, IOError):
                    pass
        
        return sorted(set(dependencies))

    def _find_entry_points(self, language: str, files: list[Path]) -> list[str]:
        """Find potential entry points (main files, index files, etc.)."""
        entry_points = []
        
        if language == "python":
            candidates = ["main.py", "app.py", "run.py", "__main__.py"]
            for candidate in candidates:
                if (self.project_root / candidate).exists():
                    entry_points.append(candidate)
        
        elif language in ["javascript", "typescript"]:
            candidates = ["index.js", "index.ts", "main.js", "main.ts", "app.js", "app.ts"]
            for candidate in candidates:
                if (self.project_root / candidate).exists():
                    entry_points.append(candidate)
        
        elif language == "go":
            if (self.project_root / "main.go").exists():
                entry_points.append("main.go")
        
        elif language == "rust":
            if (self.project_root / "src" / "main.rs").exists():
                entry_points.append("src/main.rs")
        
        return entry_points

    def _generate_description(self, files: list[Path], language: str) -> str:
        """Generate a project description using LLM."""
        if not files:
            return f"Empty {language} project"
        
        # Sample first few files for context
        sample_files = files[:5]
        sample_content = ""
        for file_path in sample_files:
            try:
                content = file_path.read_text(encoding="utf-8")[:500]
                sample_content += f"\n--- {file_path.relative_to(self.project_root)} ---\n{content}\n"
            except Exception:
                pass
        
        prompt = f"""
Analyze this {language} project and provide a concise description (2-3 sentences).

Project name: {self.project_root.name}
Files sampled:
{sample_content}

Description:"""

        try:
            return call_llm_text(prompt, timeout=30).strip()
        except Exception as e:
            self.logger(f"[CodeAgent] LLM description failed: {e}")
            return f"{language.capitalize()} project with {len(files)} files"

    def analyze_task(self, task_description: str) -> CodeTask:
        """
        Analyze a code task and determine its complexity tier.
        
        Args:
            task_description: Natural language description of the task
            
        Returns:
            CodeTask with tier analysis
        """
        self.logger(f"[CodeAgent] Analyzing task: {task_description[:100]}...")
        
        if not self.context:
            self.inspect_project()
        
        # Use LLM to classify task tier
        prompt = f"""
Classify this code task by complexity.

Project context:
- Language: {self.context.language}
- Files: {len(self.context.files)}
- Dependencies: {len(self.context.dependencies)}

Task: {task_description}

Return ONLY one of these tiers: simple, medium, complex, critical

Rules:
- simple: Single file change, <100 lines, no new dependencies
- medium: Multi-file change, <500 lines, standard dependencies
- complex: Multi-file change, >500 lines, complex logic/dependencies
- critical: Production code, security-sensitive, core infrastructure

Tier:"""

        try:
            tier_str = call_llm_text(prompt, timeout=30).strip().lower()
            tier = TaskTier(tier_str) if tier_str in [t.value for t in TaskTier] else TaskTier.MEDIUM
        except Exception as e:
            self.logger(f"[CodeAgent] Tier classification failed: {e}")
            tier = TaskTier.MEDIUM
        
        # Identify target files
        target_files = self._identify_target_files(task_description)
        
        return CodeTask(
            description=task_description,
            tier=tier,
            target_files=target_files,
            test_required=tier in [TaskTier.MEDIUM, TaskTier.COMPLEX, TaskTier.CRITICAL],
        )

    def _identify_target_files(self, task_description: str) -> list[Path]:
        """Identify files likely to be modified by the task."""
        if not self.context:
            return []
        
        # Simple keyword matching for now
        keywords = re.findall(r"\b\w+\b", task_description.lower())
        target_files = []
        
        for file_path in self.context.files:
            file_name = file_path.name.lower()
            # Check if any keyword matches file name
            if any(keyword in file_name for keyword in keywords):
                target_files.append(file_path)
        
        # If no matches, return entry points
        if not target_files and self.context.entry_points:
            target_files = [self.project_root / ep for ep in self.context.entry_points]
        
        return target_files[:5]  # Limit to top 5 candidates

    def execute_task(self, task: CodeTask) -> TaskResult:
        """
        Execute a code task.
        
        Args:
            task: CodeTask to execute
            
        Returns:
            TaskResult with execution status
        """
        self.logger(f"[CodeAgent] Executing {task.tier.value} task: {task.description[:100]}...")
        
        try:
            # Generate code changes
            modifications = self._generate_modifications(task)
            
            # Apply modifications
            modified_files = []
            for file_path, new_content in modifications.items():
                self._safe_write_file(file_path, new_content)
                modified_files.append(file_path)
                self.logger(f"[CodeAgent] Modified: {file_path.relative_to(self.project_root)}")
            
            # Run tests if required
            test_results = ""
            if task.test_required:
                test_results = self._run_tests()
            
            return TaskResult(
                success=True,
                message=f"Task completed successfully. Modified {len(modified_files)} file(s).",
                modified_files=modified_files,
                test_results=test_results,
            )
        
        except Exception as e:
            self.logger(f"[CodeAgent] Task execution failed: {e}")
            return TaskResult(
                success=False,
                message=f"Task execution failed: {e}",
                errors=[str(e)],
            )

    def _generate_modifications(self, task: CodeTask) -> dict[Path, str]:
        """Generate code modifications using LLM."""
        modifications = {}
        
        # Read current file contents
        file_contexts = {}
        for file_path in task.target_files:
            if file_path.exists():
                try:
                    file_contexts[file_path] = file_path.read_text(encoding="utf-8")
                except Exception:
                    file_contexts[file_path] = ""
        
        # Generate modifications for each file
        for file_path, current_content in file_contexts.items():
            prompt = f"""
You are a senior {self.context.language} developer. Modify the following code to:
{task.description}

Current file: {file_path.relative_to(self.project_root)}
Current content:
{current_content}

Return ONLY the complete modified code. No explanation, no markdown, no backticks.
If the file doesn't need changes, return the original content exactly.

Modified code:"""

            try:
                new_content = call_llm_text(prompt, timeout=60)
                modifications[file_path] = new_content
            except Exception as e:
                self.logger(f"[CodeAgent] Failed to generate modification for {file_path}: {e}")
        
        return modifications

    def _safe_write_file(self, file_path: Path, content: str) -> None:
        """Safely write file with backup."""
        # Validate path is within project root
        try:
            file_path.relative_to(self.project_root)
        except ValueError:
            raise ValueError(f"Cannot write outside project root: {file_path}")
        
        # Create backup
        if file_path.exists():
            backup_path = file_path.with_suffix(file_path.suffix + ".backup")
            backup_path.write_bytes(file_path.read_bytes())
        
        # Write new content
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

    def _run_tests(self) -> str:
        """Run project tests and return results."""
        if not self.context:
            return "No project context available"
        
        language = self.context.language
        test_commands = {
            "python": ["python", "-m", "pytest", "-v"],
            "javascript": ["npm", "test"],
            "typescript": ["npm", "test"],
            "go": ["go", "test", "./..."],
            "rust": ["cargo", "test"],
        }
        
        cmd = test_commands.get(language)
        if not cmd:
            return f"No test command configured for {language}"
        
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=120,
            )
            
            output = result.stdout + result.stderr
            if result.returncode == 0:
                self.logger(f"[CodeAgent] Tests passed")
                return "Tests passed successfully"
            else:
                self.logger(f"[CodeAgent] Tests failed: {output[:200]}")
                return f"Tests failed:\n{output[:500]}"
        
        except subprocess.TimeoutExpired:
            return "Tests timed out"
        except Exception as e:
            return f"Test execution failed: {e}"

    def generate_status_report(self) -> str:
        """Generate a comprehensive status report of the project."""
        if not self.context:
            self.inspect_project()
        
        report = f"""
# Project Status Report: {self.context.name}

## Overview
- Language: {self.context.language}
- Root: {self.project_root}
- Total Files: {len(self.context.files)}
- Dependencies: {len(self.context.dependencies)}
- Entry Points: {', '.join(self.context.entry_points) or 'None'}

## Description
{self.context.description}

## Files
"""
        for file_path in self.context.files[:20]:  # Limit to first 20 files
            try:
                size = file_path.stat().st_size
                report += f"- {file_path.relative_to(self.project_root)} ({size} bytes)\n"
            except Exception:
                report += f"- {file_path.relative_to(self.project_root)} (size unknown)\n"
        
        if len(self.context.files) > 20:
            report += f"... and {len(self.context.files) - 20} more files\n"
        
        report += "\n## Dependencies\n"
        for dep in self.context.dependencies[:15]:
            report += f"- {dep}\n"
        
        if len(self.context.dependencies) > 15:
            report += f"... and {len(self.context.dependencies) - 15} more dependencies\n"
        
        return report.strip()