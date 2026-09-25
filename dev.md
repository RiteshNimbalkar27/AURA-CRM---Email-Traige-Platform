# AURA — Development Guide (venv mode)

This guide explains how to run AURA locally using a Python venv for the backend
and Node.js for the frontend. Only PostgreSQL and Redis run in Docker.
Everything stays in `d:\Code\EDAI Email\` — nothing installs on C: drive.

## Prerequisites

- Python 3.12+
- Node.js 20+
- Docker Desktop (for DB + Redis)
- Git

## First-Time Setup

### Step 1 — Start Database and Redis

```powershell
docker compose -f docker-compose.dev.yml up -d
```

This creates:
- PostgreSQL at `localhost:5432` (data in `.\data\postgres\`)
- Redis at `localhost:6379` (data in `.\data\redis\`)

### Step 2 — Create Python venv (backend)

```powershell
cd backend
python -m venv .venv
```

### Step 3 — Activate venv

**Windows (PowerShell):**
```powershell
.venv\Scripts\Activate.ps1
```

**Windows (CMD):**
```cmd
.venv\Scripts\activate.bat
```

**Linux/macOS:**
```bash
source .venv/bin/activate
```

### Step 4 — Install Python dependencies

```powershell
pip install -r requirements.txt
```

> **Note:** `torch` is CPU-only and will install without CUDA. This is intentional.
> The embedding model (`all-MiniLM-L6-v2`) runs efficiently on CPU.

### Step 5 — Configure environment

Copy the example env and fill in secrets:
```powershell
copy ..\env.example ..\.env
```

Open `.env` and set:
- `OPENROUTER_API_KEY` — get from https://openrouter.ai/keys (free tier available)
- `SECRET_KEY` — generate with: `python -c "import secrets; print(secrets.token_hex(32))"`
- Leave all other values as default for local dev

### Step 6 — Run database migrations

```powershell
alembic upgrade head
```

### Step 7 — Seed the database

```powershell
# Seed users + accounts + contacts
python scripts/seed.py

# Chunk, embed, and index all 6 KB policy documents
python scripts/seed_kb.py
```

### Step 8 — Start the backend server

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

API available at: http://localhost:8000  
API docs: http://localhost:8000/docs

> **Windows Note (Resolved — asyncpg driver):** AURA uses `asyncpg` as the async
> PostgreSQL driver (not `psycopg3`). `asyncpg` works with Windows' default
> ProactorEventLoop without any special flags.
>
> The `DATABASE_URL` must use `postgresql+asyncpg://...` (already set in `.env`).
> The old `--loop asyncio` workaround is **no longer needed**.

### Step 9 — Start the frontend (new terminal)

```powershell
cd frontend
npm install
npm run dev
```

Frontend at: http://localhost:3000

### Step 10 — Start the async worker (new terminal)

```powershell
cd backend
.venv\Scripts\Activate.ps1
arq app.worker.main.WorkerSettings
```

The worker picks up background classification jobs enqueued by `POST /api/ingest`.

## Seeded Credentials

| Role | Email | Password |
|---|---|---|
| Operator | operator@nexus.example | operator_password_2024 |
| Supervisor | supervisor@nexus.example | supervisor_password_2024 |

## Running Tests

```powershell
cd backend
pytest tests/ -v
pytest tests/test_scenarios.py -v  # acceptance scenarios only
```

## Full Docker Stack (demo mode)

To run the complete stack via Docker (no venv needed):

```powershell
docker compose up --build
```

## Stopping Services

```powershell
# Stop dev DB + Redis
docker compose -f docker-compose.dev.yml down

# Stop full stack
docker compose down

# Remove data volumes (CAREFUL: deletes all DB data)
docker compose down -v
```

## Known Windows Quirks (and their fixes)

| Issue | Root Cause | Fix Applied |
|---|---|---|
| `psycopg.InterfaceError: ProactorEventLoop` | psycopg3 async incompatible with Windows default loop | **Switched to `asyncpg` driver** (`postgresql+asyncpg://...`) |
| `alembic upgrade` event loop error | `asyncio.run()` on Windows defaults to ProactorEventLoop | Added `WindowsSelectorEventLoopPolicy` in `alembic/env.py` |
| `seed.py` / `seed_kb.py` event loop error | Same as above | Added `WindowsSelectorEventLoopPolicy` in all script `__main__` blocks |
| `passlib` bcrypt warning on startup | passlib 1.7.x doesn't recognize bcrypt 4.x `__about__` | Non-breaking warning. Auth works correctly. Upgrade passlib to silence it. |
| `arq` worker event loop on Windows | ARQ uses its own loop management | `WindowsSelectorEventLoopPolicy` set at top of `app/worker/main.py` |
