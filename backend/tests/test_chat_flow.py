"""End-to-end test of the whole hosted flow.

Real: HTTP signup/login (FastAPI TestClient, real routing/DB/JWT), the
WebSocket connection and protocol, the LocalDevSandbox executing real file
writes and a real subprocess, and quota enforcement blocking the request
that exceeds the daily limit.

Scripted: the model call itself, via dependency injection on HostedAgent,
for the same reason as the CLI's integration test -- no live model
available in this environment. The tool loop it drives is entirely real.
"""
import json

import pytest
from fastapi.testclient import TestClient

from app.hosted_agent import HostedAgent, TurnEvent
from app.main import app
from app.model_client import ModelResponse


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


class ScriptedModelClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def send(self, system, messages, tools, max_tokens=4096):
        response = self._responses[self.calls]
        self.calls += 1
        return response


def _text_block(text):
    return {"type": "text", "text": text}


def _tool_use_block(id_, name, input_):
    return {"type": "tool_use", "id": id_, "name": name, "input": input_}


def test_signup_login_and_quota_endpoint(client):
    r = client.post("/auth/signup", json={"email": "e2e@example.com", "password": "correcthorsebattery"})
    assert r.status_code == 200
    token = r.json()["access_token"]

    r2 = client.post("/auth/login", json={"email": "e2e@example.com", "password": "correcthorsebattery"})
    assert r2.status_code == 200

    r3 = client.post("/auth/login", json={"email": "e2e@example.com", "password": "wrongpassword"})
    assert r3.status_code == 401

    r4 = client.get("/me/quota", params={"token": token})
    assert r4.status_code == 200
    assert r4.json()["remaining_today"] == r4.json()["daily_limit"]


def test_websocket_chat_runs_real_tools_via_scripted_model(client, monkeypatch):
    signup = client.post("/auth/signup", json={"email": "wschat@example.com", "password": "correcthorsebattery"})
    token = signup.json()["access_token"]

    # Patch HostedAgent construction so the real ws endpoint uses our scripted model client,
    # while everything else (sandbox creation, tool execution, protocol) stays real.
    original_init = HostedAgent.__init__

    def patched_init(self, sandbox, model_client=None):
        scripted = ScriptedModelClient([
            ModelResponse(
                stop_reason="tool_use",
                content=[
                    _text_block("I'll write and run a small script."),
                    _tool_use_block("c1", "write_file", {"path": "greet.py", "content": "print('e2e works')\n"}),
                ],
                usage_input_tokens=5, usage_output_tokens=5,
            ),
            ModelResponse(
                stop_reason="tool_use",
                content=[_tool_use_block("c2", "run_command", {"command": "python3 greet.py"})],
                usage_input_tokens=5, usage_output_tokens=5,
            ),
            ModelResponse(
                stop_reason="end_turn",
                content=[_text_block("Done: greet.py ran and printed the expected output.")],
                usage_input_tokens=5, usage_output_tokens=5,
            ),
        ])
        original_init(self, sandbox, model_client=scripted)

    monkeypatch.setattr(HostedAgent, "__init__", patched_init)

    with client.websocket_connect(f"/ws/chat?token={token}") as ws:
        ws.send_text(json.dumps({"message": "write and run a greeting script"}))

        received = []
        # quota_status, then text/tool_call/tool_result/tool_call/tool_result/text(final) = 7 total
        for _ in range(7):
            received.append(json.loads(ws.receive_text()))

    kinds = [r["kind"] for r in received]
    assert "quota_status" in kinds

    tool_results = [r for r in received if r["kind"] == "tool_result"]
    assert any("e2e works" in r["payload"]["output"] for r in tool_results)
    assert any("exit_code=0" in r["payload"]["output"] for r in tool_results)

    final_texts = [r for r in received if r["kind"] == "text"]
    assert any("Done" in r["payload"]["text"] for r in final_texts)


def test_websocket_enforces_quota(client, monkeypatch):
    signup = client.post("/auth/signup", json={"email": "wsquota@example.com", "password": "correcthorsebattery"})
    token = signup.json()["access_token"]

    original_init = HostedAgent.__init__

    def patched_init(self, sandbox, model_client=None):
        # Every turn just answers immediately with no tool calls -- we only care about quota here.
        scripted = ScriptedModelClient([
            ModelResponse(stop_reason="end_turn", content=[_text_block("ok")], usage_input_tokens=1, usage_output_tokens=1)
            for _ in range(10)
        ])
        original_init(self, sandbox, model_client=scripted)

    monkeypatch.setattr(HostedAgent, "__init__", patched_init)

    from app.config import settings
    with client.websocket_connect(f"/ws/chat?token={token}") as ws:
        for _ in range(settings.DAILY_MESSAGE_QUOTA):
            ws.send_text(json.dumps({"message": "hi"}))
            # quota_status then text
            events = [json.loads(ws.receive_text()) for _ in range(2)]
            assert "quota_exceeded" not in [e["kind"] for e in events]

        # One more, over the limit, should be rejected before any model call
        ws.send_text(json.dumps({"message": "one too many"}))
        final = json.loads(ws.receive_text())
        assert final["kind"] == "quota_exceeded"
