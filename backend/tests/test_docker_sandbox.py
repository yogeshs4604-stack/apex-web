"""These tests exercise DockerSandbox against a REAL Docker daemon.

They are skipped, with an explicit reason, when no daemon is reachable --
this environment has none. That is stated plainly: the Docker sandbox path
has been verified by code review and by the local-dev sandbox tests (same
logic, different execution backend for file ops; run_command differs and
is genuinely untested against a live daemon here). Run this file for real
on a machine with Docker before any production deployment.
"""
import pytest

docker = pytest.importorskip("docker")


def _docker_available() -> bool:
    try:
        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _docker_available(),
    reason="No reachable Docker daemon in this environment -- cannot verify real container isolation here.",
)


def test_docker_sandbox_lifecycle():
    from app.sandbox.docker_sandbox import DockerSandbox

    sb = DockerSandbox()
    try:
        sb.write_file("hello.py", "print('hi from container')")
        result = sb.run_command("python3 hello.py")
        assert result.exit_code == 0
        assert "hi from container" in result.stdout
    finally:
        sb.destroy()


def test_docker_sandbox_has_no_network_by_default():
    from app.sandbox.docker_sandbox import DockerSandbox

    sb = DockerSandbox()
    try:
        result = sb.run_command("wget -T 3 -q -O - http://example.com || echo NO_NETWORK")
        assert "NO_NETWORK" in result.stdout or result.exit_code != 0
    finally:
        sb.destroy()
