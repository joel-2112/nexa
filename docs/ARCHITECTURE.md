# NEXA Architecture Decision Records

> **Document type:** Architecture Decision Record (ADR) collection  
> **Status:** Living document — updated as decisions evolve  
> **Audience:** Engineers, technical leads, and contributors

---

## Table of Contents

1. [Modular Monolith Rationale](#1-modular-monolith-rationale)
2. [AI Orchestration Design](#2-ai-orchestration-design)
3. [Tool Registry Pattern](#3-tool-registry-pattern)
4. [Approval Workflow State Machine](#4-approval-workflow-state-machine)
5. [Conversation State Management](#5-conversation-state-management)
6. [Security Model](#6-security-model)
7. [Background Job Design](#7-background-job-design)
8. [Integration Architecture](#8-integration-architecture)
9. [Database Design](#9-database-design)
10. [Future Evolution Path](#10-future-evolution-path)

---

## 1. Modular Monolith Rationale

### Decision

NEXA is built as a **modular monolith** — a single deployable process with strict internal domain boundaries — rather than a microservices architecture.

### Context

At initial conception, NEXA serves a small number of users with a complex AI orchestration pipeline that involves:

- Multiple sequential steps (plan → approve → execute → respond)
- Shared database transactions across domains (e.g., creating a task atomically with its first approval record)
- Tight coupling between conversation state and tool execution

### Options Considered

| Approach | Pros | Cons |
|---|---|---|
| **Modular Monolith** ✅ | Simple ops, atomic transactions, easy refactoring | Vertical scaling only, single failure domain |
| **Microservices** | Independent scaling, fault isolation, polyglot | High operational overhead, distributed tracing required, complex deployment |
| **Serverless Functions** | No idle cost, auto-scaling | Cold starts incompatible with stateful AI sessions, complex orchestration |

### Decision Rationale

1. **Operational simplicity**: One `docker compose up` starts the entire system. No service mesh, no distributed tracing infrastructure needed at this stage.

2. **Atomic consistency**: The approval workflow requires creating multiple DB records atomically. Cross-service transactions require Saga patterns that add significant complexity without commensurate benefit at this scale.

3. **Refactoring velocity**: Domain boundaries are enforced by Python import rules and service layer abstractions. Extracting a service later means moving a directory and adding an HTTP client — a well-understood migration.

4. **Context**: NEXA is a personal assistant. It is unlikely to need true horizontal per-domain scaling. If it does, the modular structure provides clean extraction seams.

### Consequences

- All domains must respect the import hierarchy: `routers → services → models`. Cross-domain service calls go through service interfaces, never directly between ORM models.
- The Celery worker runs as a separate process but shares the same codebase, maintaining a single source of truth.
- Performance bottlenecks will be vertical (larger instances) first, then selective extraction of hot paths.

---

## 2. AI Orchestration Design

### Decision

The AI orchestration pipeline follows a strict layered design: `NexaAgent → Orchestrator → Planner → ToolRegistry → ToolExecutor`. Each layer has a single responsibility.

### Pipeline Architecture

```
┌──────────────────────────────────────────────────────────┐
│                      NexaAgent                           │
│  - Assembles system prompt                               │
│  - Loads conversation history (last N turns)             │
│  - Calls Orchestrator                                    │
│  - Formats final response for the user                   │
└───────────────────────┬──────────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────────┐
│                     Orchestrator                          │
│  - Calls LLM API (OpenAI Chat Completions)               │
│  - Parses tool_calls from the LLM response               │
│  - Implements the ReAct loop (reason → act → observe)    │
│  - Caps iterations to prevent infinite loops             │
│  - Aggregates tool outputs for next LLM call             │
└───────────────────────┬──────────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────────┐
│                      Planner                              │
│  - Validates that the proposed plan is feasible          │
│  - Checks tool parameter schemas                         │
│  - Estimates execution risk level                        │
│  - Flags high-risk tools for the approval workflow       │
└───────────────────────┬──────────────────────────────────┘
                        │
              ┌─────────┴──────────┐
              │                    │
  ┌───────────▼──────┐  ┌──────────▼─────────────┐
  │  ApprovalService │  │     ToolRegistry         │
  │  (high-risk path)│  │  - Resolves tool name    │
  │  - Creates DB    │  │  - Returns ToolExecutor  │
  │    approval row  │  │  - Validates arguments   │
  │  - Notifies user │  └──────────┬───────────────┘
  └──────────────────┘             │
                        ┌──────────▼───────────────┐
                        │      ToolExecutor         │
                        │  - Runs tool function     │
                        │  - Enforces timeout       │
                        │  - Retries on transient   │
                        │    failures               │
                        │  - Sanitises output       │
                        └──────────────────────────┘
```

### ReAct Loop Design

The Orchestrator implements the **ReAct** (Reason + Act) pattern:

```
while iteration < MAX_ITERATIONS:
    response = llm.chat(messages + tool_results)
    
    if response.finish_reason == "stop":
        return response.content   # final answer
    
    if response.finish_reason == "tool_calls":
        for tool_call in response.tool_calls:
            result = ToolRegistry.execute(tool_call)
            tool_results.append(result)
        
        messages.append(assistant_message_with_tool_calls)
        messages.append(tool_results_as_tool_messages)
    
    iteration += 1

raise OrchestratorMaxIterationsError
```

### Why Not LangChain / LlamaIndex?

| Concern | Detail |
|---|---|
| **Vendor lock-in** | Framework abstractions hide critical behavior. Upgrading the framework often breaks production. |
| **Debuggability** | Framework-generated prompts and chains are opaque. Direct LLM calls are fully inspectable. |
| **Control** | The approval workflow requires deep integration with the tool execution loop — frameworks make this difficult. |
| **Performance** | Frameworks introduce latency from abstraction layers. Direct async calls are faster. |

The orchestration is ~300 lines of well-documented Python and far easier to reason about than any framework equivalent.

---

## 3. Tool Registry Pattern

### Decision

All agent-executable capabilities are **registered tools** with explicit schemas. The agent cannot execute arbitrary code or call arbitrary URLs.

### Why a Registry?

The core security property of NEXA is: **the agent can only do what has been explicitly permitted**.

Without a registry, an LLM could be prompted (via adversarial input or model misbehavior) to execute arbitrary shell commands, make arbitrary HTTP requests, or access unintended system resources.

### Registration Contract

Every tool must implement the `BaseTool` interface:

```python
class BaseTool(ABC):
    name: str                    # Unique identifier used in LLM tool calls
    description: str             # Human-readable + LLM-readable description
    parameters_schema: dict      # JSON Schema for argument validation
    risk_level: RiskLevel        # LOW | MEDIUM | HIGH
    requires_approval: bool      # Derived from risk_level

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        ...
```

### Risk Levels

| Level | Examples | Behavior |
|---|---|---|
| `LOW` | Read calendar, search emails | Executed directly |
| `MEDIUM` | Send Telegram message | Executed directly with audit log |
| `HIGH` | Send email, delete calendar event, trigger n8n | Requires explicit user approval |

### Argument Validation

Tool arguments are validated against `parameters_schema` using `jsonschema.validate()` before execution. Invalid arguments raise `ToolArgumentError` and are reported back to the LLM for correction.

### Registry Lookup

```python
tool = ToolRegistry.resolve("google_calendar_create_event")
result = await ToolExecutor.run(tool, arguments=parsed_args)
```

If `resolve()` cannot find the tool, it raises `ToolNotFoundError` — the agent never falls through to arbitrary execution.

---

## 4. Approval Workflow State Machine

### Decision

Tool calls with `risk_level == HIGH` are paused and require explicit user approval before execution. The approval state is persisted in PostgreSQL.

### State Diagram

```
                   ┌──────────────┐
                   │  (created)   │
                   └──────┬───────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │ pending_approval │  ◄── Approval row created
                 └───┬─────────┬────┘      User notified (Telegram/email)
                     │         │
            approve  │         │ reject
                     │         │
              ┌──────▼──┐  ┌───▼──────┐
              │approved │  │ rejected │  ◄── Terminal state
              └──────┬──┘  └──────────┘
                     │
              execute│
                     ▼
              ┌──────────────┐
              │  executing   │  ◄── Tool running
              └──────┬───────┘
                     │
           ┌─────────┴─────────┐
           │                   │
     success│             failure│
           │                   │
    ┌──────▼──────┐    ┌────────▼──────┐
    │  completed  │    │    failed     │  ◄── Terminal state
    └─────────────┘    └───────────────┘
```

### State Transitions

| Transition | Actor | Precondition |
|---|---|---|
| `created → pending_approval` | ApprovalService | Tool has `risk_level == HIGH` |
| `pending_approval → approved` | User (via API or Telegram button) | Token valid, approval belongs to user |
| `pending_approval → rejected` | User | Token valid, approval belongs to user |
| `approved → executing` | ToolExecutor | Called after user approves |
| `executing → completed` | ToolExecutor | Tool returned successfully |
| `executing → failed` | ToolExecutor | Tool raised exception |

### Timeout Policy

Approvals in `pending_approval` state expire after a configurable `APPROVAL_TIMEOUT_HOURS` (default: 24 hours). A Celery beat task scans for expired approvals and transitions them to `failed` with reason `"approval_timeout"`.

### Idempotency

The approval `id` (UUID) is used as the idempotency key for tool execution. If the `executing → completed` transition fails to persist (e.g., network partition), the executor checks the approval state before re-executing to prevent duplicate tool calls.

---

## 5. Conversation State Management

### Decision

Conversation history is stored in PostgreSQL as a series of `ConversationTurn` rows. When calling the LLM, we send only the **last N turns** (not full history) to manage context window size and cost.

### Data Model

```
Conversation
├── id: UUID
├── user_id: UUID (FK → users)
├── title: str
├── metadata: JSONB          ← arbitrary key-value for future use
├── created_at: timestamptz
└── updated_at: timestamptz

ConversationTurn
├── id: UUID
├── conversation_id: UUID (FK → conversations)
├── role: Enum (user | assistant | tool | system)
├── content: text            ← message text or tool output
├── tool_name: str | null    ← populated for tool/assistant turns
├── tool_call_id: str | null ← OpenAI tool_call_id for correlation
├── metadata: JSONB          ← token counts, latency, model used
├── created_at: timestamptz
└── sequence: int            ← ordering within conversation
```

### Why JSONB for Metadata?

Conversation turns accumulate rich per-turn metadata (token counts, latency, model version, tool arguments) that evolves over time as new features are added. Using `JSONB` avoids schema migrations for new metadata fields while keeping the core schema stable.

The `metadata` column is indexed with a GIN index to support queries like "find all turns where a specific tool was used."

### Context Window Strategy

```python
MAX_HISTORY_TURNS = 20       # configurable per-user
MAX_HISTORY_TOKENS = 32_000  # hard limit based on model

# When assembling the prompt:
turns = await db.select(ConversationTurn)
    .where(conversation_id == ...)
    .order_by(sequence.desc())
    .limit(MAX_HISTORY_TURNS)
    .all()

turns = truncate_to_token_limit(reversed(turns), MAX_HISTORY_TOKENS)
```

This guarantees the LLM receives the most recent turns without exceeding the context limit.

### Why Not In-Memory State?

In-memory conversation state would be lost on:
- API server restart
- Deployment
- Horizontal scaling (different request lands on different instance)

PostgreSQL persistence ensures conversations survive restarts and are accessible across all API instances.

---

## 6. Security Model

### Authentication

NEXA uses a **dual-token JWT scheme**:

```
Access Token  (short-lived: 15 min)  — sent with every API request
Refresh Token (long-lived: 30 days)  — used only to get a new access token
```

**Refresh token rotation**: Each refresh token is single-use. When used, it is invalidated and a new refresh token is issued. Stolen refresh tokens become useless after first legitimate use.

**Token revocation**: The `jti` (JWT ID) of revoked tokens is stored in Redis with a TTL matching the token expiry. This allows immediate revocation without database lookups on every request.

### Password Security

Passwords are hashed with **Argon2id** (via `argon2-cffi`):

```python
# Parameters (OWASP recommended minimums for 2024)
ARGON2_TIME_COST = 3        # iterations
ARGON2_MEMORY_COST = 65536  # 64 MiB
ARGON2_PARALLELISM = 4      # threads
ARGON2_HASH_LENGTH = 32     # bytes
```

Argon2id is memory-hard, making GPU-based attacks impractical even if the database is breached.

### OAuth Token Encryption

Google OAuth tokens (access + refresh) are encrypted before database storage using **Fernet** (from the `cryptography` library):

- **Algorithm**: AES-128-CBC with PKCS7 padding + HMAC-SHA256 authentication
- **Key management**: The `FERNET_KEY` is a 32-byte URL-safe base64-encoded key
- **Rotation**: Support for key rotation via `MultiFernet` with multiple keys

```python
from cryptography.fernet import Fernet, MultiFernet

# Encryption
fernet = Fernet(settings.FERNET_KEY.encode())
encrypted_token = fernet.encrypt(raw_token.encode()).decode()

# Decryption
raw_token = fernet.decrypt(encrypted_token.encode()).decode()
```

The encrypted value stored in the database is useless without the `FERNET_KEY`.

### Request Validation

- All inputs validated via Pydantic v2 strict mode
- File uploads (future feature) will have MIME type validation and size limits
- Structured error responses never leak internal stack traces in production

### Audit Trail

All tool executions (approved or not) are logged to:
1. structlog structured log output (ingested by log aggregator)
2. The `ConversationTurn` table with `role="tool"` and metadata

This provides a complete audit trail of everything the AI agent did on behalf of the user.

---

## 7. Background Job Design

### Decision

Celery with Redis as broker handles all asynchronous work. Tasks are designed to be **idempotent** — safe to retry on failure.

### Queue Architecture

```
Celery Beat (scheduler process)
    │
    ├── reminders queue
    │       └── ReminderDeliveryTask
    │               → Check reminder is still pending
    │               → Deliver via Telegram / email
    │               → Mark reminder as delivered
    │
    ├── notifications queue
    │       └── NotificationTask
    │               → Send push/Telegram notification
    │               → Log delivery status
    │
    └── default queue
            └── General async tasks
                    → OAuth token refresh
                    → Approval expiry scanner
                    → Data cleanup tasks
```

### Idempotency Design

Every task accepts an `idempotency_key` parameter (typically a UUID from the database row being processed):

```python
@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
async def deliver_reminder(self, reminder_id: str) -> None:
    async with get_db_session() as session:
        reminder = await session.get(Reminder, UUID(reminder_id))
        
        if reminder is None or reminder.status != ReminderStatus.PENDING:
            return  # Already delivered or cancelled — safe to skip
        
        try:
            await telegram_service.send_message(
                chat_id=reminder.user.telegram_chat_id,
                text=reminder.message,
            )
            reminder.status = ReminderStatus.DELIVERED
            reminder.delivered_at = utcnow()
            await session.commit()
        except Exception as exc:
            raise self.retry(exc=exc)
```

The idempotency check (`status != PENDING`) ensures that retried tasks do not deliver duplicate reminders.

### Persistent Scheduling

Celery Beat uses `PersistentScheduler` to store the schedule state on disk. This prevents "burst replay" (all missed jobs firing at once) after a beat process restart.

Dynamic schedules (user-created reminders) are managed via `celery_app.send_task(..., eta=reminder.scheduled_at)` — sending a task with a future ETA rather than a cron schedule.

### Failure Handling

| Failure Type | Strategy |
|---|---|
| Transient (network, timeout) | Exponential backoff retry (max 3 times) |
| Permanent (deleted resource) | Mark task as failed, log, do not retry |
| Task queue full | Redis LIST max length configured; excess tasks wait |
| Beat process down | Tasks fire in burst when beat restarts (bounded by `max_retries`) |

---

## 8. Integration Architecture

### Decision

External integrations are designed with **graceful degradation** — NEXA boots and operates correctly even if credentials for an integration are absent. Missing credentials disable the associated tools.

### Integration Lifecycle

```
Application startup
        │
        ▼
IntegrationService.load_available_tools()
        │
        ├── GOOGLE_CLIENT_ID present? → Register calendar + gmail tools
        │   └── No? → Log warning, skip registration
        │
        ├── TELEGRAM_BOT_TOKEN present? → Start Telegram bot + register tool
        │   └── No? → Log warning, skip registration
        │
        └── N8N_BASE_URL present? → Register n8n webhook tool
            └── No? → Log warning, skip registration

ToolRegistry.available_tools()
        └── Returns only registered tools
```

The LLM is given a system prompt that lists only the tools that are registered. If Google is not configured, the LLM is never told about calendar tools and will not attempt to call them.

### OAuth Token Lifecycle (Google)

```
1. User visits GET /api/v1/integrations/google/authorize
        │
        ▼
2. NEXA generates OAuth URL with state parameter (CSRF protection)
        │
        ▼
3. User authorizes in Google
        │
        ▼
4. Google redirects to GET /api/v1/integrations/google/callback?code=...
        │
        ▼
5. NEXA exchanges code for access_token + refresh_token
        │
        ▼
6. Tokens encrypted with Fernet, stored in OAuthCredential table
        │
        ▼
7. Tool calls decrypt token on-demand, refresh if expired
```

### Integration Adapter Pattern

Each integration exposes a clean async interface:

```python
class GoogleCalendarAdapter:
    async def list_events(
        self,
        user_id: UUID,
        time_min: datetime,
        time_max: datetime,
        max_results: int = 10,
    ) -> list[CalendarEvent]: ...

    async def create_event(
        self,
        user_id: UUID,
        event: CalendarEventCreate,
    ) -> CalendarEvent: ...
```

The adapter handles token retrieval, decryption, refresh, and re-encryption transparently. The tool layer calls the adapter and never touches token management directly.

### Error Handling at Integration Boundaries

```python
try:
    result = await google_calendar.list_events(...)
except GoogleTokenExpiredError:
    await integration_service.refresh_google_token(user_id)
    result = await google_calendar.list_events(...)  # retry once
except GoogleAuthRevokedError:
    await integration_service.mark_integration_revoked(user_id, "google")
    raise ToolExecutionError("Google authorization has been revoked. Please re-authorize.")
except httpx.TimeoutException:
    raise ToolExecutionError("Google Calendar request timed out. Please try again.")
```

Errors are translated from HTTP/OAuth errors into domain errors that the LLM can communicate meaningfully to the user.

---

## 9. Database Design

### Decision

All tables use **UUID v4 primary keys**, **timezone-aware UTC timestamps**, and **JSONB for flexible metadata**. These are non-negotiable standards applied uniformly.

### Why UUID Primary Keys?

| Concern | UUID Benefit |
|---|---|
| Distributed generation | PKs can be generated in application code without a DB round-trip |
| Security | Sequential integer PKs leak record counts; UUIDs do not |
| Merge-ability | No PK collision when merging data from multiple environments |
| Future sharding | UUIDs work with hash-based sharding; sequential IDs do not |

Performance note: PostgreSQL 16 uses `gen_random_uuid()` natively and stores UUIDs efficiently as 16-byte binary values. The performance difference vs. integer PKs is negligible for NEXA's expected scale.

### Why Timezone-Aware Timestamps?

```python
# Always store and return UTC
created_at: Mapped[datetime] = mapped_column(
    DateTime(timezone=True),
    server_default=func.now(),
    nullable=False,
)
```

- PostgreSQL `TIMESTAMPTZ` stores timestamps in UTC internally
- Python `datetime` objects are always `timezone=utc` in application code
- Conversion to user's local timezone happens at the presentation layer only
- This eliminates an entire class of DST-related bugs

### JSONB Usage Policy

JSONB is used for fields that:

1. **Vary by record** — e.g., tool call arguments differ per tool
2. **Evolve over time** — e.g., metadata fields added without migrations
3. **Are queried but not joined on** — e.g., searching turns where a tool was used

JSONB is **not** used as a schema escape hatch for data that should have proper columns:

```python
# ✅ JSONB — flexible, evolving metadata
metadata: Mapped[dict] = mapped_column(JSONB, default=dict)

# ❌ Not JSONB — this should be a proper column
user_email: Mapped[str]  # always a known, queryable field
```

### Key Tables and Relationships

```
users (1) ──────────────────── (N) conversations
                                        │
                               (1) ─────┴──── (N) conversation_turns
                               
users (1) ──────────────────── (N) oauth_credentials
users (1) ──────────────────── (N) reminders
users (1) ──────────────────── (N) approvals
conversations (1) ──────────── (N) tasks
tasks (1) ──────────────────── (1) approvals
```

### Index Strategy

```sql
-- Fast user lookups
CREATE UNIQUE INDEX idx_users_email ON users(email);

-- Conversation listing by user
CREATE INDEX idx_conversations_user_id ON conversations(user_id);

-- Turn ordering within conversation
CREATE INDEX idx_turns_conversation_sequence
    ON conversation_turns(conversation_id, sequence);

-- Pending approval lookup
CREATE INDEX idx_approvals_status_user
    ON approvals(user_id, status)
    WHERE status = 'pending_approval';

-- GIN index for JSONB metadata search
CREATE INDEX idx_turns_metadata ON conversation_turns USING GIN(metadata);
```

---

## 10. Future Evolution Path

### Phase 1: Current State (Modular Monolith)

```
┌────────────────────────────────────────────┐
│              nexa_api process               │
│  ┌────────┐ ┌────────┐ ┌────────────────┐  │
│  │  Auth  │ │  Conv  │ │  AI Agent      │  │
│  │ Module │ │ Module │ │  Orchestration │  │
│  └────────┘ └────────┘ └────────────────┘  │
│  ┌────────┐ ┌────────┐ ┌────────────────┐  │
│  │ Tools  │ │Integr. │ │   Approvals    │  │
│  │ Module │ │ Module │ │   Module       │  │
│  └────────┘ └────────┘ └────────────────┘  │
└────────────────────────────────────────────┘
         │                      │
    PostgreSQL                Redis
```

### Phase 2: Multi-Tenancy Addition

Add `organization_id` as a foreign key to `users` and all resource tables. Implement row-level security in PostgreSQL:

```sql
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON conversations
    USING (user_id = current_setting('app.user_id')::uuid);
```

No service extraction required — this is a pure schema + middleware change.

### Phase 3: Selective Service Extraction (if needed)

If a specific domain hits scaling limits, extract it as a service:

```
Candidate 1: AI Orchestration Service
  - Trigger: LLM API calls consuming too many threads
  - Solution: Dedicated async service with connection pool
  - Migration: Move app/ai/ → nexa-ai-service, replace with gRPC client

Candidate 2: Notification Service
  - Trigger: High notification volume blocking other workers
  - Solution: Dedicated Celery worker cluster with separate Redis
  - Migration: Extract app/workers/ + dedicated broker

Candidate 3: Integration Adapters
  - Trigger: Google/Telegram rate limits require per-user queuing
  - Solution: Integration gateway with per-user token bucket
  - Migration: Move app/integrations/ → nexa-integration-service
```

### Phase 4: Full Microservices (if justified)

Only if NEXA scales to thousands of concurrent users per service domain. At that point:

- Each Phase 3 service gets its own database schema (database-per-service)
- Synchronous calls become async events via a message bus (Kafka or Redis Streams)
- A dedicated API Gateway handles auth and routing
- Each service gets independent CI/CD pipelines

**This phase should not be implemented prematurely.** The modular monolith handles tens of thousands of users comfortably with proper indexing and connection pooling.

### Decision Triggers for Extraction

| Metric | Threshold | Action |
|---|---|---|
| API p99 latency | > 2 seconds sustained | Profile and optimize, then consider extraction |
| DB connection pool saturation | > 90% utilization | Add read replica, then connection pooler (PgBouncer) |
| Worker queue depth | > 10,000 pending tasks | Add worker instances, then dedicated queue service |
| Single-domain CPU | > 70% of total | Extract that domain as a service |

The guiding principle: **measure first, extract if and only if the data justifies it**.

---

*Last updated: 2026-11-06*  
*Maintainers: NEXA Engineering*
