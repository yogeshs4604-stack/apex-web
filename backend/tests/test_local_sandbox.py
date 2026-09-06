import pytest

from app.sandbox.local_dev import LocalDevSandbox


def _make_sandbox():
    return LocalDevSandbox(i_understand_this_is_insecure=True)


def test_refuses_construction_without_explicit_opt_in():
    with pytest.raises(RuntimeError):
        LocalDevSandbox()  # missing the required opt-in flag


def test_write_read_roundtrip():
    sb = _make_sandbox()
    try:
        sb.write_file("hello.txt", "world")
        assert sb.read_file("hello.txt") == "world"
    finally:
        sb.destroy()


def test_path_escape_blocked():
    sb = _make_sandbox()
    try:
        with pytest.raises(ValueError):
            sb.read_file("../../../etc/passwd")
    finally:
        sb.destroy()


def test_edit_file_ambiguous_raises():
    sb = _make_sandbox()
    try:
        sb.write_file("a.py", "x = 1\nx = 1\n")
        with pytest.raises(ValueError):
            sb.edit_file("a.py", "x = 1", "x = 2")
    finally:
        sb.destroy()


def test_run_command_real_subprocess():
    sb = _make_sandbox()
    try:
        result = sb.run_command("echo sandboxed-output")
        assert result.exit_code == 0
        assert "sandboxed-output" in result.stdout
    finally:
        sb.destroy()


def test_destroy_removes_workspace():
    sb = _make_sandbox()
    sb.write_file("temp.txt", "data")
    root = sb._root
    assert root.exists()
    sb.destroy()
    assert not root.exists()
