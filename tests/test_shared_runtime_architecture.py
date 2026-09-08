"""Dependency-direction checks for shared Codex Assist runtime modules."""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path("custom_components/codex_assist")


def _imports(module: str) -> set[str]:
    tree = ast.parse((PACKAGE / module).read_text())
    return {
        (node.module or "").split(".")[-1]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level
    }


def test_ai_task_does_not_import_conversation() -> None:
    assert "conversation" not in _imports("ai_task.py")


def test_shared_modules_do_not_import_home_assistant_surfaces() -> None:
    forbidden = {"conversation", "ai_task", "config_flow"}
    for module in (
        "settings.py",
        "turn_runtime.py",
        "transcript.py",
        "telemetry.py",
        "serialization.py",
    ):
        assert not _imports(module) & forbidden


def test_conversation_has_no_duplicate_shared_helpers() -> None:
    tree = ast.parse((PACKAGE / "conversation.py").read_text())
    names = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not names & {
        "_run_tool_rounds",
        "_stream_codex_turn_into_chat_log",
        "_codex_stream_to_assistant_deltas",
        "_codex_input_from_chat_log",
        "_trim_codex_input_items",
        "_codex_tools_from_chat_log",
        "_refresh_runtime_tokens",
        "_instructions_from_chat_log",
    }
