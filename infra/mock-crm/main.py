"""Minimal mock CRM (C07) — the demo integration target.

In-memory synthetic data only; no database, no external keys. Independent
of the main application. Contract C38 will extend this stub later.
"""

from typing import Any

from fastapi import FastAPI

app = FastAPI(title="mock-crm")

_leads: dict[int, dict[str, Any]] = {}
_next_id = 1


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe for the compose healthcheck."""
    return {"status": "ok"}


@app.post("/leads", status_code=201)
def create_lead(payload: dict[str, Any]) -> dict[str, Any]:
    """Echo the lead body back with a synthetic id."""
    global _next_id
    lead_id = _next_id
    _leads[lead_id] = payload
    _next_id += 1
    return {"id": lead_id, **payload}
