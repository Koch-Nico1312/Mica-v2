"""End-to-end coverage for the advanced agent action.

``actions.advanced_agent`` was unreachable for its whole lifetime: the modules in
``core/`` imported each other as top-level names, so importing the action raised
``ModuleNotFoundError``.  The tests below pin the action's contract (it returns a
string and never raises), the code agent's file targeting and the sandbox.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import core.code_agent as code_agent_module
from actions.advanced_agent import advanced_agent
from core.code_agent import CodeAgent, default_allowed_roots


@pytest.fixture(autouse=True)
def _offline_llm(monkeypatch):
    """Make every LLM call fail fast and deterministically - no Ollama, no cloud."""
    monkeypatch.setenv("MICA_LLM_PROVIDER", "openai_api")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "reminder_scheduler.py").write_text("JOBS = []\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text(
        "fastapi==0.141.1\n"
        'comtypes; sys_platform == "win32"\n'
        "pillow[extra]>=10\n"
        "# a comment\n"
        "-r other.txt\n",
        encoding="utf-8",
    )
    return tmp_path


def _fake_llm(modification: str):
    def fake(prompt: str, *args, **kwargs) -> str:
        if "Classify this code task" in prompt:
            return "simple"          # simple => test_required False => no test run
        if "Modified code" in prompt:
            return modification
        if "concise description" in prompt:
            return "Probe project."
        return ""

    return fake


def test_advanced_agent_modules_import_as_package_members():
    for module in (
        "core.code_agent",
        "core.agent_coordinator",
        "core.model_router",
        "core.isolated_plugin_loader",
        "core.agent_integration",
    ):
        assert importlib.import_module(module) is not None


def test_default_sandbox_includes_the_installation_itself(monkeypatch):
    monkeypatch.delenv("MICA_CODE_AGENT_ROOTS", raising=False)
    roots = {root.resolve() for root in default_allowed_roots()}
    assert Path(code_agent_module.__file__).resolve().parents[2] in roots


def test_sandbox_env_var_replaces_the_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("MICA_CODE_AGENT_ROOTS", str(tmp_path))
    assert {root.resolve() for root in default_allowed_roots()} == {tmp_path.resolve()}


def test_inspect_project_reports_metadata_and_skips_tooling_dirs(tmp_path):
    project = _project(tmp_path)
    vendor = project / ".venv-local" / "Lib" / "site-packages" / "vendored"
    vendor.mkdir(parents=True)
    for index in range(5):
        (vendor / f"lib{index}.py").write_text("x = 1\n", encoding="utf-8")

    out = advanced_agent(
        {
            "action": "inspect_project",
            "project_path": str(project),
            "allowed_roots": [str(tmp_path)],
        }
    )

    assert f"Name: {project.name}" in out
    assert "Language: python" in out
    assert "Files: 2" in out          # the five vendored files must not be counted
    assert "vendored" not in out
    assert "Entry Points: app.py" in out


def test_dependencies_drop_version_markers_and_extras(tmp_path):
    project = _project(tmp_path)
    context = CodeAgent(project, allowed_roots=[str(tmp_path)]).inspect_project()
    assert context.dependencies == ["comtypes", "fastapi", "pillow"]


def test_analyze_task_targets_the_file_named_in_the_task(tmp_path):
    project = _project(tmp_path)
    out = advanced_agent(
        {
            "action": "analyze_task",
            "project_path": str(project),
            "task_description": "Fix the reminder logic in reminder_scheduler.py",
            "allowed_roots": [str(tmp_path)],
        }
    )

    assert "reminder_scheduler.py" in out
    # The ".py" token used to match every python file, so app.py came back as a
    # target even though the task never mentioned it.
    assert "app.py" not in out


def test_analyze_task_without_a_named_file_scores_name_tokens(tmp_path):
    project = _project(tmp_path)
    out = advanced_agent(
        {
            "action": "analyze_task",
            "project_path": str(project),
            "task_description": "Add retry logic to the reminder scheduler",
            "allowed_roots": [str(tmp_path)],
        }
    )

    assert "reminder_scheduler.py" in out
    assert "app.py" not in out


def test_project_outside_the_sandbox_returns_an_error_string(tmp_path, monkeypatch):
    project = _project(tmp_path)
    monkeypatch.setenv("MICA_CODE_AGENT_ROOTS", str(tmp_path / "somewhere-else"))

    out = advanced_agent({"action": "inspect_project", "project_path": str(project)})

    assert out.startswith("Advanced agent action failed:")
    assert "not in allowed directories" in out


def test_execute_task_writes_only_the_target_file(tmp_path, monkeypatch):
    project = _project(tmp_path)
    monkeypatch.setattr(code_agent_module, "call_llm_text", _fake_llm("VALUE = 2\n"))

    out = advanced_agent(
        {
            "action": "execute_task",
            "project_path": str(project),
            "task_description": "Change the value in app.py",
            "allowed_roots": [str(tmp_path)],
        }
    )

    assert "Task Executed Successfully" in out
    assert (project / "app.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    assert (project / "reminder_scheduler.py").read_text(encoding="utf-8") == "JOBS = []\n"
    assert (project / "app.py.backup").read_text(encoding="utf-8") == "VALUE = 1\n"


def test_execute_task_never_truncates_a_file_on_an_empty_answer(tmp_path, monkeypatch):
    project = _project(tmp_path)
    monkeypatch.setattr(code_agent_module, "call_llm_text", _fake_llm("   \n"))

    out = advanced_agent(
        {
            "action": "execute_task",
            "project_path": str(project),
            "task_description": "Change the value in app.py",
            "allowed_roots": [str(tmp_path)],
        }
    )

    assert "Modified Files: None" in out
    assert (project / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def test_player_receives_the_sub_agent_log_lines(tmp_path):
    project = _project(tmp_path)

    class Player:
        def __init__(self) -> None:
            self.messages: list[str] = []

        def write_log(self, message: str) -> None:
            self.messages.append(message)

    player = Player()
    advanced_agent(
        {
            "action": "inspect_project",
            "project_path": str(project),
            "allowed_roots": [str(tmp_path)],
        },
        player=player,
    )

    assert any("Inspecting project" in message for message in player.messages)


def test_route_llm_returns_a_routing_decision_without_a_project():
    out = advanced_agent(
        {
            "action": "route_llm",
            "task_description": "Summarise this short note",
            "task_context": {"complexity": "low"},
        }
    )

    assert "Model Routing Decision:" in out
    assert "Selected Model:" in out
    assert "Estimated Cost: $" in out


def test_plugin_health_explains_an_empty_registry():
    out = advanced_agent({"action": "plugin_health"})

    assert out.startswith("Plugin Health Status:")
    assert "plugin" in out.lower()
    assert len(out.splitlines()) > 1


def test_submit_task_reports_a_failed_agent_run_instead_of_raising():
    out = advanced_agent(
        {
            "action": "submit_task",
            "agent_type": "research",
            "task_description": "Summarise the release notes",
        }
    )

    assert "Agent Task Result:" in out
    assert "Agent Type: research" in out
    assert "Success: False" in out


def test_unknown_action_lists_the_available_actions():
    out = advanced_agent({"action": "definitely-not-an-action"})

    assert "Unknown action: definitely-not-an-action" in out
    assert "inspect_project" in out
