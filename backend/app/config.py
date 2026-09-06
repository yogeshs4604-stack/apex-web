"""Settings for the hosted APEX web service.

Everything security- or cost-relevant is explicit and has a safe default:
if you deploy this without configuring JWT_SECRET, it refuses to start
rather than silently using a guessable default in production.
"""
from __future__ import annotations

import os
import secrets


class Settings:
    # --- Identity / auth ---
    JWT_SECRET: str = os.environ.get("APEX_JWT_SECRET", "")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = int(os.environ.get("APEX_JWT_EXPIRE_MINUTES", "60"))

    # --- Database ---
    DATABASE_URL: str = os.environ.get("APEX_DATABASE_URL", "sqlite:///./apex_web.db")

    # --- The ONE shared Anthropic key that pays for everyone's usage, since this is free-to-use. ---
    ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
    MODEL: str = os.environ.get("APEX_MODEL", "claude-sonnet-4-6")

    # --- Hard cost controls. "Free" does not mean "unlimited". ---
    DAILY_MESSAGE_QUOTA: int = int(os.environ.get("APEX_DAILY_MESSAGE_QUOTA", "20"))
    MAX_TOOL_ITERATIONS_PER_MESSAGE: int = int(os.environ.get("APEX_MAX_ITERATIONS", "15"))

    # --- Sandbox isolation mode ---
    # "docker": real per-user Docker containers (production; requires a Docker daemon).
    # "local_dev_INSECURE": runs directly on the host in a per-user temp dir. NEVER use this
    #   for a real public deployment -- it has no isolation between users. It exists only so
    #   this codebase is runnable/testable on a machine without Docker.
    SANDBOX_MODE: str = os.environ.get("APEX_SANDBOX_MODE", "local_dev_INSECURE")
    DOCKER_IMAGE: str = os.environ.get("APEX_DOCKER_IMAGE", "python:3.12-slim")
    CONTAINER_MEMORY_LIMIT: str = os.environ.get("APEX_CONTAINER_MEM", "512m")
    CONTAINER_PIDS_LIMIT: int = int(os.environ.get("APEX_CONTAINER_PIDS", "128"))
    CONTAINER_CPU_QUOTA: int = int(os.environ.get("APEX_CONTAINER_CPU_QUOTA", "50000"))  # 50% of one core
    CONTAINER_IDLE_TIMEOUT_SECONDS: int = int(os.environ.get("APEX_CONTAINER_IDLE_TIMEOUT", "600"))
    # "none" disables all container networking (safest default for a free public tier -- blocks
    # abuse like using sandboxes as attack proxies, at the cost of `pip install`/`git clone` not
    # working inside the sandbox). Set to "bridge" to allow outbound network, accepting that risk.
    CONTAINER_NETWORK_MODE: str = os.environ.get("APEX_CONTAINER_NETWORK", "none")

    def validate_for_production(self) -> list[str]:
        """Real checks; call this at real-deployment startup, not in tests."""
        problems = []
        if not self.JWT_SECRET:
            problems.append("APEX_JWT_SECRET is not set.")
        if not self.ANTHROPIC_API_KEY:
            problems.append("ANTHROPIC_API_KEY is not set -- the service cannot call the model.")
        if self.SANDBOX_MODE != "docker":
            problems.append(
                "SANDBOX_MODE is not 'docker'. Do not expose this to the public internet "
                "without real per-user isolation."
            )
        return problems


settings = Settings()


def generate_dev_jwt_secret() -> str:
    """Convenience for local dev only -- real deployments must set APEX_JWT_SECRET explicitly."""
    return secrets.token_urlsafe(32)
