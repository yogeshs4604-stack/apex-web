"""INSECURE local-dev sandbox: no isolation between users at all.

This runs shell commands and file operations directly on the host machine,
scoped only by a per-session temp directory -- there is NOTHING stopping a
malicious command from reading other users' data, attacking the host, or
using the machine's network. It exists purely so this codebase can be run
and tested end-to-end on a machine without Docker (the sandbox this was
built in has no Docker daemon). The constructor requires an explicit
`i_understand_this_is_insecure=True` argument so it cannot be wired up for
a real deployment by a stray default value.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from .base import Sandbox, SandboxCommandResult

MAX_OUTPUT_CHARS = 20_000


class LocalDevSandbox(Sandbox):
    def __init__(self, session_id: str | None = None, *, i_understand_this_is_insecure: bool = False):
        if not i_understand_this_is_insecure:
            raise RuntimeError(
                "LocalDevSandbox provides NO isolation between users and must never be used in "
                "a real deployment. Pass i_understand_this_is_insecure=True only for local "
                "development/testing on a machine without Docker."
            )
        self.session_id = session_id or str(uuid.uuid4())
        self._root = Path(tempfile.mkdtemp(prefix=f"apex-devsession-{self.session_id}-"))

    def _resolve(self, relative_path: str) -> Path:
        candidate = (self._root / relative_path).resolve()
        if not str(candidate).startswith(str(self._root.resolve())):
            raise ValueError(f"Refusing to access path outside session workspace: {relative_path}")
        return candidate

    def read_file(self, path: str) -> str:
        p = self._resolve(path)
        if not p.exists():
            raise FileNotFoundError(path)
        return p.read_text(encoding="utf-8", errors="replace")

    def write_file(self, path: str, content: str) -> int:
        p = self._resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8")
        p.write_bytes(data)
        return len(data)

    def edit_file(self, path: str, old_str: str, new_str: str) -> int:
        p = self._resolve(path)
        original = p.read_text(encoding="utf-8")
        count = original.count(old_str)
        if count == 0:
            raise ValueError("old_str not found")
        if count > 1:
            raise ValueError(f"old_str is ambiguous ({count} matches)")
        updated = original.replace(old_str, new_str, 1)
        p.write_text(updated, encoding="utf-8")
        return len(updated.encode("utf-8"))

    def list_directory(self, path: str = ".") -> str:
        p = self._resolve(path)
        if not p.exists():
            raise FileNotFoundError(path)
        lines = []
        for entry in sorted(p.rglob("*")):
            rel = entry.relative_to(self._root)
            lines.append(f"{rel}{'/' if entry.is_dir() else ''}")
        return "\n".join(lines) if lines else "(empty)"

    def search_code(self, pattern: str, regex: bool = False) -> str:
        matches = []
        compiled = re.compile(pattern) if regex else None
        for p in sorted(self._root.rglob("*")):
            if not p.is_file():
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                hit = compiled.search(line) if compiled else (pattern in line)
                if hit:
                    matches.append(f"{p.relative_to(self._root)}:{lineno}: {line.strip()[:200]}")
        return "\n".join(matches) if matches else "No matches found."

    def run_command(self, command: str, timeout_seconds: int = 60) -> SandboxCommandResult:
        try:
            proc = subprocess.run(
                command, shell=True, cwd=str(self._root),
                capture_output=True, text=True, timeout=timeout_seconds,
            )
            return SandboxCommandResult(
                exit_code=proc.returncode,
                stdout=proc.stdout[-MAX_OUTPUT_CHARS:],
                stderr=proc.stderr[-MAX_OUTPUT_CHARS:],
            )
        except subprocess.TimeoutExpired:
            return SandboxCommandResult(exit_code=None, stdout="", stderr=f"Timed out after {timeout_seconds}s")

    def destroy(self) -> None:
        shutil.rmtree(self._root, ignore_errors=True)
