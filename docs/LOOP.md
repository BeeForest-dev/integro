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
ID:          C25
Name:        connectors.triggers.telegram
State:       ACCEPTED
Owner:       human
Implementer: kimi
Reviewer:    assistant
Awaiting:    owner
Contract:    see docs/CONTRACTS.md, section C25
Delivery:    docs/reviews/C25.md
Note:        Telegram ingress: secret-token header (isascii-first),
             two-layer dedupe (older-than-last guard + idempotency key),
             non-text updates ignored with structured log.
             ACCEPTED 2026-11-14: 231 passed; reviewer probes incl.
             raw-ASGI non-ASCII 401 and 9-request id-sequence; both
             mutations caught. Awaiting owner sign-off.
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
| 2026-11-07 12:40 | reviewer | C12 ACCEPTED after fix round - _assert_scoped enforces Select-only/no-OR/single-FROM/pin-belongs-to-entity; all four adversarial probes re-run by reviewer now reject with ScopeError; mutations on OR and single-FROM checks fail the new tests. 69 passed, ruff/mypy clean. Awaiting owner sign-off. C13 not started. |
| 2026-11-07 13:00 | owner | C12 sign-off -> ACCEPTED in docs/TRACKER.md. Anti-leak keystone signed off; Sprint 2 progress: C10, C11, C12 done. |
| 2026-11-07 18:30 | implementer | C13 GENERATED per owner "с13 продолжай": hash_password/verify_password (argon2id; malformed hash -> False; empty -> ValueError) + C11 standing requirement delivered (users.password_hash via migration 0005); 9 new tests, InvalidHash-mutation proven - suite 78 passed, ruff/mypy clean. Awaiting reviewer. |
| 2026-11-08 10:30 | implementer | C14 GENERATED (CONTRACTED block present - first module under the new rule-0): compact HS256 JWTs (fixed header, cryptography HMAC + compare_digest), issue_token_pair/verify_access/verify_refresh, typed TokenError/TokenExpired/TokenInvalid; 10 tests incl. strengthened alg=none fixture - suite 88 passed, ruff/mypy clean. Awaiting reviewer. |
| 2026-11-08 13:30 | implementer | C14 fix: UnicodeEncodeError on non-ASCII token segments -> TokenInvalid (upfront ASCII validation, raw bytes reused); 2 new unicode tests; mutation verified (guard removed -> both fail) - suite 90 passed, ruff/mypy clean. Awaiting reviewer. |
| 2026-11-07 18:00 | reviewer | C13 ACCEPTED - argon2id hash/verify with (VerificationError, InvalidHash) tuple (hierarchy fact verified), users.password_hash via migration 0005 (C11 standing requirement closed); mutations on both tuple elements fail dedicated tests; 78 passed, ruff/mypy clean. Awaiting owner sign-off. C14 not started. |
| 2026-11-07 18:15 | owner + reviewer | workflow rule agreed and written into AGENTS.md section 8: the only valid start signal is State: CONTRACTED in LOOP.md; owner chat messages do not override it; reviewer writes the CONTRACTED block before any module starts. |
| 2026-11-07 18:30 | owner | C13 sign-off -> ACCEPTED in docs/TRACKER.md. |
| 2026-11-07 18:35 | reviewer | C14 services.auth.tokens CONTRACTED per the new workflow rule: HS256 compact JWT via cryptography (allow-listed, PyJWT rejected as not allow-listed), explicit secret param, typed TokenExpired/TokenInvalid. Awaiting implementer. |
| 2026-11-07 19:30 | reviewer | C14 CHANGES_REQUESTED - core verified (fixed header, compare_digest before parsing, typed errors, 88 passed, typ/exp mutations caught) but a unicode token escapes as UnicodeEncodeError instead of TokenInvalid (live probe). One fix + test required. See docs/reviews/C14.md. |
| 2026-11-07 20:30 | reviewer | C14 ACCEPTED after fix round - all three unicode segments (token/payload/signature) raise TokenInvalid; mutation on the ASCII guard fails both new tests; 90 passed, ruff/mypy clean. Awaiting owner sign-off. C15 not started. |
| 2026-11-07 21:00 | owner | C14 sign-off -> ACCEPTED in docs/TRACKER.md. |
| 2026-11-08 12:00 | implementer | C15 GENERATED: /auth register/login/refresh/me (httpOnly cookie rotation, byte-identical 401, 409 via C10 pattern, OrgScope role in /me), services registration+login+audit, repositories users+memberships, migration 0006_audit_log; 12 PG-backed scenarios, all three required mutations verified - suite 102 passed, ruff/mypy clean. Awaiting reviewer. |
| 2026-11-08 12:45 | implementer | C15 post-push CI catch: run #31 failed (auth tests assumed prior migration side effects; CI runs tests/api first on an empty DB) -> fixture now brings schema to head; proven on a freshly recreated database (12/12 standalone); run #32 green. |
| 2026-11-08 15:30 | implementer | C15 fix: /auth/refresh checks membership through OrgScope (403 after revocation); new test deletes the membership row and expects 403; mutation verified (check removed -> test fails) - suite 103 passed, ruff/mypy clean. Awaiting reviewer. |
| 2026-11-07 21:05 | reviewer | C15 api.auth CONTRACTED per workflow rule: 4 endpoints, httpOnly refresh cookie with rotation, generic 401 (probe-safe), services orchestrate (registration/login/audit minimal, C19 extends), migration 0006_audit_log, PG-backed endpoint tests. Awaiting implementer. |
| 2026-11-07 22:30 | reviewer | C15 CHANGES_REQUESTED - endpoints/audit/cookie verified (102 passed, 3 mutations caught, live probes leak-free) but /auth/refresh skips the membership check: a revoked user still rotates tokens (reviewer probe, 200). One fix + test required. See docs/reviews/C15.md. |
| 2026-11-07 23:00 | reviewer | C15 ACCEPTED after fix round - /auth/refresh verifies membership through OrgScope before rotating; reviewer revocation probe -> 403; mutation on the check fails the new test; 103 passed, ruff/mypy clean. Awaiting owner sign-off. C16 not started. |
| 2026-11-07 23:15 | owner | C15 sign-off -> ACCEPTED in docs/TRACKER.md. |
| 2026-11-07 23:20 | reviewer | C16 api.rbac CONTRACTED per workflow rule: security.py with get_current_claims/get_current_membership/require_roles, explicit allowed-set, 403 semantics per contract (membership->403 not 404, insufficient role->403 with required roles), C15 untouched. Awaiting implementer. |
| 2026-11-08 19:00 | implementer | C16 GENERATED: api/security.py (claims 401 generic, membership via OrgScope 403-not-404, require_roles explicit set with roles in detail); 6 PG-backed tests on scratch app, both mutations verified - suite 109 passed, ruff/mypy clean. Awaiting reviewer. |
| 2026-11-08 21:30 | implementer | C17 GENERATED: core/crypto.py (Fernet, HKDF-derived key from SECRET_KEY, CryptoError single failure type, empty->empty both ways); 10 tests, both mutations verified - suite 119 passed, ruff/mypy clean. Awaiting reviewer. |
| 2026-11-09 00:30 | implementer | C18 GENERATED: Connection model (JSONB config, encrypted secret at rest, SUPPORTED_TYPES) + migration 0007, OrgScope-first repositories/connections (secret_error state + self-heal, to_api_dict leak-free); 8 PG-backed tests, both mutations verified; leftover-rows FK trap found and fixed (clean before+after) - suite 127 passed on fresh DB, ruff/mypy clean. Awaiting reviewer. |
| 2026-11-09 11:30 | implementer | C19 GENERATED: migration 0008 (entity/entity_id/before/after/ip), full record_audit + failure-isolated try_record_audit (SAVEPOINT + payload-free audit_write_failed log), C15 call sites switched; 4 PG-backed tests, both mutations verified - suite 131 passed on fresh DB, ruff/mypy clean. Sprint 2 (M1) complete. Awaiting reviewer. |
| 2026-11-09 14:30 | implementer | C20 GENERATED: Flow/FlowVersion models + migration 0009 (unique(flow_id,version), no current FK), pydantic FlowDefinition validated against SUPPORTED_TYPES, OrgScope-first repositories/flows with pre-insert 422 validation ("json-path: message"); 9 PG-backed tests, both mutations verified (schema mutation via fresh rebuild) - suite 140 passed on fresh DB, ruff/mypy clean. Awaiting reviewer. |
| 2026-11-09 17:30 | implementer | C21 GENERATED: services/conditions (stdlib-only condition tree, explicit operator registry, never-raising evaluation with failed_paths, strict validate_conditions), FlowDefinition gains optional validated conditions (the one allowed C20 touch); 30 new tests, both mutations verified - suite 169 passed on fresh DB, ruff/mypy clean. Awaiting reviewer. |
| 2026-11-12 15:00 | implementer | C22 GENERATED (scope: events storage of C23 delivered here): Event model + migration 0010 (unique(org, idempotency_key)), store_event dedupe, POST /hooks/{id} with raw-body HMAC (compare_digest, uniform 404, lazy celery seam, process_event placeholder); 12 PG-backed tests, both mutations verified; facts: celery 5.6 send_task ignores always_eager, compare_digest-vs-!= is timing-only - suite 181 passed on fresh DB, ruff/mypy clean. Awaiting reviewer. |
| 2026-11-14 11:00 | implementer | C22 fix: non-ASCII presented signature -> 401 before compare_digest (TypeError -> 500 otherwise); new raw-ASGI test (httpx refuses such headers); mutation verified (guard removed -> test fails) - suite 182 passed on fresh DB, ruff/mypy clean. Awaiting reviewer. |
| 2026-11-07 23:50 | reviewer | C16 ACCEPTED - security.py per contract; reviewer live probes incl. cross-org role resolution (token org B viewer -> 403 with required roles); mutations on role-check and membership-None branch fail dedicated tests; 109 passed, ruff/mypy clean; C15 untouched. Awaiting owner sign-off. C17 not started. |
| 2026-11-08 00:05 | owner | C16 sign-off -> ACCEPTED in docs/TRACKER.md. |
| 2026-11-08 00:10 | reviewer | C17 core.crypto CONTRACTED per workflow rule: Fernet with HKDF-derived key from SECRET_KEY (no second env var), typed CryptoError, empty->empty both directions, no new dependencies. Awaiting implementer. |
| 2026-11-08 00:40 | reviewer | C17 ACCEPTED - Fernet/HKDF crypto verified: reviewer probes (wrong/empty key, tampering x4 offsets, truncation, garbage) all fail closed as CryptoError; mutations on empty short-circuit and except-tuple caught; 119 passed, ruff/mypy clean. Awaiting owner sign-off. C18 not started. |
| 2026-11-08 01:00 | owner | C17 sign-off -> ACCEPTED in docs/TRACKER.md. |
| 2026-11-08 01:05 | reviewer | C18 models.connection + repositories.connections CONTRACTED per workflow rule: Connection model + 0007 migration, OrgScope-first CRUD, C17 encryption at rest, secret_error marking with self-heal, to_api_dict never leaks secrets, 4 supported types. Awaiting implementer. |
| 2026-11-08 01:40 | reviewer | C18 ACCEPTED - connections verified: at-rest Fernet, tenant isolation via OrgScope, to_api_dict leak-free, secret_error marking + self-heal; mutations on type validation and secret_error marking caught; 127 passed, ruff/mypy clean. Awaiting owner sign-off. C19 not started. |
| 2026-11-08 02:00 | owner | C18 sign-off -> ACCEPTED in docs/TRACKER.md. |
| 2026-11-08 02:05 | reviewer | C19 services.audit CONTRACTED per workflow rule: migration 0008 (entity/entity_id/before/after/ip), record_audit extended + try_record_audit with SAVEPOINT isolation, no-payload logging rule, C15 two call sites switch to the safe variant. Awaiting implementer. |
| 2026-11-08 02:40 | reviewer | C19 ACCEPTED - full audit shape with SAVEPOINT isolation verified (reviewer FK-failure probe: None + caller survives + identifier-only log); both mutations caught; 131 passed, ruff/mypy clean. Sprint 2 (M1) complete after owner sign-off. C20 awaits owner command through the reviewer (workflow rule). |
| 2026-11-08 03:00 | owner | C19 sign-off -> ACCEPTED in docs/TRACKER.md. Sprint 2 (M1) fully signed off. |
| 2026-11-08 03:05 | reviewer | C20 models.flow CONTRACTED per workflow rule: Flow + FlowVersion (0009), pydantic definition schema validated in the repository (422 with exact path, SUPPORTED_TYPES from C18 as the single registry), OrgScope-first versioning CRUD, no new deps. Sprint 3 (M2) begins. Awaiting implementer. |
| 2026-11-08 03:40 | reviewer | C20 ACCEPTED - versioned flows verified: exact 422 paths (trigger / trigger.type / actions.0.type with supported lists), tenant isolation on flow + version history, monotonic versioning; mutations on validation bypass and unique(flow_id, version) via full schema rebuild caught; 140 passed, ruff/mypy clean. Awaiting owner sign-off. C21 not started. |
| 2026-11-08 04:00 | owner | C20 sign-off -> ACCEPTED in docs/TRACKER.md. |
| 2026-11-08 04:05 | reviewer | C21 services.conditions CONTRACTED per workflow rule: stdlib-only condition tree (all/any + operator registry, no eval), validate at save time wired into the C20 FlowDefinition as the one allowed touch, runtime never raises. Awaiting implementer. |
| 2026-11-08 04:40 | reviewer | C21 ACCEPTED - conditions engine verified: 20+ reviewer probes (truth tables, None-vs-absent, injection-shaped field names inert, runtime never raises, save-time 422 through C20); mutations on operator registry and missing-field handling caught; 169 passed, ruff/mypy clean. Awaiting owner sign-off. C22 not started. |
| 2026-11-12 10:00 | owner | C21 sign-off -> ACCEPTED in docs/TRACKER.md. Resuming after the pause discussed 2026-11-08. |
| 2026-11-12 10:05 | reviewer | C22 connectors.triggers.webhook CONTRACTED per workflow rule: scope includes the events storage layer (C23 content - will be closed as delivered here), HMAC-signed public ingress at POST /hooks/{connection_id}, idempotency via unique(org, key), placeholder worker task. Awaiting implementer. |
| 2026-11-14 12:00 | reviewer | C22 CHANGES_REQUESTED - ingress verified end-to-end (HMAC/tamper/404/400/idempotency all green; dedupe mutation caught) except one hole: non-ASCII signature header -> TypeError -> 500 instead of 401 (raw-ASGI probe). One guard + one raw-ASGI test required. See docs/reviews/C22.md. |
| 2026-11-14 13:00 | reviewer | C22 ACCEPTED after fix round - isascii guard verified by raw-ASGI probe (401), guard mutation caught; 182 passed. C23 closed as ACCEPTED-by-delivery inside C22 (docs/reviews/C23.md). Awaiting owner sign-off for both. C24 not started. |
| 2026-11-14 14:00 | owner | C22 and C23 sign-off -> ACCEPTED in docs/TRACKER.md. |
| 2026-11-14 19:30 | implementer | C24 GENERATED: SUPPORTED_TYPES += schedule + save-time Trigger.config validation (exactly one of every_seconds/cron), stdlib 5-field cron parser + next_slot, Flow.next_run_at (migration 0011), beat tick every 60 s (shared_task + conf entry) with advance-first, slot-keyed exactly-once events and one-shot catch-up; 38 new tests, both mutations verified (slot-key test refined: same-slot keys collide with or without the slot, so the detector uses successive slots) - suite 220 passed on fresh DB, ruff/mypy clean. Awaiting reviewer. |
| 2026-11-15 00:30 | implementer | C25 GENERATED: POST /hooks/telegram/{id} (secret-token header with isascii guard + compare_digest, uniform 404, two-layer dedupe via C22 index + config.last_update_id, non-text ignored with telegram_update_ignored log, lazy _enqueue seam); 11 PG-backed tests, both mutations verified - suite 231 passed on fresh DB, ruff/mypy clean. Awaiting reviewer. |
| 2026-11-14 14:05 | reviewer | C24 connectors.triggers.cron CONTRACTED per workflow rule: type "schedule" added to the registry, stdlib 5-field cron parser, 60s beat tick task with exactly-once slot idempotency and one-catch-up semantics, migration 0011 (flows.next_run_at). Four documented accepted-module touches. Awaiting implementer. |
| 2026-11-14 15:00 | reviewer | C24 ACCEPTED - schedule trigger verified: parser table + slot boundaries + tick semantics (catch-up once, double-tick once, disabled skip); mutations on catch-up base and slot-in-key caught; 220 passed, ruff/mypy clean. Awaiting owner sign-off. C25 not started. |
| 2026-11-14 15:30 | owner | C24 sign-off -> ACCEPTED in docs/TRACKER.md. |
| 2026-11-14 15:35 | reviewer | C25 connectors.triggers.telegram CONTRACTED per workflow rule: public ingress guarded by secret-token header (isascii-first), two-layer dedupe (idempotency key + older-than-last guard), non-text updates ignored with log. Awaiting implementer. |
| 2026-11-14 16:00 | reviewer | C25 ACCEPTED - telegram ingress verified: secret-token auth (raw-ASGI non-ASCII -> 401), two-layer dedupe, non-text ignored with log; exactly 2 events/2 enqueues over 9 probe requests; both mutations caught; 231 passed, ruff/mypy clean. Awaiting owner sign-off. C26 not started. |
