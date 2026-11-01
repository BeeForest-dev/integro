# AGENTS.md — Rules for AI coding agents working on `integro`

This file is the contract between the human owner and any AI agent (Kimi, Cursor, Claude Code, Codex, etc.)
that writes code in this repository.

## Naming

| Thing | Name | Why |
|---|---|---|
| GitHub repository | `integro` | English name is what international clients see on a portfolio |
| Product name in the UI / README | `Integro` | brand; the README title sells the project, not the folder name |

Never put the local checkout path into user-facing text (README, UI, commit messages).

The owner is the only person allowed to change architecture. Your job: implement a **contract**,
exactly as written, with tests, and stop when the contract is satisfied.

---

## 1. Hard boundaries (do not cross without explicit approval)

1. **Never change** without explicit permission:
   - database schema / Alembic migrations
   - the list of dependencies
   - layer boundaries
   - public API contracts (request/response shapes)

   If a task seems to require one of these, **stop and ask**. Do not "just do it".

2. **Dependency allow-list** (adding anything else requires approval):
   ```
   fastapi, uvicorn[standard], pydantic, pydantic-settings, sqlalchemy, alembic,
   asyncpg, psycopg[binary], celery, redis, httpx, tenacity, structlog,
   cryptography, argon2-cffi, jinja2, python-multipart, prometheus-client,
   pytest, pytest-asyncio, pytest-cov, respx, factory-boy,
   ruff, mypy
   ```
   Standard library is always allowed.

3. **One PR = one contract.** "While we're here" refactors are a separate PR.

4. **Every contract must ship**: implementation + tests (including tests for every
   error case listed in the contract) + docstring + an ADR if an architectural decision changed.

5. **Layering** (import direction is strictly downward):
   ```
   api  ->  services  ->  repositories  ->  models
   workers  ->  services  (workers must NEVER import api)
   connectors  ->  protocols  (connectors must NEVER touch the DB directly)
   ```
   A violation is a reason to reject the PR.

6. **Secrets** live in environment variables only. Never in code, logs, fixtures or docs.
   `.env.example` contains placeholders only.

7. **Every outbound HTTP call must have an explicit timeout.**
   **Every retry policy must include jitter.**

8. **Do not invent features.** If it is not in the contract, do not build it.
   Suggest it instead, in the PR description, as a separate proposal.

9. **No silent behaviour changes.** If a contract is ambiguous, ask one clarifying
   question and wait. Ambiguity is a question, not a licence to guess.

---

## 2. Definition of Ready (the task must have this before you start)

A contract in `docs/CONTRACTS.md` contains:
- purpose (one sentence)
- input -> output
- error cases and the behaviour for each
- side effects (tables touched, external calls)
- allowed dependencies

If any of these are missing, say so and ask. Do not start.

---

## 3. Definition of Done

A module is done only when **all** of the following are true:

- [ ] implementation matches the contract exactly, nothing more
- [ ] every error case from the contract has a test
- [ ] `ruff check .` passes
- [ ] `mypy app` passes (no new errors introduced)
- [ ] `pytest` passes, including the new tests
- [ ] every public function/class has a docstring explaining purpose, args, returns, raises
- [ ] no secrets, no hardcoded URLs, no commented-out code, no `print()` (use `structlog`)
- [ ] an ADR is written or updated if an architectural decision changed
- [ ] the PR description contains the **5-point explanation**:
      1. what it does
      2. why it is built this way
      3. how it is structured internally
      4. where the traps / failure modes are
      5. how to verify it

---

## 4. Output format for every generated module

```
app/<layer>/<module>.py        # implementation
tests/<layer>/test_<module>.py # tests, one per contract error case
docs/adr/NNNN-<slug>.md        # only if a decision changed
```

Explain the module in exactly 5 bullet points at the end of your answer (see DoD).

---

## 5. Review gates the owner applies (your code must survive these)

- **G1 Conformance** — does it do exactly the contract, nothing extra?
- **G2 Tests** — is there a test for each error case in the contract?
- **G3 Boundaries** — timeouts, injection safety, secret leakage, unhandled exceptions?
- **G4 Architecture** — correct import direction, no business logic in routers?

---

## 6. Project structure (do not restructure)

```
integro/          # repo root
  backend/
    app/
      api/            # routers, dependencies, error handlers
      core/           # config, logging, security, errors
      db/             # engine, session, base, migrations
      models/         # SQLAlchemy ORM models
      schemas/        # Pydantic schemas
      repositories/   # data access
      services/       # business logic
      connectors/     # integrations (protocols + implementations)
      workers/        # Celery tasks, scheduler
    tests/
  frontend/
  infra/              # dockerfiles, compose, nginx
  docs/               # architecture, ADRs, contracts, demo script
```

---

## 7. Stack (fixed)

Backend: Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic,
PostgreSQL 16, Celery + Redis, httpx, tenacity, structlog, cryptography.

Frontend: React 19 + TypeScript + Vite + TanStack Query + React Router + Tailwind CSS.
API types are generated from the OpenAPI schema — do not hand-write client types.

Infra: Docker (multi-stage), docker compose, GitHub Actions.

---

## 8. Coordination protocol (read before every task)

`docs/LOOP.md` is the shared channel with the reviewer. **Read it first, update it last.**

1. Read `docs/LOOP.md` -> check the **Current contract** block.
   If `State` is not `CONTRACTED`, **do not start** — wait for the owner.
2. Implement the contract exactly (code + tests + docstrings).
3. Write the delivery note to `docs/reviews/<ID>.md` (template is in `docs/LOOP.md`).
4. Update `docs/LOOP.md`: `State: GENERATED`, `Awaiting: reviewer`, append a log line.
5. **Stop.** Do not begin the next module, do not refactor anything else.

The reviewer (the assistant) will reply in the same file with the verdict and the
required changes. Read the verdict, make exactly those changes, update the file again.

Never mark a module `ACCEPTED` yourself — only the owner does that.

---

## 9. When you are stuck

1. Re-read the contract in `docs/CONTRACTS.md`.
2. Check `docs/EXECUTION-PLAN.md` for the gate list.
3. Write a test that reproduces the problem.
4. If still stuck: **ask one specific question**, present what you tried, and propose two
   options with trade-offs. Never guess silently.
