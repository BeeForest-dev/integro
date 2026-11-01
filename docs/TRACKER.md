# Tracker — `integro` (folder: `spidoznye_kozyvki2`)

Status flow: `TODO` -> `CONTRACTED` -> `GENERATED` -> `G1` -> `G2` -> `G3` -> `G4` -> `ACCEPTED`

A module reaches `ACCEPTED` only when all four gates pass and the owner can explain it.
Update this file **daily** (5 minutes) — it is the only progress source that counts.

---

## Sprint 1 — M0 Foundation (target: 3–4 days at 20–30 h/week)

| ID | Contract | Status | G1 | G2 | G3 | G4 | Notes / why it was rejected |
|---|---|---|---|---|---|---|---|
| C01 | core.config | ACCEPTED | ✓ | ✓ | ✓ | ✓ | Reviewer verdict ACCEPTED (docs/reviews/C01.md); owner sign-off 2026-10-31. 7 tests. |
| C02 | core.logging | ACCEPTED | ✓ | ✓ | ✓ | ✓ | Reviewer verdict ACCEPTED (docs/reviews/C02.md); owner sign-off 2026-10-31. 4 tests. |
| C03 | core.errors | ACCEPTED | ✓ | ✓ | ✓ | ✓ | Reviewer verdict ACCEPTED (docs/reviews/C03.md); owner sign-off 2026-10-31. 6 tests. |
| C04 | db.engine | ACCEPTED | ✓ | ✓ | ✓ | ✓ | Reviewer verdict ACCEPTED (docs/reviews/C04.md); owner sign-off 2026-10-31. Clean venv: 28 passed, ruff/mypy clean; 503 proven via httpx.ASGITransport. |
| C05 | db.base + migrations | ACCEPTED | ✓ | ✓ | ✓ | ✓ | Reviewer verdict ACCEPTED (docs/reviews/C05.md); owner sign-off 2026-10-31. Real PG16: upgrade head -> 0001_baseline (head); duplicate-revision-id conflict test added; ruff/mypy clean. |
| C06 | api.health | ACCEPTED | ✓ | ✓ | ✓ | ✓ | Reviewer verdict ACCEPTED (docs/reviews/C06.md); owner sign-off 2026-10-31. 37 passed; live stand: /ready 200, redis down -> 503 failed=["redis"], both down -> failed=["db","redis"], /health stays 200. Mutation check proves the Redis test guards the real PING path. |
| C07 | infra.docker | TODO | | | | | |
| C08 | ci.github-actions | TODO | | | | | |
| C09 | api.request_context | TODO | | | | | |

**Sprint 1 exit criterion**
- [ ] `docker compose up` -> api, worker, beat, postgres, redis, mock-crm, mailpit healthy in 60 s
- [ ] `GET /health` -> `{"status":"ok"}`; `GET /ready` -> dependency status
- [ ] CI green on the first push (ruff, mypy, pytest, docker build)
- [ ] `docs/adr/0001-stack.md` written by the owner
- [ ] 2-minute demo video recorded

---

## Sprint 2 — M1 Tenancy, auth, connections (target: 4–5 days)

| ID | Contract | Status | G1 | G2 | G3 | G4 | Notes |
|---|---|---|---|---|---|---|---|
| C10 | models.organization | TODO | | | | | |
| C11 | models.user + membership | TODO | | | | | |
| C12 | repositories.org_scope | TODO | | | | | |
| C13 | services.auth.password | TODO | | | | | |
| C14 | services.auth.tokens | TODO | | | | | |
| C15 | api.auth | TODO | | | | | |
| C16 | api.rbac | TODO | | | | | |
| C17 | core.crypto | TODO | | | | | |
| C18 | models.connections | TODO | | | | | |
| C19 | services.audit | TODO | | | | | |

**Sprint 2 exit criterion**
- [ ] test proves org A cannot read org B's rows (C12 is the anti-leak keystone)
- [ ] secrets in the DB are ciphertext; the API never returns them
- [ ] audit rows appear for auth and connection changes

---

## Sprint 3 — M2 First end-to-end flow (target: 4–5 days)

| ID | Contract | Status | G1 | G2 | G3 | G4 | Notes |
|---|---|---|---|---|---|---|---|
| C20 | models.flow | TODO | | | | | |
| C21 | services.conditions | TODO | | | | | |
| C22 | triggers.webhook | TODO | | | | | |
| C23 | services.events | TODO | | | | | |
| C24 | triggers.cron | TODO | | | | | |
| C25 | triggers.telegram | TODO | | | | | |
| C26 | triggers.imap | TODO | | | | | |
| C27 | actions.http | TODO | | | | | |
| C28 | actions.table | TODO | | | | | |
| C29 | actions.crm | TODO | | | | | |
| C30 | notifiers (base + 4 channels) | TODO | | | | | |

**Sprint 3 exit criterion**
- [ ] a webhook POST produces a stored event, a run and recorded steps
- [ ] a flow with 2 conditions + 2 actions runs correctly against a fake payload
- [ ] the telegram trigger is reachable and normalises a text message

---

## Sprint 4 — M3 Engine & reliability (target: 5–6 days)

| ID | Contract | Status | G1 | G2 | G3 | G4 | Notes |
|---|---|---|---|---|---|---|---|
| C31 | workers.dispatcher | TODO | | | | | |
| C32 | workers.executor | TODO | | | | | |
| C33 | services.retry | TODO | | | | | |
| C34 | services.idempotency | TODO | | | | | |
| C35 | services.dead_letter | TODO | | | | | |
| C36 | services.rate_limit | TODO | | | | | |
| C37 | services.circuit_breaker | TODO | | | | | |

**Sprint 4 exit criterion**
- [ ] failing endpoint -> 3 retries with jitter -> DLQ -> manual replay -> success
- [ ] the same event delivered twice produces exactly one effect
- [ ] replay of a running run is rejected with 409

---

## Sprint 5 — M4 Connectors & frontend (target: 6–7 days)

| ID | Contract | Status | G1 | G2 | G3 | G4 | Notes |
|---|---|---|---|---|---|---|---|
| C38 | mock_crm service | TODO | | | | | |
| C39 | connectors.protocols | TODO | | | | | |
| C40 | frontend.app_shell | TODO | | | | | |
| C41 | frontend.connections | TODO | | | | | |
| C42 | frontend.flow_editor | TODO | | | | | |
| C43 | frontend.run_history | TODO | | | | | |
| C44 | frontend.dlq / notifications / audit | TODO | | | | | |
| C45 | frontend.demo_panel | TODO | | | | | |

**Sprint 5 exit criterion**
- [ ] the lead-routing scenario (Telegram/webhook -> CRM + table + email + Slack) completes in the UI
- [ ] a reviewer with no external account can trigger it via the demo panel

---

## Sprint 6 — M5 Production hardening (target: 4–5 days)

| ID | Contract | Status | G1 | G2 | G3 | G4 | Notes |
|---|---|---|---|---|---|---|---|
| C46 | api.metrics | TODO | | | | | |
| C47 | scripts.seed | TODO | | | | | |
| C48 | tests.integration | TODO | | | | | |
| C49 | tests.load | TODO | | | | | |
| C50 | docs (README EN, architecture, ADRs, demo script) | TODO | | | | | |

**Sprint 6 exit criterion**
- [ ] `make demo` from a clean clone gives a working system with fake data in 60 s
- [ ] integration suite covers the five mandatory failure scenarios
- [ ] README + screenshots + 3-minute video ready

---

## Sprint 7 — M6 Sales layer (target: 3 days)

| ID | Contract | Status | G1 | G2 | G3 | G4 | Notes |
|---|---|---|---|---|---|---|---|
| C51 | docs.use_cases | TODO | | | | | |
| C52 | docs.services | TODO | | | | | |
| C53 | landing page | TODO | | | | | |
| C54 | sales.outreach tracker | TODO | | | | | |

**Sprint 7 exit criterion**
- [ ] landing deployed and linked from every profile
- [ ] >= 50 targets in the tracker, >= 5 messages sent per week
- [ ] 1 reply received, 1 call booked

---

## Weekly log

| Week | Modules accepted | Rejected at gates | Clarifications needed | Demo video | Outreach sent | Notes |
|---|---|---|---|---|---|---|
| 1 | C01–C06 | C04, C05, C06 (one round each, fixed and re-reviewed) | — | — | — | foundation contracts done; C07 infra.docker in progress |
| 2 | | | | | | |
| 3 | | | | | | |
| 4 | | | | | | |
| 5 | | | | | | |
| 6 | | | | | | |
| 7 | | | | | | |

---

## Demo notes (accumulate -> becomes the final demo script)

| Date | What the product can do now | How to show it |
|---|---|---|
| | | |

---

## Backlog (explicitly out of current scope)

- branching / loops in flows
- drag-and-drop flow builder
- WhatsApp / SMS / Discord notifiers
- ML / AI classification of events
- multi-tenant plan limits and billing (that is project #3)
- SSO / SAML, 2FA
- i18n
- mobile app
