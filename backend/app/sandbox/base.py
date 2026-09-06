"""The Sandbox interface: everywhere the agent touches the outside world.

Every hosted user session gets one Sandbox instance. This is the entire
trust boundary of the product -- get this wrong and one free-tier user can
attack another, or attack the host. There are two implementations:

- DockerSandbox: real per-user container isolation. This is the ONLY
  implementation that should ever be used for a real public deployment.
- LocalDevSandbox: runs directly on the host filesystem, no isolation at
  all between users. It exists solely so this codebase is runnable and
  testable on a machine without Docker (like the sandbox this was built
  in). It refuses to construct unless an explicit "I understand this is
  insecure" flag is passed, so it can't be reached for real by accident.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SandboxCommandResult:
    exit_code: int | None
    stdout: str
    stderr: str
    denied_reason: str | None = None


class Sandbox(ABC):
    @abstractmethod
    def read_file(self, path: str) -> str: ...

    @abstractmethod
    def write_file(self, path: str, content: str) -> int:
        """Returns bytes written."""

    @abstractmethod
    def edit_file(self, path: str, old_str: str, new_str: str) -> int:
        """Exact unique-match replacement. Returns bytes written. Raises on 0 or >1 matches."""

    @abstractmethod
    def list_directory(self, path: str = ".") -> str: ...

    @abstractmethod
    def search_code(self, pattern: str, regex: bool = False) -> str: ...

    @abstractmethod
    def run_command(self, command: str, timeout_seconds: int = 60) -> SandboxCommandResult: ...

    @abstractmethod
    def destroy(self) -> None:
        """Tear down the sandbox and free its resources."""
