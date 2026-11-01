# Contract registry — `integro` (folder: `spidoznye_kozyvki2`)

Every module is implemented from a contract. A contract is written **by the owner** in 3 lines
and must be restatable out loud before generation starts.

Format:
```
Purpose:    one sentence
In -> Out:  concrete types
Errors:     every failure case and the behaviour for each
Side fx:    tables touched / external calls
Deps:       allowed imports
```

Status legend: `TODO` -> `CONTRACTED` -> `GENERATED` -> `G1` -> `G2` -> `G3` -> `G4` -> `ACCEPTED`

---

## M0 — Foundation (exit: compose up works, CI green)

### C01 `core.config`
```
Purpose:    load and validate application settings from environment.
In -> Out:  Settings object (immutable) from env + .env file.
Errors:     missing required var -> app refuses to start with a named error;
            invalid type (e.g. DATABASE_URL="foo") -> validation error naming the field.
Side fx:    reads env / .env only.
Deps:       pydantic-settings.
```

### C02 `core.logging`
```
Purpose:    configure structured JSON logging with request/correlation id.
In -> Out:  configured stdlib logger + helper to bind correlation id.
Errors:     never raises; falls back to plain logging if setup fails.
Side fx:    writes to stdout.
Deps:       structlog, stdlib logging.
```

### C03 `core.errors`
```
Purpose:    unified exception -> RFC 7807 problem-details response.
In -> Out:  JSON {type,title,status,detail,instance,errors[]}.
Errors:     domain error -> mapped status; unknown error -> 500 with generic text,
            internal detail only in logs, never in the response body.
Side fx:    none.
Deps:       fastapi.
```

### C04 `db.engine`
```
Purpose:    async SQLAlchemy engine + session factory.
In -> Out:  AsyncSession via dependency injection.
Errors:     DB unreachable -> connection error surfaces as 503, not 500.
Side fx:    opens a pool to PostgreSQL.
Deps:       sqlalchemy[asyncio], asyncpg.
```

### C05 `db.base` + `db.migrations`
```
Purpose:    declarative base + Alembic wired to the same metadata.
In -> Out:  `alembic upgrade head` produces the schema; `alembic revision --autogenerate`
            produces a reviewable diff.
Errors:     migration conflict -> non-zero exit with the conflicting revision id.
Side fx:    creates/alters tables in PostgreSQL.
Deps:       sqlalchemy, alembic.
```

### C06 `api.health`
```
Purpose:    liveness/readiness/metrics endpoints for containers and monitoring.
In -> Out:  GET /health  -> 200 {"status":"ok"} (liveness, no deps)
            GET /ready   -> 200 {"db":true,"redis":true} / 503 (checks deps)
            GET /metrics -> Prometheus text format
Errors:     dependency down -> /ready returns 503 with the failing dependency name.
Side fx:    reads DB + Redis.
Deps:       fastapi, prometheus_client, redis.
Note:       also creates app/main.py (create_app + lifespan wiring for the engine
            and the Redis client). No other endpoints in this contract.
```

### C07 `infra.docker`
```
Purpose:    multi-stage Dockerfile + compose for api, worker, beat, postgres, redis,
            mock-crm, mailpit.
In -> Out:  `docker compose up` -> 7 healthy services within 60 s.
Errors:     image build fails -> build log shows the failing step.
Side fx:    creates volumes for postgres data.
Deps:       docker only (no python deps added).
```

### C08 `ci.github-actions`
```
Purpose:    CI pipeline: ruff -> mypy -> pytest -> docker build.
In -> Out:  green/red badge + PR status check.
Errors:     test failure -> step fails with the failing test name in the log.
Side fx:    uses postgres + redis service containers for integration tests.
Deps:       github actions only.
```

### C09 `api.request_context`
```
Purpose:    middleware that assigns a correlation id to every request/response.
In -> Out:  request carries `x-request-id`; response echoes it; log lines include it.
Errors:     incoming id that is not a valid uuid -> generate a new one.
Side fx:    writes to the log context.
Deps:       fastapi, structlog.
```

---

## M1 — Tenancy, auth, connections (exit: tenant isolation proven by test)

### C10 `models.organization`
```
Purpose:    org (tenant) row: id, name, slug, plan, created_at.
In -> Out:  persisted row, id uuid.
Errors:     duplicate slug -> unique violation mapped to 409.
Side fx:    table `organizations`.
Deps:       sqlalchemy.
```

### C11 `models.user` + `models.membership`
```
Purpose:    user row + membership linking a user to an org with a role.
In -> Out:  persisted rows; role in {owner, admin, member, viewer}.
Errors:     role not in the enum -> validation error.
Side fx:    tables `users`, `memberships`.
Deps:       sqlalchemy.
```

### C12 `repositories.org_scope`
```
Purpose:    single choke point that adds `organization_id` to every query.
In -> Out:  repository methods that never accept an org id from the caller.
Errors:     query without org scope -> raises `ScopeError` (never returns cross-tenant rows).
Side fx:    none beyond reads.
Deps:       sqlalchemy.
```
> This module is the anti-leak mechanism. It gets the most review attention.

### C13 `services.auth.password`
```
Purpose:    hash and verify passwords.
In -> Out:  argon2 hash string / boolean.
Errors:     invalid hash -> False, no exception; empty password -> validation error.
Side fx:    none.
Deps:       argon2-cffi.
```

### C14 `services.auth.tokens`
```
Purpose:    issue and verify access + refresh JWTs.
In -> Out:  signed token pair / decoded claims.
Errors:     expired -> typed `TokenExpired`; bad signature -> `TokenInvalid`;
            wrong audience/issuer -> `TokenInvalid`.
Side fx:    none. Secret from env.
Deps:       fastapi (jwt), core.config.
```

### C15 `api.auth`
```
Purpose:    register, login, refresh, me.
In -> Out:  JSON with tokens and user profile; sets an httpOnly refresh cookie.
Errors:     wrong credentials -> 401 generic message (no "user exists" leak);
            duplicate email -> 409.
Side fx:    inserts user + membership; writes an audit record.
Deps:       services.auth, repositories.
```

### C16 `api.rbac`
```
Purpose:    role-based access dependency for routes.
In -> Out:  allowed request or 403.
Errors:     missing membership -> 403 (not 404, to avoid existence probing);
            insufficient role -> 403 with the required role in the detail.
Side fx:    none.
Deps:       fastapi, services.auth.
```

### C17 `core.crypto`
```
Purpose:    encrypt/decrypt connection secrets at rest.
In -> Out:  ciphertext token / plaintext secret.
Errors:     wrong key -> typed error, never returns partial plaintext;
            empty input -> empty output.
Side fx:    none. Key from env (Fernet).
Deps:       cryptography.
```

### C18 `models.connection` + `repositories.connections`
```
Purpose:    CRUD for integration connections (type, config JSONB, encrypted secrets, status).
In -> Out:  connection row; secrets are never returned by the API, only `has_secret: true`.
Errors:     unknown type -> validation error with the list of supported types;
            decryption failure on read -> connection marked `secret_error`, not a 500.
Side fx:    table `connections`.
Deps:       core.crypto, repositories.
```

### C19 `services.audit`
```
Purpose:    record who changed what, when, from where.
In -> Out:  audit row (actor, org, action, entity, before/after diff, ip, ts).
Errors:     audit write failure must not break the business operation -> log error, continue.
Side fx:    table `audit_log`.
Deps:       models, repositories.
```

---

## M2 — Flows, triggers, first end-to-end run (exit: webhook -> recorded run)

### C20 `models.flow`
```
Purpose:    flow row + versioned JSON definition + enabled flag.
In -> Out:  persisted flow; definition validated against the JSON schema before write.
Errors:     definition fails schema -> 422 with the exact path that failed;
            unknown trigger/action type -> 422 listing supported types.
Side fx:    tables `flows`, `flow_versions`.
Deps:       models, schemas.
```

### C21 `services.conditions`
```
Purpose:    evaluate a JSON condition tree against an event payload.
In -> Out:  boolean + list of failed clause paths (for the UI).
Errors:     unknown operator -> validation error at save time, never at runtime;
            missing field in payload -> condition evaluates False, not an exception.
Side fx:    none. NO `eval()` — explicit operator registry only.
Deps:       stdlib only.
```

### C22 `connectors.triggers.webhook`
```
Purpose:    accept an inbound event via HTTP and normalise it.
In -> Out:  Event(id, org, type, payload, received_at).
Errors:     bad HMAC signature -> 401; unknown/inactive token -> 404;
            malformed JSON -> 400 with the offending field.
Side fx:    inserts `events`; enqueues a run.
Deps:      fastapi, services.events.
```

### C23 `services.events`
```
Purpose:    store inbound events with an idempotency key.
In -> Out:  event row; duplicate key -> returns the existing event with `duplicate=True`.
Errors:     duplicate -> no second run is created.
Side fx:    table `events`, unique index on (org, idempotency_key).
Deps:       models, repositories.
```

### C24 `connectors.triggers.cron`
```
Purpose:    scheduled trigger firing a flow on an interval or cron expression.
In -> Out:  event payload with the schedule and the previous run timestamp.
Errors:     invalid cron -> validation error when the flow is saved;
            missed schedule (worker down) -> one catch-up run, not N.
Side fx:    uses celery beat.
Deps:       celery.
```

### C25 `connectors.triggers.telegram`
```
Purpose:    receive bot updates and normalise them into events.
In -> Out:  Event with type telegram.message, chat id, text, user id.
Errors:     wrong secret token header -> 401; update older than the last processed
            update_id -> ignored (no duplicate event); non-text message -> ignored with a log.
Side fx:    inserts `events`, enqueues a run.
Deps:       fastapi, httpx.
```

### C26 `connectors.triggers.imap`
```
Purpose:    poll (or IDLE on) a mailbox and normalise new messages into events.
In -> Out:  Event per new message; cursor per mailbox.
Errors:     IMAP auth failure -> connection marked `auth_failed`, no retry storm;
            network timeout -> backoff and retry; broken connection -> reconnect once, then give up.
Side fx:    reads the mailbox only. Cursor persisted.
Deps:       imaplib (stdlib), ssl.
```
> The owner already owns a working IMAP implementation — reuse it, keep the tests.

### C27 `connectors.actions.http`
```
Purpose:    call an external HTTP API with auth, timeout and retries.
In -> Out:  response status, headers, body (truncated to 64 KB), duration.
Errors:     timeout -> typed error, retried; 5xx -> retried; 4xx -> NOT retried (permanent);
            invalid JSON body -> permanent error.
Side fx:    one outbound HTTP call.
Deps:       httpx, tenacity.
```

### C28 `connectors.actions.table`
```
Purpose:    write a row into a table-like connector (a stand-in for Sheets/Sheets-API).
In -> Out:  created row id + the stored row.
Errors:     missing required column -> permanent error naming the column;
            duplicate on the unique key -> upsert, not an error.
Side fx:    table `connector_rows` (or an external call).
Deps:       models, repositories.
```

### C29 `connectors.actions.crm`
```
Purpose:    create/update a deal in a CRM via its HTTP API.
In -> Out:  external deal id, stored on the run step.
Errors:     404 on CRM -> permanent; 5xx/timeout -> retried; auth error -> permanent + connection flagged.
Side fx:    one outbound HTTP call to the CRM.
Deps:       httpx, tenacity.
```

### C30 `connectors.notifiers` (base) + `notifiers.slack` / `.telegram` / `.email` / `.webhook`
```
Purpose:    deliver a notification through one of four interchangeable channels.
In -> Out:  Delivery record (id, channel, target, status, provider_message_id, error).
Errors:     channel misconfigured -> permanent; provider 5xx/timeout -> retried;
            rate limited (429) -> retried after the provider's Retry-After.
Side fx:    one outbound call (or SMTP send) + `deliveries` table.
Deps:       httpx, tenacity, smtplib.
```
> Four separate contracts, one common `Notifier` protocol. No channel-specific logic in flows.

---

## M3 — Engine and reliability (exit: DLQ + replay, no duplicates)

### C31 `workers.dispatcher`
```
Purpose:    turn a stored event into a run and enqueue the execution task.
In -> Out:  run id + enqueued task id.
Errors:     enqueue failure -> event stays `pending`, retried by the scheduler;
            duplicate event -> no second run.
Side fx:    inserts `runs`, publishes to celery.
Deps:       celery, models.
```

### C32 `workers.executor`
```
Purpose:    execute a run: evaluate conditions, run actions in order, record every step.
In -> Out:  final run status {succeeded, failed, partial} + list of step results.
Errors:     permanent action error -> run status failed, remaining steps skipped;
            transient error -> handled by the retry policy of that step;
            exception in the executor itself -> run marked `crashed` with the traceback in logs.
Side fx:    inserts/updates `runs`, `run_steps`.
Deps:       services, connectors.
```

### C33 `services.retry`
```
Purpose:    one retry policy for every outbound action.
In -> Out:  result after N attempts with exponential backoff and full jitter.
Errors:     attempts exhausted -> typed `RetryExhausted` carrying the last error.
Side fx:    none.
Deps:       tenacity.
```

### C34 `services.idempotency`
```
Purpose:    guarantee that one event produces at most one effect per step.
In -> Out:  boolean `executed` + the stored result of a previous execution.
Errors:     concurrent execution -> second caller gets `skipped(already_done)`.
Side fx:    table `idempotency_keys`, unique on (org, event_id, step_key).
Deps:       models, repositories.
```

### C35 `services.dead_letter`
```
Purpose:    collect permanently failed runs and allow a manual replay.
In -> Out:  DLQ listing + replay result.
Errors:     replay of a non-DLQ run -> 409; replay while the original is still running -> 409.
Side fx:    table `dead_letters`; replay creates a new run linked to the original.
Deps:       models, repositories, workers.
```

### C36 `services.rate_limit`
```
Purpose:    limit outbound calls per connection (token bucket in Redis).
In -> Out:  decision {allowed, retry_after}.
Errors:     Redis down -> fail open (allow) and log a warning, never block the pipeline.
Side fx:    Redis counters.
Deps:       redis.
```

### C37 `services.circuit_breaker`
```
Purpose:    stop hammering a failing endpoint; probe recovery after a cooldown.
In -> Out:  decision {closed, open, half_open} per endpoint key.
Errors:     never raises; defaults to closed (allow) when state is unknown.
Side fx:    Redis state.
Deps:       redis.
```

---

## M4 — Connectors, mock services, frontend (exit: full scenario through the UI)

### C38 `mock_crm` (separate service)
```
Purpose:    a tiny CRM API used as the demo integration target.
In -> Out:  REST: POST /leads, GET /leads, POST /deals, GET /deals/{id}; data in memory + seed file.
Errors:     unknown lead -> 404; validation -> 422; data persists across restarts via a seed file.
Side fx:    stores demo leads/deals.
Deps:       fastapi. Independent repo/dir, no dependency on the main app.
```
> Labelled in the UI as a demo component. Its purpose: prove real HTTP integration between two services.

### C39 `connectors.protocols`
```
Purpose:    define the Trigger / Action / Notifier protocols the engine talks to.
In -> Out:  typing.Protocol definitions + a registry mapping type name -> implementation.
Errors:     unknown type at lookup -> `UnknownConnector` listing the registered names.
Side fx:    none.
Deps:       stdlib typing.
```

### C40 `frontend.app_shell`
```
Purpose:    app shell: layout, navigation, auth guard, API client with token refresh.
In -> Out:  SPA with protected routes; 401 -> redirect to login.
Errors:     token refresh failure -> redirect to login and clear the store;
            API unreachable -> toast with a retry button.
Side fx:    stores the access token in memory, refresh token in an httpOnly cookie.
Deps:       react, react-router, tanstack-query.
```

### C41 `frontend.connections`
```
Purpose:    list and edit connections, test a connection.
In -> Out:  form with type-specific fields; "Test" runs a real check against the target.
Errors:     test failure -> inline error with the provider message; secrets never pre-filled.
Side fx:    calls the API.
Deps:       frontend stack.
```

### C42 `frontend.flow_editor`
```
Purpose:    create and edit a flow: trigger, conditions, actions — as a form, not a canvas.
In -> Out:  flow JSON saved to the API; validation errors mapped to the right field.
Errors:     server validation error -> inline per-field messages.
Side fx:    calls the API.
Deps:       frontend stack.
```

### C43 `frontend.run_history`
```
Purpose:    list runs, open a run, inspect every step with status, timing, error, payloads.
In -> Out:  paginated list + detail with a step timeline.
Errors:     run not found -> 404 view; step payload too large -> truncated with a "show more".
Side fx:    calls the API.
Deps:       frontend stack.
```

### C44 `frontend.dlq` + `frontend.notifications` + `frontend.audit`
```
Purpose:    DLQ with a replay button, in-app notification feed, audit log view.
In -> Out:  list views; replay triggers a new run and shows its result.
Errors:     replay conflict (409) -> inline message explaining the run is still active.
Side fx:    calls the API.
Deps:       frontend stack.
```

### C45 `frontend.demo_panel`
```
Purpose:    a "Send test event" button + demo mode switch, so a reviewer can reproduce
            the whole pipeline without any external account.
In -> Out:  one click -> event -> run -> steps -> notifications visible.
Errors:     demo mode off -> the button is hidden; failures surface in the run view.
Side fx:    calls the API.
Deps:       frontend stack.
```

---

## M5 — Production hardening (exit: `make demo` works from a clean clone)

### C46 `api.metrics`
```
Purpose:    expose business metrics: runs by status, step latency, queue depth, retry count.
In -> Out:  Prometheus exposition.
Errors:     never raises.
Side fx:    reads counters.
Deps:       prometheus_client.
```

### C47 `scripts.seed`
```
Purpose:    create a realistic demo dataset: 1 org, 2 users, 4 connections,
            3 flows, 40 runs with mixed statuses, 2 DLQ entries, notifications.
In -> Out:  idempotent seed (safe to run twice).
Errors:     duplicate -> skipped, not failed.
Side fx:    inserts demo rows; uses only fake data.
Deps:       stdlib + app models.
```

### C48 `tests.integration`
```
Purpose:    integration suite over the real DB and a mock provider.
In -> Out:  green suite covering: tenant isolation, full flow run, retry->DLQ->replay,
            duplicate event -> single effect, webhook with bad signature -> 401.
Errors:     container not ready -> the suite waits, then fails loudly (no silent skip).
Side fx:    uses a separate test database.
Deps:       pytest, httpx, respx.
```

### C49 `tests.load`
```
Purpose:    load scenario: N parallel webhook calls, measure p95 latency.
In -> Out:  report with p50/p95 and error rate.
Errors:     failure -> non-zero exit (blocks CI on the main branch).
Side fx:    hits the running stack.
Deps:       locust (dev dependency, allowed via explicit approval).
```

### C50 `docs`
```
Purpose:    README (English), architecture doc with diagrams, ADRs, demo script, screenshots.
In -> Out:  docs that a stranger can follow to run the project in 60 seconds.
Errors:     n/a.
Side fx:    none.
Deps:       none (human-written, AI-assisted).
```

---

## M6 — Sales layer (exit: one inbound reply, one call booked)

### C51 `docs.use_cases`
```
Purpose:    map each capability to a real client request, effort and price.
In -> Out:  table: "client asks X -> I deliver Y -> N hours -> $Z -> evidence link".
Errors:     n/a.
Side fx:    none.
```

### C52 `docs.services`
```
Purpose:    three fixed-scope offers with price, deliverable list and timeline.
In -> Out:  offers a client can accept as-is.
Errors:     n/a.
Side fx:    none.
```

### C53 `landing`
```
Purpose:    one-page site: who I am, what I automate, three cases, demo video, contact.
In -> Out:  static site deployed to a free host, linked from every profile.
Errors:     n/a.
Side fx:    none.
```

### C54 `sales.outreach`
```
Purpose:    tracker of 50 target agencies/companies + 3 message templates + status column.
In -> Out:  a filled tracker and a repeatable 5-messages-per-week routine.
Errors:     n/a.
Side fx:    none.
```
