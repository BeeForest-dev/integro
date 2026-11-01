# Execution plan — `integro` (folder: `spidoznye_kozyvki2`)

Lead-routing & workflow-automation platform. Demo environment + foundation for real client work.

This document is the **operating manual** for the project: who decides what, how a module
travels from idea to accepted code, and where the owner (human) sets boundaries.

---

## 1. Roles

| Role | Owner | Responsibility | Forbidden |
|---|---|---|---|
| **Decision maker** | Human (owner) | Approves contracts, changes architecture, accepts modules, talks to clients, records demo | — |
| **Implementer** | Kimi / any AI agent | Writes code + tests from a contract, explains in 5 points | Changing schema, deps, layers, contracts |
| **Architect / keeper** | This assistant (OpenCode) | Maintains the contract registry, catches architecture drift, co-writes ADRs, reviews critical modules | Writing modules in place of the owner |
| **Reviewer** | Human + assistant | Runs the 4 gates, rejects what does not pass | Rubber-stamping |

---

## 2. The module pipeline (4 gates)

```
  CONTRACT            GENERATION           REVIEW                ACCEPTANCE
  ─────────           ──────────           ──────                ──────────
  3 lines, human      Kimi writes          human reads diff      module marked
  writes it           code + tests         + answers 4 gates      done in
                                         + 5-point check        TRACKER
```

### 2.1 Contract format (3 lines, human-written, human-owns)

```
Purpose:    one sentence
In -> Out:  concrete types
Errors:     every failure case and the behaviour for each
Side fx:    tables touched, external calls made
Deps:       allowed imports
```

**Rule:** if the human cannot state the contract out loud, the module does not get generated.
This is the single most important boundary in the project.

### 2.2 The 4 review gates

| Gate | Question | Failure action |
|---|---|---|
| **G1 Conformance** | Does the code do exactly the contract, nothing more? | Send back: remove the extras |
| **G2 Tests** | Is there a test for *every* error case in the contract? | Add the missing tests |
| **G3 Boundaries** | Timeouts on outbound calls? Injection-safe? No secrets in logs? No unhandled exceptions? No retries without jitter? | Fix before anything else |
| **G4 Architecture** | Import direction respected? No business logic in routers? Connectors do not touch the DB? | Restructure |

A module is accepted only when **all four** pass. Partial passes are rejected.

### 2.3 The 5-point explanation (required from the AI after generation)

1. What it does
2. Why it is built this way (trade-offs)
3. How it is structured internally
4. Where the traps / failure modes are
5. How to verify it

The human checks that the explanation matches the code. A mismatch = G1 failure.

---

## 3. Boundaries set by the owner

Encoded in `AGENTS.md`. Summary:

1. No changes to schema, dependencies, layers or public contracts without approval.
2. Dependency allow-list only.
3. One PR = one contract. No drive-by refactors.
4. Every contract ships code + tests + docstring + (ADR if needed).
5. Strict layering: `api -> services -> repositories -> models`; workers never import `api`;
   connectors never touch the DB.
6. Secrets only via environment variables.
7. Every outbound HTTP call has a timeout; every retry has jitter.
8. **No invented features.** Anything not in the contract goes to the PR description as a proposal.
9. Ambiguity -> one clarifying question, then stop.

### 3.1 Where the owner intervenes — the explicit checklist

| Moment | Owner's decision | Cannot be delegated |
|---|---|---|
| Before generation | Signs the contract | Who decides scope |
| After generation | Runs G1–G4 | Acceptance |
| On architecture change | Approves + records ADR | Technology choices |
| Weekly | Picks the next contracts | Priorities |
| With clients | Positioning, price, scope | Selling |

---

## 4. Cadence

### Daily (60–90 min, owner)

| Minutes | Activity |
|---|---|
| 10 | Read the next contract, restate it in your own words |
| 15 | Read the generated diff, look for "not what was asked" |
| 15 | Run the tests, read 2–3 of them properly |
| 10 | Answer the 4 gates, write the ADR if needed |
| 10 | Update the demo notes: "what the product can do now" |
| 20 | Move the module in `TRACKER.md`, take the next contract |

Limit: **1–2 modules per day.** More accumulates unreviewed code and the owner stops
understanding the codebase — which is the actual goal of the project.

### Weekly (2–3 h)

- Record a 2-minute demo video of the current state (accumulates into the final demo)
- Update `TRACKER.md` with measured numbers
- Write 1 ADR
- 3–5 outreach messages to agencies/clients (the sales track, never skipped)

### Sprint (2 weeks)

- Demo milestone end-to-end, record it
- Retro: what was harder than the contract assumed
- Adjust contracts for the next sprint

---

## 5. Metrics (measure these, not lines of code)

| Metric | Target |
|---|---|
| Modules accepted / total | sprint velocity |
| Modules rejected at gates | quality of the contract, not of the AI |
| Contracts needing clarification | shrinks over time = the owner is getting better at specifying |
| Demo steps reproducible from a clean clone | must be 100% at every milestone |
| Outreach messages sent per week | >= 5 |

---

## 6. Milestone map (details in `CONTRACTS.md`)

| Milestone | Content | Exit criterion |
|---|---|---|
| **M0 Foundation** | config, logging, errors, db, health, docker, CI, alembic | `docker compose up` starts 7 services, `/health` returns ok, CI green |
| **M1 Tenancy & auth** | orgs, users, memberships, JWT, RBAC, encrypted connections, audit | test proves org A cannot read org B data |
| **M2 First end-to-end flow** | flow model, JSON schema, condition evaluator, webhook + cron triggers, one action | a webhook call produces a recorded run and a step |
| **M3 Engine & reliability** | dispatcher, executor, retry, idempotency, DLQ, replay, rate limit, circuit breaker | failing endpoint -> 3 retries -> DLQ -> replay -> success, no duplicates |
| **M4 Connectors & frontend** | 4 notifiers, telegram/imap triggers, mock CRM, mailpit, React admin | the lead-routing scenario runs end-to-end through the UI |
| **M5 Production hardening** | metrics, seed script, integration + failure tests, load test, docs, deploy | `make demo` gives a working system with fake data in 60 s |
| **M6 Sales layer** | USE_CASES, service offers, landing page, outreach tracker, proposal templates | one agency replied, one call booked |

---

## 7. Definition of Done for the whole project

- [ ] `git clone && docker compose up` -> working system with seeded demo data
- [ ] No external key required for the demo path
- [ ] CI green: lint, type-check, unit, integration, docker build
- [ ] Tests include failure scenarios (network, timeout, malformed payload, duplicate event)
- [ ] README in English: problem -> solution -> screenshots -> architecture -> run -> tests
- [ ] `docs/architecture.md` with diagrams + ADRs
- [ ] 2–3 screenshots + 3-minute demo video
- [ ] Live demo URL
- [ ] `USE_CASES.md` + service offers with prices
- [ ] Outreach tracker with >= 50 target companies
- [ ] No secrets, no Russian text anywhere in the repository

---

## 8. Risks and counters

| Risk | Counter |
|---|---|
| AI produces a framework instead of a product | Contract registry is fixed; extra features are rejected at G1 |
| Owner stops understanding the code | 1–2 modules/day cap, 5-point explanation check, ADR per module |
| Demo depends on external services | Every connector has a local mock; `make demo` path uses no external key |
| Scope creep towards "another Zapier" | 4 notifiers, 4 triggers, linear flows, no branching engine |
| Infrastructure eats the time | Docker + CI in M0, one week budget, no timeboxes beyond that |
