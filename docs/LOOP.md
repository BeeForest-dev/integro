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
ID:          C04
Name:        db.engine
State:       CHANGES_REQUESTED
Owner:       human
Implementer: kimi
Reviewer:    assistant
Awaiting:    implementer
Contract:    see docs/CONTRACTS.md, section C04
Delivery:    docs/reviews/C04.md
Note:        fix C04 first, then C05 (also CHANGES_REQUESTED, docs/reviews/C05.md).
             Both need the dependency manifest; see the verdicts for exact items.
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
| 2026-10-22 13:55 | owner | instruction "дальше" — start C05 while C04 review still pending |
| 2026-10-22 14:20 | implementer | C05 GENERATED (db.base + alembic wiring + 6 tests) — awaiting reviewer |
| 2026-10-26 14:05 | reviewer | C04 CHANGES_REQUESTED — code passes G1/G3/G4, but suite cannot collect in a clean checkout (no manifest) and ruff fails; see docs/reviews/C04.md |
| 2026-10-26 14:05 | reviewer | C05 CHANGES_REQUESTED — `alembic upgrade head` on real PostgreSQL fails (psycopg undeclared), conflict test targets the wrong case, ruff fails; see docs/reviews/C05.md |
| 2026-10-31 12:00 | reviewer | Re-checked C04/C05: no changes (HEAD 1138278, tree clean). Clean venv fails collection on all 6 test modules; ruff still 12 errors. Verdicts stand. |
```
