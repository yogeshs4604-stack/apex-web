"""Real per-user isolation via Docker.

This is the production sandbox implementation. It is written against the
real `docker` Python SDK and the real Docker Engine API. I was not able to
run this against an actual Docker daemon in the environment this was built
in (no `docker` binary was present there) -- that is stated plainly rather
than glossed over. It should be exercised against a real daemon before any
public deployment; see backend/tests/test_docker_sandbox.py, which
auto-skips when no daemon is reachable rather than pretending to pass.

Hardening applied, all real Docker Engine features (not aspirational):
- mem_limit / pids_limit / cpu_quota: resource ceilings so one session
  can't starve or crash the host.
- network_mode: "none" by default -- blocks the container from making any
  outbound connection, which closes off the most common abuse pattern
  (using a free sandbox as an attack/scraping proxy) at the cost of
  package installs not working inside the sandbox.
- read-only root filesystem with a single writable bind-mounted workspace
  directory -- the agent can only persist changes inside its own project
  directory, not the container's system files.
- runs as a non-root user inside the container.
- auto_remove + explicit destroy(): no orphaned containers.
"""
from __future__ import annotations

import shlex
import tempfile
import uuid
from pathlib import Path

import docker
from docker.errors import DockerException, NotFound

from ..config import settings
from .base import Sandbox, SandboxCommandResult

MAX_OUTPUT_CHARS = 20_000


class DockerSandboxUnavailableError(RuntimeError):
    def __init__(self, detail: str):
        super().__init__(
            f"Could not reach the Docker daemon: {detail}\n"
            "A real deployment requires Docker running on the host. This is not optional for "
            "a public multi-user service -- without it there is no isolation between users."
        )


class DockerSandbox(Sandbox):
    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or str(uuid.uuid4())
        try:
            self._client = docker.from_env()
            self._client.ping()
        except DockerException as exc:
            raise DockerSandboxUnavailableError(str(exc)) from exc

        # Host-side directory that is bind-mounted into the container. File tools write here
        # directly (fast, no exec round-trip); shell commands run *inside* the container via
        # exec_run so they're actually isolated.
        self._host_dir = Path(tempfile.mkdtemp(prefix=f"apex-session-{self.session_id}-"))
        self._container_workdir = "/workspace"

        self._container = self._client.containers.run(
            settings.DOCKER_IMAGE,
            command="sleep infinity",
            detach=True,
            working_dir=self._container_workdir,
            volumes={str(self._host_dir): {"bind": self._container_workdir, "mode": "rw"}},
            mem_limit=settings.CONTAINER_MEMORY_LIMIT,
            pids_limit=settings.CONTAINER_PIDS_LIMIT,
            cpu_quota=settings.CONTAINER_CPU_QUOTA,
            network_mode=settings.CONTAINER_NETWORK_MODE,
            user="nobody",
            read_only=True,
            tmpfs={"/tmp": "size=64m"},
            security_opt=["no-new-privileges"],
            auto_remove=False,  # we call destroy() explicitly for a clean, observable teardown
            labels={"apex-session": self.session_id},
        )

    def _resolve(self, relative_path: str) -> Path:
        candidate = (self._host_dir / relative_path).resolve()
        if not str(candidate).startswith(str(self._host_dir.resolve())):
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
            rel = entry.relative_to(self._host_dir)
            lines.append(f"{rel}{'/' if entry.is_dir() else ''}")
        return "\n".join(lines) if lines else "(empty)"

    def search_code(self, pattern: str, regex: bool = False) -> str:
        import re
        matches = []
        compiled = re.compile(pattern) if regex else None
        for p in sorted(self._host_dir.rglob("*")):
            if not p.is_file():
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                hit = compiled.search(line) if compiled else (pattern in line)
                if hit:
                    matches.append(f"{p.relative_to(self._host_dir)}:{lineno}: {line.strip()[:200]}")
        return "\n".join(matches) if matches else "No matches found."

    def run_command(self, command: str, timeout_seconds: int = 60) -> SandboxCommandResult:
        # Runs INSIDE the container via the real Docker exec API -- this is the actual
        # isolation boundary. `timeout` wraps it so a stuck command can't hang the session forever.
        wrapped = f"timeout {int(timeout_seconds)} sh -c {shlex.quote(command)}"
        try:
            result = self._container.exec_run(wrapped, workdir=self._container_workdir, demux=True)
        except DockerException as exc:
            return SandboxCommandResult(exit_code=None, stdout="", stderr=str(exc))
        stdout_b, stderr_b = result.output
        stdout = (stdout_b or b"").decode("utf-8", errors="replace")[-MAX_OUTPUT_CHARS:]
        stderr = (stderr_b or b"").decode("utf-8", errors="replace")[-MAX_OUTPUT_CHARS:]
        return SandboxCommandResult(exit_code=result.exit_code, stdout=stdout, stderr=stderr)

    def destroy(self) -> None:
        try:
            self._container.kill()
        except (DockerException, NotFound):
            pass
        try:
            self._container.remove(force=True)
        except (DockerException, NotFound):
            pass
        import shutil
        shutil.rmtree(self._host_dir, ignore_errors=True)
