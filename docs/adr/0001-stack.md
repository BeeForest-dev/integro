# ADR 0001 — Technology stack

**Status:** DRAFT — needs owner approval
**Date:** 2026-10-22
**Deciders:** owner

## Context

`integro` is a workflow-automation platform used as a portfolio project for international
clients and as a foundation for real client work. It must look and behave like a commercial
product: reliable background processing, tenant isolation, a usable admin UI, one-command
startup and automated tests.

Constraints:

- The owner's strongest language is Python (4k LOC of production-ish stdlib code already written).
- Positioning is **full-stack**, so the project needs a real frontend, not a server-rendered page.
- The demo must run on any machine with one command and without external accounts.
- The project must be understandable and defensible by the owner in a client call.

## Decision

**Backend:** FastAPI + Pydantic v2 + SQLAlchemy 2 (async) + Alembic + PostgreSQL 16,
Celery + Redis for background work, httpx + tenacity for outbound calls.

**Python:** 3.13 (`.python-version`, Docker base image, CI). Chosen because the whole
pinned stack is already green on 3.13.1, it has a longer support window than 3.12, and
3.12 is not installed on the development machine. 3.14 is deliberately avoided until
Celery and the connector libraries catch up.

**Metrics:** `prometheus-client` exposes `/metrics` in the Prometheus text format.
The registry is per process, so multi-worker deployments need the library's
multiprocess mode; the demo runs a single uvicorn worker.

**Database drivers:** the application connects through asynchronous `asyncpg`
(`postgresql+asyncpg://`), while Alembic migrations run through synchronous
`psycopg[binary]` (`postgresql+psycopg://`). `backend/alembic/env.py` converts the
`DATABASE_URL` DSN between the two schemes at migration time, so a single
environment variable serves both paths without a second config source.

**Frontend:** React 19 + TypeScript + Vite + TanStack Query + Tailwind CSS.
API types generated from the OpenAPI schema.

**Infrastructure:** Docker (multi-stage), docker compose, GitHub Actions.

## Alternatives considered

| Option | Why rejected |
|---|---|
| Django + DRF + Celery | Bateries included, but heavier; the project needs an API-first service and a separate SPA. FastAPI's OpenAPI generation removes hand-written client types. |
| Flask | Too little structure for a multi-tenant service with background tasks; the owner would re-invent DI and validation. |
| Node/NestJS backend | Would discard the owner's Python advantage and the existing IMAP/Telegram experience. |
| Server-rendered Jinja + HTMX | Faster to build, but weakens the full-stack positioning the portfolio needs. |
| Kafka instead of Redis | The workload is task queues, not event streaming; over-engineering with no commercial benefit. |
| Kubernetes | No client pays for it in this project; compose is enough for a demo and for small deployments. |
| `arq` instead of Celery | Lighter, but Celery's retry/beat ecosystem is what clients recognise; fewer surprises. |
| MongoDB | Workflow definitions are relational (flows → runs → steps); JSONB in PostgreSQL covers the document part without giving up transactions. |

## Consequences

**Positive**

- One language for the backend, the existing domain experience is reusable (IMAP, Telegram).
- OpenAPI → generated TS client keeps the frontend and backend in sync.
- JSONB lets flow definitions evolve without a migration per schema change.
- Compose + CI is exactly what clients check first.

**Negative**

- Two stacks (Python + TS) means two toolchains; mitigated by Docker and a single CI pipeline.
- Async SQLAlchemy has a learning curve; the owner must be able to explain `asyncpg` vs `psycopg`
  and session lifecycle in a review.
- Celery + beat adds operational surface (worker + scheduler containers).

**Neutral**

- Redis serves as both broker and (later) rate-limit store — one dependency, two roles.
