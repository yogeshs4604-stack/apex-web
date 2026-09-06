from __future__ import annotations

from ..config import settings
from .base import Sandbox


def create_sandbox(session_id: str) -> Sandbox:
    if settings.SANDBOX_MODE == "docker":
        from .docker_sandbox import DockerSandbox
        return DockerSandbox(session_id=session_id)

    if settings.SANDBOX_MODE == "local_dev_INSECURE":
        from .local_dev import LocalDevSandbox
        return LocalDevSandbox(session_id=session_id, i_understand_this_is_insecure=True)

    raise RuntimeError(
        f"Unknown APEX_SANDBOX_MODE={settings.SANDBOX_MODE!r}. Must be 'docker' or "
        "'local_dev_INSECURE' (dev/test only, no isolation)."
    )
