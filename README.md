# APEX Web — hosted, multi-user, free-to-use

A hosted version of APEX: signup/login, a browser chat UI, and per-user sandboxed code
execution, backed by one shared Anthropic API key. This is a genuinely different, larger
project than the `apex-agent` CLI — see the honesty notes below before you deploy this
publicly.

## What's real and tested here

- Real signup/login (bcrypt-hashed passwords, JWT tokens) — `backend/app/auth.py`
- Real, DB-enforced daily message quota per user — `backend/app/rate_limit.py`. This is
  what makes "free" not mean "unlimited": without it, a public free tier has no cost ceiling.
- A `Sandbox` interface with two implementations — `backend/app/sandbox/`:
  - **`DockerSandbox`** (`docker_sandbox.py`): real per-user container isolation via the
    Docker SDK — network disabled by default, memory/CPU/PID limits, non-root user,
    read-only root filesystem. **This was written against the real Docker Engine API but
    has not been run against a live Docker daemon** — the environment this was built in
    had none. `tests/test_docker_sandbox.py` exercises it for real and auto-skips (with an
    explicit reason, not a silent pass) when no daemon is reachable. **Run that test file
    for real on a machine with Docker before trusting this in production.**
  - **`LocalDevSandbox`** (`local_dev.py`): zero isolation between users, runs directly on
    the host. Exists only so the whole stack is testable without Docker. Its constructor
    refuses to run without an explicit `i_understand_this_is_insecure=True` flag, specifically
    so it can't end up wired into a real deployment by an innocent default value.
- A real chat frontend (`frontend/index.html`) — plain HTML/JS, no build step, served by
  the same backend. Signup/login, WebSocket streaming of the agent's tool calls and output,
  live quota display.
- 22 tests, 20 passing / 2 honestly skipped (Docker-only). Includes a full live-server run
  during development: real signup → real JWT → real WebSocket → real quota decrement → an
  honest error surfaced to the browser when the model call failed, rather than a fake response.

## What is NOT done, stated plainly

- **No live Docker verification.** This is the single biggest gap before a real deployment.
  Isolation is the entire trust model of a "free, anyone can run code" product — verify it
  yourself, on real infrastructure, before letting strangers use this.
- No billing (you said this is free-to-use, so there's none — but that means the quota is
  your only cost control; tune `APEX_DAILY_MESSAGE_QUOTA` accordingly).
- No email verification, password reset, or abuse/fraud detection (e.g. one person signing
  up 500 times to multiply their quota). A public free tier without these will get abused.
- No persistent per-user workspace across sessions — each WebSocket connection gets a fresh
  sandbox that's destroyed on disconnect. Add a persistent volume per user if you want
  projects to survive between visits.
- No horizontal scaling story. One process holds in-memory WebSocket/agent state; running
  multiple backend replicas would need session affinity or moving that state to Redis/DB.
- The frontend stores the JWT in `localStorage`, fine for a demo, but a real production
  frontend should use an httpOnly cookie to reduce XSS token-theft risk.

## Local setup

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in APEX_JWT_SECRET and ANTHROPIC_API_KEY
export $(grep -v '^#' .env | xargs)   # or use a proper env loader / your platform's secrets
uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000` — the backend serves the frontend directly.

⚠️ Local setup defaults to `APEX_SANDBOX_MODE=local_dev_INSECURE`. That's fine alone on your
own machine. **Never set that in a deployment anyone else can reach.**

## Running the tests

```bash
pip install -r requirements.txt   # includes pytest
pytest -v
```

## Real deployment options (why Vercel-alone doesn't fit)

The execution model here — a long-lived WebSocket holding an agent loop, backed by a Docker
daemon spinning up per-user containers — doesn't fit serverless functions: Vercel functions
are stateless, time out long before a multi-step agent turn finishes, and have no Docker
daemon to call. You need a host that stays running and can talk to Docker:

| Component | Good real options | Why |
|---|---|---|
| Backend + sandboxes | Fly.io Machines, Render (Docker-enabled), a plain VPS (DigitalOcean/Hetzner/EC2) with Docker installed | Needs a persistent process and access to a real Docker daemon |
| Database | **Supabase Postgres works fine here** — it's just a connection string, and this backend already uses plain SQLAlchemy | `APEX_DATABASE_URL=postgresql://...` pointed at Supabase |
| Frontend | Can stay served by the backend (simplest), or split out to Vercel/Netlify as a static site that talks to your backend's API/WebSocket URL | Vercel is genuinely fine for *static* frontend hosting; it's the execution layer that doesn't fit there |

A reasonable real path: deploy `backend/` (with `APEX_SANDBOX_MODE=docker`) to Fly.io or a
VPS with Docker installed, point `APEX_DATABASE_URL` at a Supabase Postgres instance, and
either keep serving `frontend/index.html` from the backend or deploy it separately to Vercel
pointed at your backend's URL.

## Before you tell anyone this URL

1. Set `APEX_SANDBOX_MODE=docker` and actually run `pytest tests/test_docker_sandbox.py` on
   that machine to confirm isolation really works.
2. Set a real `APEX_JWT_SECRET` (never the example value).
3. Set `APEX_DAILY_MESSAGE_QUOTA` to something you're financially comfortable multiplying by
   however many signups you expect, worst case.
4. Decide whether `APEX_CONTAINER_NETWORK=none` (safer, no package installs in-sandbox) or
   `bridge` (more useful, more abuse-prone) fits what you're building.
5. Restrict CORS in `backend/app/main.py` (`allow_origins=["*"]` is fine for local dev only)
   to your real frontend origin.
