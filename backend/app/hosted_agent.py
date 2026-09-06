from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import settings
from .model_client import ModelClient
from .sandbox.base import Sandbox

SYSTEM_PROMPT = """You are APEX, an autonomous coding agent. You are operating inside an isolated \
per-user sandbox, not the host machine. Every tool call performs a real operation inside that \
sandbox and returns real results.

Rules:
1. Never claim a task is done without real evidence (a command actually exited 0, a file was \
actually written). If you haven't verified something, say so.
2. Prefer edit_file (exact string replacement) over write_file for existing files.
3. This sandbox may have no network access and a small resource budget -- if a command fails for \
that reason, explain it plainly rather than retrying blindly.
4. Keep responses concise.
"""

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {"name": "read_file", "description": "Read a file in the sandbox workspace.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Create or fully overwrite a file in the sandbox workspace.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                       "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace an exact, unique substring in an existing file.",
     "input_schema": {"type": "object", "properties": {
         "path": {"type": "string"}, "old_str": {"type": "string"}, "new_str": {"type": "string"}},
         "required": ["path", "old_str", "new_str"]}},
    {"name": "list_directory", "description": "List files/directories in the sandbox workspace.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string", "default": "."}}}},
    {"name": "search_code", "description": "Search sandbox files for a substring or regex pattern.",
     "input_schema": {"type": "object", "properties": {
         "pattern": {"type": "string"}, "regex": {"type": "boolean", "default": False}}, "required": ["pattern"]}},
    {"name": "run_command", "description": "Run a shell command inside the isolated sandbox.",
     "input_schema": {"type": "object", "properties": {
         "command": {"type": "string"}, "timeout_seconds": {"type": "integer", "default": 60}},
         "required": ["command"]}},
]


@dataclass
class TurnEvent:
    kind: str  # "text" | "tool_call" | "tool_result" | "stopped" | "error"
    payload: dict[str, Any] = field(default_factory=dict)


class HostedAgent:
    """One instance per active chat session (one Sandbox, one message history)."""

    def __init__(self, sandbox: Sandbox, model_client: ModelClient | None = None):
        self.sandbox = sandbox
        self.model_client = model_client or ModelClient()
        self.messages: list[dict[str, Any]] = []

    def _execute_tool(self, name: str, tool_input: dict[str, Any]) -> str:
        try:
            if name == "read_file":
                return self.sandbox.read_file(tool_input["path"])
            if name == "write_file":
                n = self.sandbox.write_file(tool_input["path"], tool_input["content"])
                return f"Wrote {n} bytes to {tool_input['path']}"
            if name == "edit_file":
                n = self.sandbox.edit_file(tool_input["path"], tool_input["old_str"], tool_input["new_str"])
                return f"Edited {tool_input['path']} ({n} bytes now)"
            if name == "list_directory":
                return self.sandbox.list_directory(tool_input.get("path", "."))
            if name == "search_code":
                return self.sandbox.search_code(tool_input["pattern"], tool_input.get("regex", False))
            if name == "run_command":
                result = self.sandbox.run_command(tool_input["command"], tool_input.get("timeout_seconds", 60))
                if result.denied_reason:
                    return f"DENIED: {result.denied_reason}"
                return f"[exit_code={result.exit_code}]\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            return f"Unknown tool: {name}"
        except Exception as exc:  # noqa: BLE001 - surface real errors to the model
            return f"TOOL ERROR: {type(exc).__name__}: {exc}"

    def run_turn(self, user_message: str) -> list[TurnEvent]:
        events: list[TurnEvent] = []
        self.messages.append({"role": "user", "content": user_message})

        for _ in range(settings.MAX_TOOL_ITERATIONS_PER_MESSAGE):
            response = self.model_client.send(system=SYSTEM_PROMPT, messages=self.messages, tools=TOOL_DEFINITIONS)
            self.messages.append({"role": "assistant", "content": response.content})

            tool_calls = [b for b in response.content if b.get("type") == "tool_use"]
            for b in response.content:
                if b.get("type") == "text" and b.get("text", "").strip():
                    events.append(TurnEvent("text", {"text": b["text"]}))

            if not tool_calls:
                return events

            tool_results = []
            for call in tool_calls:
                events.append(TurnEvent("tool_call", {"name": call["name"], "input": call["input"]}))
                output = self._execute_tool(call["name"], call["input"])
                events.append(TurnEvent("tool_result", {"name": call["name"], "output": output}))
                tool_results.append({"type": "tool_result", "tool_use_id": call["id"], "content": output})
            self.messages.append({"role": "user", "content": tool_results})

        events.append(TurnEvent("stopped", {
            "reason": f"Hit max_iterations={settings.MAX_TOOL_ITERATIONS_PER_MESSAGE} without finishing."
        }))
        return events
