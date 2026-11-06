# LOOP — coordination file

This file is the only shared channel between the agents working on this project.

- Implementer: Kimi / any coding agent
- Reviewer: the assistant in OpenCode (or the owner acting as reviewer)

Both agents read this file first and update it last.

## Protocol

### Implementer (Kimi)
1. Read AGENTS.md and docs/CONTRACTS.md.
2. Read the Current contract section below. If State is not CONTRACTED, do nothing.
3. Implement the contract exactly (code + a test per error case + docstrings).
4. Write a delivery note into docs/reviews/<ID>.md using the template in section "Review file".
5. Update the Current contract block below: State: GENERATED, add a timestamped line to the log, and set Awaiting: reviewer.
6. Stop. Do not start the next module.

### Reviewer (assistant)
1. Read docs/reviews/<ID>.md and the produced files.
2. Run the 4 gates (G1–G4).
3. Write the verdict into docs/reviews/<ID>.md.
4. Update the Current contract block below and the Log.

### Owner (human)
Moves CHANGES_REQUESTED -> CONTRACTED after checking changes, and decides when to start the next module.

## Current contract

```
ID:          C12
Name:        repositories.org_scope
State:       GENERATED
Owner:       human
Implementer: kimi
Reviewer:    assistant
Awaiting:    reviewer
Contract:    see docs/CONTRACTS.md, section C12
Delivery:    docs/reviews/C12.md
Note:        CHANGES_REQUESTED 2026-11-07 (anti-leak keystone, adversarial
             review): (1) reject or_ anywhere in the WHERE clause;
             (2) execute() must isinstance-check Select -> ScopeError for
             text()/union() (today: AttributeError); (3) require single FROM
             entity + pin belongs to it (join-poison future-proof);
             (4) docstring states the enforced invariant precisely;
             (5) tests: OR/union/text/two-entity rejections + self-checks.
             Reviewer-verified: OR-poison leaks a foreign row today;
             honest-path tests are mutation-proven. See docs/reviews/C12.md.
```
## Log (append only, newest last)

| When | Who | Event |
|---|---|---|
| 2026-10-22 11:30 | owner | protocol initialised |
| 2026-10-22 11:45 | implementer | C01 GENERATED (core.config + tests + .env.example) — awaiting reviewer |
| 2026-10-22 12:10 | reviewer | C01 ACCEPTED (G1–G4 pass, 7/7 tests green) |
| 2026-10-22 12:25 | implementer | C02 GENERATED (core.logging + tests) — awaiting reviewer |
| 2026-10-22 12:40 | reviewer | C02 ACCEPTED (G1–G4 pass, 11/11 tests green) |
| 2026-10-22 12:45 | implementer | C03 GENERATED (core.errors + tests) — awaiting reviewer |
| 2026-10-22 12:55 | reviewer | C03 ACCEPTED (G1–G4 pass, 17/17 tests green) |
| 2026-10-22 12:56 | owner | Move to C04 db.engine — CONTRACTED, awaiting implementer |
| 2026-10-22 13:40 | implementer | C04 GENERATED (db.engine + 6 tests) — awaiting reviewer |
| 2026-10-22 13:55 | owner | instruction "continue" — start C05 while C04 review still pending |
| 2026-10-22 14:20 | implementer | C05 GENERATED (db.base + alembic wiring + 6 tests) — awaiting reviewer |
| 2026-10-26 14:05 | reviewer | C04 CHANGES_REQUESTED — code passes G1/G3/G4, but suite cannot collect in a clean checkout (no manifest) and ruff fails; see docs/reviews/C04.md |
| 2026-10-26 14:05 | reviewer | C05 CHANGES_REQUESTED — `alembic upgrade head` on real PostgreSQL fails (psycopg undeclared), conflict test targets the wrong case, ruff fails; see docs/reviews/C05.md |
| 2026-10-31 12:00 | reviewer | Re-checked C04/C05: no changes (HEAD 1138278, tree clean). Clean venv fails collection on all 6 test modules; ruff still 12 errors. Verdicts stand. |
| 2026-10-31 15:30 | implementer | C04+C05 fixes applied (requirements.txt manifest, httpx.ASGITransport test, psycopg declared + ADR note, literal duplicate-revision-id conflict test, ruff/mypy clean) — clean venv: 28 passed, ruff/mypy green; real PG16: upgrade head + current = 0001_baseline (head). Awaiting reviewer. |
| 2026-10-31 16:20 | reviewer | C04 ACCEPTED — clean venv from requirements.txt: 28 passed, ruff clean, mypy clean; 503 via httpx.ASGITransport. Non-blocking: pin ruff config, Python 3.12 vs 3.13. |
| 2026-10-31 16:20 | reviewer | C05 ACCEPTED — real PG16: upgrade head -> current = 0001_baseline (head), downgrade base and re-upgrade exit 0; duplicate-revision-id conflict test added; ruff/mypy clean. Non-blocking: mako import block still fails ruff on empty migrations (fix before C10). |
| 2026-10-31 16:20 | reviewer | C04+C05 closed; awaiting owner. C06 api.health not started. |
| 2026-10-31 17:05 | owner | decisions: prometheus-client allowed; Python 3.13; ruff config pinned + Alembic template fixed. |
| 2026-10-31 17:10 | reviewer | chore: `backend/pyproject.toml` (ruff, py313, isort known-third-party=alembic, F401 ignore for generated revisions), `script.py.mako` import order + blank-line fix, E501 wraps, `AGENTS.md` (3.13, prometheus-client), ADR 0001, `.python-version`. Clean venv: 28 passed, ruff/mypy clean; generated migrations (empty and with ops) pass ruff; PG16 upgrade/downgrade/re-upgrade exit 0. |
| 2026-10-31 17:10 | reviewer | C06 api.health CONTRACTED — awaiting implementer. |
| 2026-10-31 20:30 | implementer | C07 GENERATED (workers celery_app+ping, infra/Dockerfile, mock-crm, root compose.yaml 7/7 healthy, .dockerignore; requirements +celery==5.6.3) — clean venv: 38 passed, ruff/mypy clean; compose build/up/down -v exit 0; e2e ping.delay().get() -> pong; worker/beat healthcheck negatives exit 1. Awaiting reviewer. |
| 2026-10-31 18:30 | implementer | C06 GENERATED (api/health + db/redis + main.py lifespan + 8 tests; requirements +uvicorn[standard]==0.54.0, redis==8.1.0, prometheus-client==0.26.0) — clean venv: 36 passed, ruff/mypy clean; live pg16+redis7: /ready 200, redis stopped -> 503 failed=["redis"]. Awaiting reviewer. |
| 2026-10-31 19:15 | implementer | C06 fix: added test_ready_reports_real_unreachable_redis (real init_redis/check_redis via port-1 refused connection) — clean venv: 37 passed, ruff/mypy clean. Awaiting reviewer. |
| 2026-10-31 19:10 | reviewer | C06 CHANGES_REQUESTED — G1/G3/G4 pass; clean venv 36 passed, live stand verified (redis down -> 503, both down -> failed=["db","redis"], /health stays 200, no DSN in logs). G2 fails: check_redis/init_redis are never executed by tests. One test required; see docs/reviews/C06.md. |
| 2026-10-31 19:45 | implementer | C06 fix applied: test_ready_reports_real_unreachable_redis added (real init_redis/check_redis, port 1) — clean venv: 37 passed, ruff/mypy clean. Awaiting reviewer. |
| 2026-10-31 20:05 | reviewer | C06 ACCEPTED — 37 passed, ruff/mypy clean; mutation check confirms the new test fails when PING is broken, so it guards the real path. Awaiting owner sign-off. C07 not started. |
| 2026-10-31 20:30 | owner | start C07 infra.docker; reviewer to choose the worker/mock-crm approach. |
| 2026-10-31 20:35 | reviewer | C07 CONTRACTED — decisions: real Celery app + ping task (celery already allow-listed), worker healthcheck via `inspect ping`, beat via pidfile, minimal FastAPI mock-crm, root compose.yaml + infra/Dockerfile on python:3.13-slim. Awaiting implementer. |
| 2026-10-31 21:00 | owner | approved C01-C06; tracker set to ACCEPTED with owner sign-off. C07 continues. |
| 2026-10-31 21:40 | reviewer | C07 CHANGES_REQUESTED — build 0, up 21.3 s, 7/7 healthy, e2e ping -> pong, healthcheck negatives exit 1, down -v clean; G3/G4 pass. G1: Russian in compose.yaml and in the delivery note, hardcoded localhost fallback. G2: the `include=` registry line has no CI guard. See docs/reviews/C07.md. |
| 2026-10-31 22:10 | owner | remove the planning transcript and every old-project trace from the repository; keep a copy outside git. |
| 2026-10-31 22:40 | implementer | C07 fixes applied: English-only compose comments + full English review note; REDIS_URL via os.environ[] (no localhost fallback, loud startup failure); CI guard test for include=["app.workers.tasks"]; dropped worker->api / beat->worker edges; mock-crm image non-root; build/env x-anchors — clean venv: 39 passed, ruff/mypy clean; compose build/up --wait 60 -> 7/7 healthy, e2e ping -> pong, down -v clean. Awaiting reviewer. |
| 2026-10-31 23:15 | reviewer | C07 ACCEPTED - 39 passed, ruff/mypy clean (+ --warn-unused-ignores); missing REDIS_URL -> KeyError exit 1; mutation (remove include=) fails the registry guard, restore hash-identical; compose build 0, up 21.2 s -> 7/7 healthy; /health 200, /ready 200 {"db":true,"redis":true}, /metrics 200; e2e pong; uid 1000; worker healthcheck negative exit 1; down -v clean. Awaiting owner sign-off. C08 not started. |
| 2026-11-01 10:00 | owner | C07 sign-off -> ACCEPTED in docs/TRACKER.md. M0 remaining: C08, C09. |
| 2026-11-01 18:30 | owner | GitHub account BeeForest-dev created; repo github.com/BeeForest-dev/integro pushed (17 commits). |
| 2026-11-02 09:30 | reviewer | C08 ci.github-actions CONTRACTED - workflow ci.yml, checks job (ruff/mypy/pytest + PG16/Redis7 services) + docker compose build job; badge deferred to README (M6). Awaiting implementer. |
| 2026-11-02 15:20 | reviewer | C08 ACCEPTED - run 41442602755 on 480ab60 verified via API (success) + raw job log: ruff clean, mypy clean (15 files), 39 passed in 4.22s, postgres:16 + redis:7 created, docker compose build success. Awaiting owner sign-off. C09 not started. |
| 2026-11-02 15:35 | owner | C08 sign-off -> ACCEPTED in docs/TRACKER.md. M0 remaining: C09. |
| 2026-11-02 15:40 | reviewer | C09 api.request_context CONTRACTED - pure ASGI middleware, x-request-id, C02 contextvars binding with finally-cleanup, httpx.ASGITransport tests. Awaiting implementer. |
| 2026-11-02 17:10 | reviewer | C09 CHANGES_REQUESTED - code passes G1/G3/G4 and 45 tests green, but the context-cleanup test is a false green: mutation (finally body -> no-op) still passes it; assertion runs in the outer asyncio.run context, not the request's. One test rewrite required. See docs/reviews/C09.md. |
| 2026-11-02 12:15 | implementer | C08 GENERATED: .github/workflows/ci.yml (checks job with pg16+redis7 service containers, ruff/mypy --warn-unused-ignores/pytest; docker compose build job) - committed 480ab60 and pushed; real CI run #1 conclusion=success, both jobs green in 55 s (run 41442602755). Awaiting reviewer. |
| 2026-11-02 15:40 | implementer | C09 GENERATED: pure ASGI RequestContextMiddleware (reuse valid x-request-id / uuid4, structlog contextvars bind + finally clear, response echo), registered in create_app; 6 new tests - clean venv: 45 passed, ruff/mypy --warn-unused-ignores clean. Awaiting reviewer. |
| 2026-11-02 17:20 | implementer | C09 fix: test_context_cleared_after_request rewritten — request + assert in one coroutine (the old shape passed even with cleanup disabled); mutation self-check done (finally -> pass makes the test fail; restored; suite 45 passed, ruff/mypy clean). Awaiting reviewer. |
| 2026-11-02 17:50 | reviewer | C09 ACCEPTED after fix round - cleanup test rewritten to one coroutine; mutation re-run by reviewer fails the test as required; 45 passed, ruff/mypy clean; middleware untouched. Awaiting owner sign-off. M0 (Sprint 1) complete after sign-off. |
| 2026-11-02 18:10 | owner | start C10 models.organization (Sprint 2 / M1). C09 sign-off still pending. |
| 2026-11-02 19:30 | implementer | C10 GENERATED: Organization model (uuid pk, slug unique index, plan default, tz created_at), migration 0002_organizations (autogen, verified up/down/re-up on real PG16), repositories.create_organization with IntegrityError->AppError 409; 4 PG-backed tests - no skips (unset DATABASE_URL -> all 4 fail); suite 49 passed, ruff/mypy clean. Awaiting reviewer. |
| 2026-11-02 18:15 | reviewer | C10 CONTRACTED - Organization model (uuid pk, slug unique, plan, created_at), migration 0002 proven on real PG16, repositories layer starts (create_organization, 409 on duplicate slug), tests against real PostgreSQL (compose/CI service). Awaiting implementer. |
| 2026-11-06 14:00 | reviewer | C10 ACCEPTED - verified on real PG16 (standalone container): alembic up/down/re-up clean, full suite 49 passed, ruff/mypy clean; mutation (IntegrityError mapping removed) fails the duplicate-slug test. Housekeeping: compose postgres now publishes 5432 for local PG tests. Awaiting owner sign-off. C11 not started. |
| 2026-11-06 14:30 | owner | C09 and C10 sign-off -> ACCEPTED in docs/TRACKER.md. Sprint 1 fully signed off; Sprint 2 (M1) in progress with C10. |
| 2026-11-06 22:30 | implementer | C11 GENERATED per owner "делай 11" (no CONTRACTED block yet - same precedent as C02/C05): User + Membership models (StrEnum roles with value-persisting enum + @validates -> ValueError), migration 0003_users_memberships (autogen, up/down/re-up proven on compose PG16); 5 PG-backed tests, no skips - suite 54 passed, ruff/mypy clean. Awaiting reviewer. |
| 2026-11-07 00:10 | implementer | C11 fixes: migration 0004_membership_integrity (batch-mode, composite unique + role CHECK; sqlite C05 tests keep working), model __table_args__ mirrors both, 3 new tests incl. raw-SQL role guard; mutations re-verified (no CHECK -> raw test fails; no unique on fresh base->head schema -> duplicate test fails); suite 57 passed, ruff/mypy clean. Awaiting reviewer. |
| 2026-11-06 23:10 | reviewer | C11 CHANGES_REQUESTED - models/migration/tests solid (54 green, @validates mutation caught) but two integrity gaps verified: no composite unique on memberships(user_id, organization_id) and no DB-level role guard (CHECK missing; values_callable-removal mutation stays green). Required: new migration 0004 (unique pair + CHECK on role) + duplicate-pair IntegrityError test + raw-role-is-lowercase test. Q&A answered in docs/reviews/C11.md.
| 2026-11-06 23:40 | reviewer | C11 ACCEPTED after fix round - migration 0004 (composite unique + role CHECK, batch mode) with model-mirrored constraints; both mutations re-run by reviewer as full-loop rebuilds fail the new tests; 57 passed, ruff/mypy clean. Awaiting owner sign-off. C12 not started.
| 2026-11-06 23:55 | owner | C11 sign-off -> ACCEPTED in docs/TRACKER.md. Sprint 2 progress: C10, C11 done. |
| 2026-11-07 12:30 | implementer | C12 GENERATED per owner "давай с12": OrgScope choke point (equality-only scope validation, cross-tenant get -> None, ScopeError as generic 500); 8 PG-backed anti-leak tests incl. mutation-proven rejection tests - suite 65 passed, ruff/mypy clean. Awaiting reviewer. |
| 2026-11-07 16:00 | implementer | C12 fixes: adversarial hardening (non-Select -> ScopeError, OR-branches banned, single-entity FROM + pin ownership), docstring states the invariant precisely, 4 adversarial tests; mutations verified (no OR check -> OR test fails; no single-FROM -> two-entity test fails) - suite 69 passed, ruff/mypy clean. Awaiting reviewer. |
| 2026-11-07 12:00 | reviewer | C12 CHANGES_REQUESTED - adversarial probes found a real cross-tenant leak (OR-poison accepted, foreign row returned) and AttributeError instead of ScopeError for union/text(); honest-path tests mutation-proven. Three inspector hardenings + tests required. See docs/reviews/C12.md. |
