# HANDOFF — brief for Kimi (or any coding agent)

Paste the relevant section into the agent's chat, or point it at the files if it has
local filesystem access. This brief is self-contained; `docs/CONVERSATION.md` is optional
background context.

---

## 1. What we are building

`integro` (local folder `spidoznye_kozyvki2`) — a **workflow-automation platform**: a company
connects triggers (webhook, Telegram bot, IMAP mailbox, cron) to actions (REST API, CRM,
table write, notification via Slack / Telegram / Email / Webhook) through configurable
flows. The engine runs flows in a queue with retries, idempotency, dead-letter handling
and a replay button.

It is a **demo environment / reference implementation** for a freelance portfolio, and the
base for real client work. Product quality matters: it must look like something a business
could pay for.

Stack (fixed, do not change): Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async),
Alembic, PostgreSQL 16, Celery + Redis, httpx, tenacity, structlog, cryptography.
Frontend: React 19 + TS + Vite + TanStack Query + Tailwind.

---

## 2. Files that matter

| File | What it is |
|---|---|
| `AGENTS.md` | **Rules and boundaries for you.** Read it fully before writing code. |
| `docs/LOOP.md` | **Shared coordination file.** Read first, update last. Says what to work on right now. |
| `docs/CONTRACTS.md` | The contract registry: 54 modules, each with a 3–5 line contract. |
| `docs/EXECUTION-PLAN.md` | How work flows, review gates, cadence. |
| `docs/TRACKER.md` | What is done and what is next. |
| `docs/reviews/` | One delivery note + one review verdict per module. |
| `docs/CONVERSATION.md` | The planning dialogue (background only). |

---

## 3. Hard boundaries (the owner sets these; they are not negotiable without approval)

1. Do **not** change the DB schema, the dependency list, the layer structure, or public
   API contracts. If a task appears to need that — stop and ask.
2. Dependencies are limited to this allow-list; anything else needs approval:
   `fastapi, uvicorn[standard], pydantic, pydantic-settings, sqlalchemy, alembic, asyncpg,
   psycopg[binary], celery, redis, httpx, tenacity, structlog, cryptography, argon2-cffi,
   jinja2, python-multipart, pytest, pytest-asyncio, pytest-cov, respx, factory-boy,
   ruff, mypy`. Standard library is always fine.
3. One change = one contract. No "while we're here" refactors.
4. **Do not invent features.** If it is not in the contract, propose it in your answer
   instead of building it.
5. Layering is strictly downward: `api -> services -> repositories -> models`.
   Workers never import `api`. Connectors never touch the DB.
6. Secrets come from environment variables only. Never in code, logs, fixtures or docs.
7. Every outbound HTTP call needs an explicit timeout. Every retry policy needs jitter.
8. Ambiguity in a contract → ask **one** clarifying question, then stop. Do not guess.

---

## 4. How we work together (per module)

1. The owner states the contract (already written in `docs/CONTRACTS.md`).
2. You implement it **exactly**: code + a test for **every** error case in the contract
   + docstrings on public functions.
3. You explain the module in exactly 5 points:
   what it does / why it is built this way / how it is structured / where the traps are /
   how to verify it.
4. The owner reviews against 4 gates: conformance, tests, boundaries, architecture.

---

## 5. The task right now — module C01 `core.config`

> The authoritative source of "what to do right now" is `docs/LOOP.md`.
> If `State` there is not `CONTRACTED`, do not start — ask the owner.

Full contract from `docs/CONTRACTS.md`:

```
C01 core.config
Purpose:    load and validate application settings from environment.
In -> Out:  Settings object (immutable) from env + .env file.
Errors:     missing required var -> app refuses to start with a named error;
            invalid type (e.g. DATABASE_URL="foo") -> validation error naming the field.
Side fx:    reads env / .env only.
Deps:       pydantic-settings.
```

### Copy-paste prompt for the agent

```
Implement module C01 (core.config) according to the contract below.
Project rules are in AGENTS.md — read it first and obey the boundaries.

Hard boundaries for this task:
- Do NOT change the DB schema, add dependencies, or restructure layers.
- Do NOT implement anything beyond the contract.
- Every error case in the contract MUST have a test.
- Public functions/classes need docstrings.

Deliver:
  backend/app/core/config.py
  backend/tests/core/test_config.py
  .env.example  (placeholders only, no real values)

Then explain the module in exactly 5 points:
what it does / why built this way / how it is structured / where the traps are /
how to verify it.

CONTRACT:
Purpose:    load and validate application settings from environment.
In -> Out:  Settings object (immutable) from env + .env file.
Errors:     missing required var -> app refuses to start with a named error;
            invalid type (e.g. DATABASE_URL="foo") -> validation error naming the field.
Side fx:    reads env / .env only.
Deps:       pydantic-settings.
```

---

## 6. Queue after C01

`C02 core.logging` → `C03 core.errors` → `C04 db.engine` → `C05 db.base + migrations` →
`C06 api.health` → `C07 infra.docker` → `C08 ci.github-actions` → `C09 api.request_context`

Do **not** start the next module until the current one has passed the owner's 4 gates.

---

## 7. Environment note

The project root is `C:\Projects\spidoznye_kozyvki2` (repo name on GitHub: `integro`).
Docker and Git are not installed yet on this machine — the owner installs them in
parallel. Python 3.13 is present locally; the project pins **3.12** in Docker.
