from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from . import auth, rate_limit
from .config import settings
from .db import get_db, init_db
from .hosted_agent import HostedAgent
from .model_client import MissingModelKeyError
from .sandbox.base import Sandbox
from .sandbox.factory import create_sandbox


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="APEX Web (hosted, free-tier)", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ⚠️ dev-only default. Before a real deployment, restrict this to your
                          # actual frontend origin(s), e.g. ["https://your-app.vercel.app"].
    allow_methods=["*"],
    allow_headers=["*"],
)


class SignupRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@app.post("/auth/signup", response_model=TokenResponse)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    try:
        user = auth.signup(db, payload.email, payload.password)
    except auth.AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TokenResponse(access_token=auth.create_access_token(user.id))


@app.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    try:
        user = auth.login(db, payload.email, payload.password)
    except auth.AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return TokenResponse(access_token=auth.create_access_token(user.id))


@app.get("/me/quota")
def my_quota(token: str, db: Session = Depends(get_db)):
    try:
        user_id = auth.decode_access_token(token)
    except auth.AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return {"daily_limit": settings.DAILY_MESSAGE_QUOTA, "remaining_today": rate_limit.remaining_quota(db, user_id)}


@app.get("/health")
def health():
    return {"status": "ok", "sandbox_mode": settings.SANDBOX_MODE}


import pathlib
_frontend_dir = pathlib.Path(__file__).resolve().parent.parent.parent / "frontend"
if _frontend_dir.exists():
    @app.get("/")
    def serve_frontend():
        return FileResponse(_frontend_dir / "index.html")


def _send_event(ws_send, event) -> None:
    ws_send(json.dumps({"kind": event.kind, "payload": event.payload}))


@app.websocket("/ws/chat")
async def chat_ws(websocket: WebSocket, token: str):
    db_gen = get_db()
    db: Session = next(db_gen)
    try:
        user_id = auth.decode_access_token(token)
    except auth.AuthError as exc:
        await websocket.close(code=4401, reason=str(exc))
        return

    await websocket.accept()

    sandbox: Sandbox | None = None
    agent: HostedAgent | None = None

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
                user_message = data["message"]
            except (json.JSONDecodeError, KeyError):
                await websocket.send_text(json.dumps({"kind": "error", "payload": {"message": "Malformed request."}}))
                continue

            try:
                remaining = rate_limit.check_and_increment_quota(db, user_id)
            except rate_limit.QuotaExceededError as exc:
                await websocket.send_text(json.dumps({"kind": "quota_exceeded", "payload": {"message": str(exc)}}))
                continue

            if agent is None:
                try:
                    sandbox = create_sandbox(session_id=str(user_id))
                    agent = HostedAgent(sandbox)
                except MissingModelKeyError as exc:
                    await websocket.send_text(json.dumps({"kind": "error", "payload": {"message": str(exc)}}))
                    continue
                except Exception as exc:  # noqa: BLE001 - sandbox startup failures must reach the client honestly
                    await websocket.send_text(json.dumps({"kind": "error", "payload": {"message": str(exc)}}))
                    continue

            await websocket.send_text(json.dumps({
                "kind": "quota_status", "payload": {"remaining_today": settings.DAILY_MESSAGE_QUOTA - remaining}
            }))

            try:
                events = agent.run_turn(user_message)
            except Exception as exc:  # noqa: BLE001
                await websocket.send_text(json.dumps({"kind": "error", "payload": {"message": str(exc)}}))
                continue

            for ev in events:
                await websocket.send_text(json.dumps({"kind": ev.kind, "payload": ev.payload}))

    except WebSocketDisconnect:
        pass
    finally:
        if sandbox is not None:
            sandbox.destroy()
        db.close()
