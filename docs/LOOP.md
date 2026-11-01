# LOOP — coordination file

This file is the **only** shared channel between the agents working on this project.

- **Implementer:** Kimi / any coding agent
- **Reviewer:** the assistant in OpenCode (or the owner acting as reviewer)

Both agents read this file **first** and update it **last**. Everything else in the repo
is shared state; this file is shared *intent*.

---

## Protocol

### Implementer (Kimi)

1. Read `AGENTS.md` and `docs/CONTRACTS.md`.
2. Read the **Current contract** section below. If `State` is not `CONTRACTED`, do nothing.
3. Implement the contract exactly (code + a test per error case + docstrings).
4. Write a delivery note into `docs/reviews/<ID>.md` using the template in section "Review file".
5. Update the **Current contract** block below: `State: GENERATED`, add a timestamped line to
   the log, and set `Awaiting: reviewer`.
6. **Stop.** Do not start the next module.

### Reviewer (assistant)

1. Read `docs/reviews/<ID>.md` and the produced files.
2. Run the 4 gates:

   | Gate | Question |
   |---|---|
   | G1 Conformance | Does it do exactly the contract, nothing more? |
   | G2 Tests | Is there a test for **every** error case in the contract? |
   | G3 Boundaries | Timeouts, injection safety, secret leakage, unhandled exceptions, retries without jitter? |
   | G4 Architecture | Import direction respected? No business logic in routers? Connectors not touching the DB? |

3. Write the verdict into `docs/reviews/<ID>.md` (verdict + per-gate result + required changes).
4. Update the **Current contract** block below:
   - `State: CHANGES_REQUESTED` -> list what must change, `Awaiting: implementer`
   - `State: ACCEPTED` -> `Awaiting: owner`, record the module in `docs/TRACKER.md`
5. Stop.

### Owner (human)

Moves `CHANGES_REQUESTED` -> `CONTRACTED` after checking that the changes were made, and
decides when to start the next module. The owner owns scope and priority.

---

## Current contract

```
ID:          C01
Name:        core.config
State:       CONTRACTED      # CONTRACTED | GENERATED | CHANGES_REQUESTED | ACCEPTED
Owner:       human
Implementer: kimi
Reviewer:    assistant
Awaiting:    implementer
Contract:    see docs/CONTRACTS.md, section C01
Delivery:    docs/reviews/C01.md
```

---

## Log (append only, newest last)

| When | Who | Event |
|---|---|---|
| — | — | protocol initialised |

---

## Review file template — `docs/reviews/<ID>.md`

```markdown
# <ID> — <name>

## Contract
<verbatim copy from docs/CONTRACTS.md>

## Delivery note (written by the implementer)
1. What it does
2. Why it is built this way
3. How it is structured internally
4. Where the traps / failure modes are
5. How to verify it

## Files changed
- path/to/file.py — new / changed
- tests/... — new / changed

## Verdict (written by the reviewer)
**Result:** ACCEPTED | CHANGES_REQUESTED

| Gate | Result | Comment |
|---|---|---|
| G1 Conformance | pass / fail | |
| G2 Tests | pass / fail | |
| G3 Boundaries | pass / fail | |
| G4 Architecture | pass / fail | |

### Required changes
1. ...

### Questions for the owner
1. ...
```

---

## Rules for both agents

- Never edit the other's sections of this file; only the **Current contract** block and the **Log**.
- Never change a contract. If it is wrong, write it in the review verdict as a question.
- Never mark a module `ACCEPTED` — only the owner does that in the tracker.
- Keep the log append-only. It is the project's memory.
