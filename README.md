# NEXA – AI Personal Assistant Backend

> **NEXA** is a production-grade, modular-monolith AI personal assistant backend.  
> It orchestrates LLM-driven agents, manages integrations with external services (Google Calendar, Gmail, Telegram, n8n), and exposes a secure REST API for client applications.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture Overview](#2-architecture-overview)
3. [Technology Stack](#3-technology-stack)
4. [Project Structure](#4-project-structure)
5. [Prerequisites](#5-prerequisites)
6. [Quick Start (Windows PowerShell)](#6-quick-start-windows-powershell)
7. [Environment Configuration](#7-environment-configuration)
8. [Installation Steps](#8-installation-steps)
9. [Infrastructure with Docker Compose](#9-infrastructure-with-docker-compose)
10. [Database Migrations (Alembic)](#10-database-migrations-alembic)
11. [Running the API Server](#11-running-the-api-server)
12. [Running Celery Workers](#12-running-celery-workers)
13. [API Documentation](#13-api-documentation)
14. [Testing](#14-testing)
15. [Linting & Formatting](#15-linting--formatting)
16. [Integration Setup](#16-integration-setup)
17. [Security Considerations](#17-security-considerations)
18. [Integration Status](#18-integration-status)
19. [Recommended Next Steps](#19-recommended-next-steps)

---

## 1. Project Overview

NEXA is built around a central AI orchestration pipeline that:

- Accepts natural-language instructions from users (via REST API or Telegram)
- Plans multi-step actions using an LLM-based Planner
- Executes approved actions through a registered Tool Registry
- Tracks conversation state and long-running tasks persistently
- Sends proactive reminders and notifications via background workers
- Encrypts all third-party OAuth tokens at rest using Fernet symmetric encryption

**Core capabilities:**

| Capability | Description |
|---|---|
| AI Agent Orchestration | Multi-step planning, tool selection, and execution via LLM |
| Approval Workflow | High-risk tool calls require explicit user approval before execution |
| Google Calendar | Read/write events, free/busy queries |
| Gmail | Send messages, search inbox, read threads |
| Telegram Bot | Bidirectional messaging, inline approval buttons |
| n8n Webhooks | Trigger arbitrary automation workflows |
| Reminders | Scheduled Celery tasks for time-based notifications |
| Secure Auth | JWT access + refresh token rotation, Argon2 password hashing |

---

## 2. Architecture Overview

NEXA uses a **modular monolith** architecture — all modules live in one deployable unit but are strictly separated by domain boundaries. This avoids the operational complexity of microservices while preserving a clean migration path if scaling demands require service extraction.

### AI Orchestration Pipeline

```
User Request (HTTP / Telegram)
        │
        ▼
  ConversationService
        │  persists turn, loads context
        ▼
   NexaAgent (app.ai.agent)
        │  assembles system prompt, history
        ▼
   Orchestrator (app.ai.orchestrator)
        │  calls LLM, parses tool calls
        ▼
   Planner (app.ai.planner)
        │  validates plan feasibility
        ▼
  ApprovalService (app.services.approval)
        │  high-risk → pending_approval state
        │  low-risk  → direct execution
        ▼
  ToolRegistry (app.tools.registry)
        │  resolves tool name → ToolExecutor
        ▼
  ToolExecutor (app.tools.executor)
        │  runs tool with timeout + retries
        ▼
  Result → LLM for final answer → User
```

### Approval State Machine

```
pending_approval ──► approved ──► executing ──► completed
        │                                           │
        └──► rejected                       ──► failed
```

### Background Workers

```
Celery Beat (scheduler)
    │
    ├── reminders queue  ──► ReminderTask ──► Telegram / Email
    ├── notifications queue ──► NotificationTask
    └── default queue    ──► General async tasks
```

---

## 3. Technology Stack

| Component | Technology | Version |
|---|---|---|
| Language | Python | 3.12+ |
| Web Framework | FastAPI | 0.115+ |
| ASGI Server | Uvicorn | 0.30+ |
| ORM | SQLAlchemy (async) | 2.0+ |
| Migrations | Alembic | 1.13+ |
| Database | PostgreSQL | 16 |
| Cache / Broker | Redis | 7 |
| Task Queue | Celery | 5.4+ |
| Data Validation | Pydantic | 2.x |
| Password Hashing | Argon2-cffi | 23+ |
| Token Encryption | cryptography (Fernet) | 42+ |
| Structured Logging | structlog | 24+ |
| Auth | python-jose (JWT) | 3.3+ |
| Google APIs | google-api-python-client | 2.x |
| Telegram | python-telegram-bot | 21+ |
| HTTP Client | httpx | 0.27+ |
| Testing | pytest + pytest-asyncio | 8+ |
| Linting | Ruff | 0.4+ |
| Containerisation | Docker + Compose | 24+ / 2.x |

---

## 4. Project Structure

```
nexa/
├── app/
│   ├── __init__.py
│   ├── main.py                      # FastAPI application factory
│   ├── config.py                    # Settings (pydantic-settings)
│   ├── dependencies.py              # FastAPI dependency injectors
│   │
│   ├── api/                         # HTTP routers
│   │   ├── __init__.py
│   │   ├── v1/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py              # /auth/* endpoints
│   │   │   ├── conversations.py     # /conversations/* endpoints
│   │   │   ├── tasks.py             # /tasks/* endpoints
│   │   │   ├── approvals.py         # /approvals/* endpoints
│   │   │   ├── integrations.py      # /integrations/* endpoints
│   │   │   └── health.py            # /health endpoint
│   │
│   ├── ai/                          # AI orchestration layer
│   │   ├── __init__.py
│   │   ├── agent.py                 # NexaAgent — top-level AI entry point
│   │   ├── orchestrator.py          # LLM call loop, tool-call parsing
│   │   ├── planner.py               # Plan validation and feasibility checks
│   │   ├── prompts.py               # System prompt templates
│   │   └── schemas.py               # LLM request/response Pydantic models
│   │
│   ├── tools/                       # Tool registry and executors
│   │   ├── __init__.py
│   │   ├── registry.py              # ToolRegistry — registers & resolves tools
│   │   ├── executor.py              # ToolExecutor — runs tools with timeout/retry
│   │   ├── base.py                  # BaseTool ABC
│   │   ├── calendar_tool.py         # Google Calendar tool
│   │   ├── gmail_tool.py            # Gmail tool
│   │   ├── telegram_tool.py         # Telegram send tool
│   │   ├── n8n_tool.py              # n8n webhook trigger tool
│   │   └── reminder_tool.py         # Schedule reminder tool
│   │
│   ├── models/                      # SQLAlchemy ORM models
│   │   ├── __init__.py
│   │   ├── base.py                  # DeclarativeBase, TimestampMixin
│   │   ├── user.py                  # User model
│   │   ├── conversation.py          # Conversation + ConversationTurn models
│   │   ├── task.py                  # Task model (agent-initiated tasks)
│   │   ├── approval.py              # Approval model
│   │   ├── reminder.py              # Reminder model
│   │   └── integration.py           # OAuthCredential model
│   │
│   ├── schemas/                     # Pydantic v2 request/response schemas
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── conversation.py
│   │   ├── task.py
│   │   ├── approval.py
│   │   ├── reminder.py
│   │   └── integration.py
│   │
│   ├── services/                    # Business logic layer
│   │   ├── __init__.py
│   │   ├── auth_service.py          # Registration, login, token refresh
│   │   ├── conversation_service.py  # Conversation CRUD, turn management
│   │   ├── task_service.py          # Task lifecycle management
│   │   ├── approval_service.py      # Approval workflow state machine
│   │   ├── reminder_service.py      # Reminder scheduling
│   │   ├── integration_service.py   # OAuth credential management
│   │   ├── google_service.py        # Google API client wrapper
│   │   ├── telegram_service.py      # Telegram Bot API wrapper
│   │   └── n8n_service.py           # n8n webhook client
│   │
│   ├── workers/                     # Celery tasks
│   │   ├── __init__.py
│   │   ├── celery_app.py            # Celery application instance
│   │   ├── reminder_tasks.py        # Reminder delivery tasks
│   │   └── notification_tasks.py    # General notification tasks
│   │
│   ├── integrations/                # Third-party integration adapters
│   │   ├── __init__.py
│   │   ├── google/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py              # OAuth2 flow for Google
│   │   │   ├── calendar.py          # Google Calendar API adapter
│   │   │   └── gmail.py             # Gmail API adapter
│   │   ├── telegram/
│   │   │   ├── __init__.py
│   │   │   ├── bot.py               # Telegram bot setup and handlers
│   │   │   └── webhooks.py          # Telegram webhook processing
│   │   └── n8n/
│   │       ├── __init__.py
│   │       └── client.py            # n8n REST/webhook client
│   │
│   └── core/                        # Shared infrastructure
│       ├── __init__.py
│       ├── database.py              # Async engine, session factory
│       ├── security.py              # JWT, Argon2, Fernet helpers
│       ├── exceptions.py            # Domain exception hierarchy
│       ├── logging.py               # structlog configuration
│       └── middleware.py            # Request ID, error handling middleware
│
├── alembic/                         # Database migrations
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── ...
│
├── tests/                           # Test suite
│   ├── conftest.py                  # Shared fixtures, test DB setup
│   ├── unit/
│   │   ├── test_auth_service.py
│   │   ├── test_approval_service.py
│   │   ├── test_tool_registry.py
│   │   └── test_security.py
│   └── integration/
│       ├── test_auth_endpoints.py
│       ├── test_conversation_endpoints.py
│       └── test_approval_endpoints.py
│
├── docs/
│   └── ARCHITECTURE.md              # Architecture decision records
│
├── .env.example                     # Environment variable template
├── .gitignore
├── alembic.ini                      # Alembic configuration
├── docker-compose.yml               # Local development infrastructure
├── Dockerfile                       # Multi-stage production image
├── pyproject.toml                   # Project metadata and dependencies
└── README.md
```

---

## 5. Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.12+ | 3.14 path: `C:\Users\H\AppData\Local\Python\bin\python3.14.exe` |
| Docker Desktop | 24+ | With Docker Compose v2 |
| Git | Any recent | For cloning |
| PowerShell | 5.1+ or Core 7+ | Windows development |

Optional (for running integrations locally without Docker):

| Requirement | Notes |
|---|---|
| PostgreSQL 16 | Local instance or Docker |
| Redis 7 | Local instance or Docker |

---

## 6. Quick Start (Windows PowerShell)

```powershell
# 1. Clone the repository
git clone https://github.com/your-org/nexa.git
cd nexa

# 2. Create a virtual environment using the project Python
C:\Users\H\AppData\Local\Python\bin\python3.14.exe -m venv .venv

# 3. Activate the virtual environment
.venv\Scripts\Activate.ps1

# 4. Install the project with dev dependencies
pip install -e ".[dev]"

# 5. Configure environment
Copy-Item .env.example .env
# Edit .env and fill in required values (see Section 7)

# 6. Start infrastructure (PostgreSQL + Redis)
docker compose up -d postgres redis

# 7. Run database migrations
alembic upgrade head

# 8. Start the API server
uvicorn app.main:app --reload
```

API will be available at **http://localhost:8000**  
Interactive docs at **http://localhost:8000/docs**

---

## 7. Environment Configuration

Copy `.env.example` to `.env` and fill in values. The table below documents every variable, which feature requires it, and whether it is mandatory.

### Core Application

| Variable | Required | Default | Description |
|---|---|---|---|
| `SECRET_KEY` | ✅ Yes | — | 32-byte hex secret for JWT signing. Generate: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DEBUG` | No | `false` | Enable debug mode (never use in production) |
| `APP_PORT` | No | `8000` | Port the API server listens on |
| `ALLOWED_ORIGINS` | No | `*` | Comma-separated CORS origins |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | `15` | JWT access token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | No | `30` | JWT refresh token lifetime |

### Database (PostgreSQL)

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | ✅ Yes | — | Async DSN: `postgresql+asyncpg://user:pass@host:5432/dbname` |
| `POSTGRES_DB` | No | `nexa` | Database name (Docker Compose only) |
| `POSTGRES_USER` | No | `nexa_user` | DB user (Docker Compose only) |
| `POSTGRES_PASSWORD` | ✅ Yes | — | DB password |
| `POSTGRES_PORT` | No | `5432` | Host port mapped to PostgreSQL |

### Redis / Celery

| Variable | Required | Default | Description |
|---|---|---|---|
| `REDIS_URL` | ✅ Yes | — | `redis://localhost:6379/0` |
| `REDIS_PORT` | No | `6379` | Host port mapped to Redis |
| `REDIS_PASSWORD` | No | — | Redis AUTH password (leave blank for no auth) |
| `CELERY_BROKER_URL` | No | Same as `REDIS_URL` | Celery broker DSN |
| `CELERY_RESULT_BACKEND` | No | Same as `REDIS_URL` | Celery result backend DSN |

### AI / LLM

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | ✅ Yes | — | OpenAI API key for GPT-4o |
| `OPENAI_MODEL` | No | `gpt-4o` | Model identifier |
| `OPENAI_MAX_TOKENS` | No | `4096` | Max tokens per LLM call |
| `OPENAI_TEMPERATURE` | No | `0.1` | Temperature for deterministic planning |

### Google Integration

| Variable | Required for Google | Description |
|---|---|---|
| `GOOGLE_CLIENT_ID` | ✅ | OAuth2 client ID from Google Cloud Console |
| `GOOGLE_CLIENT_SECRET` | ✅ | OAuth2 client secret |
| `GOOGLE_REDIRECT_URI` | ✅ | Redirect URI (must match Cloud Console) |
| `FERNET_KEY` | ✅ | 32-byte Fernet key for token encryption. Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |

### Telegram Integration

| Variable | Required for Telegram | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | Bot token from @BotFather |
| `TELEGRAM_WEBHOOK_SECRET` | ✅ | Secret header value for webhook validation |
| `TELEGRAM_WEBHOOK_URL` | ✅ | Public HTTPS URL Telegram will POST to |

### n8n Integration

| Variable | Required for n8n | Description |
|---|---|---|
| `N8N_BASE_URL` | ✅ | Base URL of your n8n instance (e.g. `https://n8n.example.com`) |
| `N8N_API_KEY` | ✅ | n8n API key or webhook bearer token |

---

## 8. Installation Steps

### Step 1 — Clone

```powershell
git clone https://github.com/your-org/nexa.git
cd nexa
```

### Step 2 — Create Virtual Environment

```powershell
C:\Users\H\AppData\Local\Python\bin\python3.14.exe -m venv .venv
```

### Step 3 — Activate

```powershell
.venv\Scripts\Activate.ps1
```

> **Note:** If you receive an execution policy error, run:  
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

### Step 4 — Install Dependencies

```powershell
pip install -e ".[dev]"
```

This installs the project in editable mode with all development dependencies (pytest, ruff, etc.).

### Step 5 — Configure Environment

```powershell
Copy-Item .env.example .env
notepad .env   # or use your preferred editor
```

At minimum, set:
- `SECRET_KEY`
- `DATABASE_URL`
- `REDIS_URL`
- `OPENAI_API_KEY`
- `POSTGRES_PASSWORD`

---

## 9. Infrastructure with Docker Compose

Start only the backing services (recommended for local development):

```powershell
# Start PostgreSQL and Redis only
docker compose up -d postgres redis

# Check health
docker compose ps
```

Start the full stack (API + workers in containers):

```powershell
# Build and start everything
docker compose up -d --build

# View logs
docker compose logs -f api worker beat
```

Stop all services:

```powershell
docker compose down

# Also remove volumes (WARNING: destroys all data)
docker compose down -v
```

**Service URLs (default ports):**

| Service | URL |
|---|---|
| PostgreSQL | `localhost:5432` |
| Redis | `localhost:6379` |
| API | `http://localhost:8000` |

---

## 10. Database Migrations (Alembic)

### Apply all migrations to latest

```powershell
alembic upgrade head
```

### Roll back one migration

```powershell
alembic downgrade -1
```

### Create a new auto-generated migration

```powershell
alembic revision --autogenerate -m "add user preferences table"
```

> **Important:** Always review the generated migration file in `alembic/versions/` before applying. Alembic cannot detect all schema changes (e.g., constraint renames).

### View migration history

```powershell
alembic history --verbose
```

### Check current revision

```powershell
alembic current
```

---

## 11. Running the API Server

### Development (with auto-reload)

```powershell
uvicorn app.main:app --reload --port 8000
```

### Production-like (multiple workers)

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

> **Note:** `--reload` is incompatible with `--workers > 1`. Use one or the other.

---

## 12. Running Celery Workers

### Start the task worker

```powershell
celery -A app.workers.celery_app worker --loglevel=info --concurrency=4 -Q default,reminders,notifications
```

### Start the beat scheduler (for periodic tasks)

```powershell
celery -A app.workers.celery_app beat --loglevel=info --scheduler celery.schedulers:PersistentScheduler
```

### Monitor tasks (Flower UI — optional)

```powershell
pip install flower
celery -A app.workers.celery_app flower --port=5555
# Open http://localhost:5555
```

> **Note:** On Windows, Celery worker requires the `--pool=solo` or `--pool=threads` flag due to `fork()` limitations:  
> `celery -A app.workers.celery_app worker --pool=solo --loglevel=info`

---

## 13. API Documentation

| Interface | URL | Description |
|---|---|---|
| Swagger UI | http://localhost:8000/docs | Interactive API explorer |
| ReDoc | http://localhost:8000/redoc | Clean reference docs |
| OpenAPI JSON | http://localhost:8000/openapi.json | Machine-readable schema |
| Health Check | http://localhost:8000/health | Service liveness probe |

---

## 14. Testing

### Run the full test suite

```powershell
pytest tests/ -v
```

### Run only unit tests

```powershell
pytest tests/unit/ -v
```

### Run only integration tests

```powershell
pytest tests/integration/ -v
```

### Run with coverage report

```powershell
pytest tests/ --cov=app --cov-report=term-missing --cov-report=html
```

### Run a specific test file

```powershell
pytest tests/unit/test_auth_service.py -v
```

The test suite uses an **in-memory SQLite database** (via `aiosqlite`) for unit tests and a **dedicated test PostgreSQL database** for integration tests. The test database URL is read from the `TEST_DATABASE_URL` environment variable, which defaults to `sqlite+aiosqlite:///./test.db`.

---

## 15. Linting & Formatting

### Check for lint errors

```powershell
ruff check app/ tests/
```

### Auto-fix lint errors

```powershell
ruff check app/ tests/ --fix
```

### Format code

```powershell
ruff format app/ tests/
```

### Type checking

```powershell
mypy app/
```

The project is configured via `pyproject.toml` with strict Ruff rules including `E`, `F`, `I`, `N`, `UP`, `ANN`, `ASYNC` rule sets.

---

## 16. Integration Setup

### 16.1 Google Calendar & Gmail

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project (or select existing)
3. Enable the following APIs:
   - Google Calendar API
   - Gmail API
4. Create OAuth2 credentials:
   - Application type: **Web application**
   - Add authorized redirect URI: `http://localhost:8000/api/v1/integrations/google/callback`
5. Download the credentials JSON
6. Set in `.env`:
   ```
   GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=your_client_secret
   GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/integrations/google/callback
   FERNET_KEY=<generated Fernet key>
   ```
7. Start the NEXA API and visit `GET /api/v1/integrations/google/authorize` to initiate the OAuth flow
8. After authorization, tokens are encrypted and stored in PostgreSQL

### 16.2 Telegram Bot

1. Open Telegram and start a chat with [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts to create a bot
3. Copy the bot token provided
4. For webhook mode (recommended for production):
   - Your server must have a valid HTTPS certificate
   - Tunnel for local dev: `ngrok http 8000`
   - Set webhook: `POST https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://your-domain.com/api/v1/integrations/telegram/webhook`
5. Set in `.env`:
   ```
   TELEGRAM_BOT_TOKEN=123456789:ABCdef...
   TELEGRAM_WEBHOOK_SECRET=random_secret_string_32_chars_min
   TELEGRAM_WEBHOOK_URL=https://your-domain.com/api/v1/integrations/telegram/webhook
   ```
6. Users can link their Telegram account via `POST /api/v1/integrations/telegram/link` with their Telegram chat ID

### 16.3 n8n Webhooks

1. Deploy n8n (self-hosted or cloud): https://n8n.io
2. Create a workflow with a **Webhook** trigger node
3. Copy the webhook URL from the node
4. Create an API key in n8n: **Settings → API → Create API Key**
5. Set in `.env`:
   ```
   N8N_BASE_URL=https://your-n8n-instance.com
   N8N_API_KEY=your_n8n_api_key
   ```
6. Register webhook URLs in NEXA via `POST /api/v1/integrations/n8n/webhooks`
7. NEXA will POST to these URLs when the AI agent triggers n8n actions

---

## 17. Security Considerations

### Passwords
- Hashed with **Argon2id** (memory-hard KDF) — resistant to GPU brute-force attacks
- Never stored in plaintext; never logged

### JWT Tokens
- Access tokens expire in **15 minutes** by default
- Refresh tokens rotate on each use — compromised refresh tokens are invalidated
- Tokens are signed with HMAC-SHA256 using `SECRET_KEY`
- Revocation is tracked in Redis for immediate invalidation

### OAuth Tokens (Google)
- Access and refresh tokens encrypted at rest using **Fernet** (AES-128-CBC + HMAC-SHA256)
- `FERNET_KEY` must be kept secret and backed up — loss means users must re-authorize
- Never logged, never returned in API responses

### Transport Security
- All production traffic must use HTTPS (TLS 1.2+)
- Configure your reverse proxy (nginx, Caddy) to terminate TLS
- HSTS headers enabled in production mode

### Input Validation
- All API inputs validated via Pydantic v2 with strict mode
- SQL injection prevented by SQLAlchemy parameterized queries
- Request size limits enforced by Uvicorn

### Secrets Management
- Never commit `.env` to version control (`.gitignore` excludes it)
- Use a secrets manager (HashiCorp Vault, AWS Secrets Manager) in production
- Rotate `SECRET_KEY` and `FERNET_KEY` on a schedule

### Rate Limiting
- Implement rate limiting at the reverse proxy or API gateway layer
- Login endpoint has additional brute-force protection via account lockout

---

## 18. Integration Status

| Integration | Status | Required Env Vars |
|---|---|---|
| OpenAI GPT-4o | ✅ Implemented | `OPENAI_API_KEY` |
| PostgreSQL | ✅ Implemented | `DATABASE_URL`, `POSTGRES_PASSWORD` |
| Redis / Celery | ✅ Implemented | `REDIS_URL` |
| JWT Auth | ✅ Implemented | `SECRET_KEY` |
| Google Calendar | ✅ Implemented | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `FERNET_KEY` |
| Gmail | ✅ Implemented | Same as Google Calendar |
| Telegram Bot | ✅ Implemented | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` |
| n8n Webhooks | ✅ Implemented | `N8N_BASE_URL`, `N8N_API_KEY` |
| Reminders (Celery) | ✅ Implemented | Requires Redis |
| Approval Workflow | ✅ Implemented | No extra config |

---

## 19. Recommended Next Steps

### Immediate (before first production deployment)

- [ ] Generate and securely store `SECRET_KEY` and `FERNET_KEY`
- [ ] Set strong `POSTGRES_PASSWORD` and `REDIS_PASSWORD`
- [ ] Configure HTTPS via nginx/Caddy reverse proxy
- [ ] Set `ALLOWED_ORIGINS` to your actual frontend domain
- [ ] Review and customize approval thresholds in `app/services/approval_service.py`
- [ ] Run `alembic upgrade head` on the production database

### Short-term

- [ ] Add Sentry or similar error tracking (`SENTRY_DSN` env var)
- [ ] Configure Celery worker auto-scaling (Kubernetes KEDA or similar)
- [ ] Add Prometheus metrics endpoint (`/metrics`) + Grafana dashboard
- [ ] Implement per-user rate limiting
- [ ] Add end-to-end tests for the full AI orchestration pipeline

### Medium-term

- [ ] Multi-user tenant isolation (row-level security in PostgreSQL)
- [ ] Voice interface integration (Whisper for STT, TTS for responses)
- [ ] Mobile push notifications (FCM/APNs)
- [ ] Plugin system for community-contributed tools
- [ ] Fine-tune or instruct a smaller model for cost efficiency

### Long-term

- [ ] Extract high-traffic services (e.g., AI orchestration) into separate microservices if needed
- [ ] Implement event sourcing for complete audit trail of agent actions
- [ ] Add compliance features (GDPR data export/deletion)
- [ ] Multi-region deployment with PostgreSQL read replicas
