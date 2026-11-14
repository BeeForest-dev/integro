"""Flow definition schema (C20) — the validated shape of a flow's JSON.

Type membership is validated against :data:`app.models.SUPPORTED_TYPES`
(the C18 single registry) in a field validator, so trigger and action
types can never drift from the connector families the system implements.
"""

from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.models import SUPPORTED_TYPES
from app.services.conditions import validate_conditions
from app.services.cron import CronError, validate_cron


def _supported_listing() -> str:
    return ", ".join(sorted(SUPPORTED_TYPES))


class Trigger(BaseModel):
    """What starts a flow.

    Attributes:
        type: One of ``SUPPORTED_TYPES`` (validated); ``"schedule"`` reads
            its timer from ``config``.
        config: Trigger-specific settings. For ``"schedule"`` exactly one of
            ``{"every_seconds": int > 0}`` or ``{"cron": "5-field string"}``.
    """

    type: str
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def _type_must_be_supported(cls, value: str) -> str:
        """Reject a type outside the single supported registry."""
        if value not in SUPPORTED_TYPES:
            raise ValueError(
                f"unsupported type '{value}' (supported: {_supported_listing()})"
            )
        return value

    @field_validator("config")
    @classmethod
    def _schedule_config_must_be_valid(
        cls, value: dict[str, Any], info: Any
    ) -> dict[str, Any]:
        """Validate schedule trigger configs at save time (C24)."""
        trigger_type = info.data.get("type")
        if trigger_type != "schedule":
            return value
        keys = set(value)
        if keys == {"every_seconds"}:
            interval = value["every_seconds"]
            if isinstance(interval, bool) or not isinstance(interval, int) or interval <= 0:
                raise ValueError("config.every_seconds: must be a positive integer")
            return value
        if keys == {"cron"}:
            expression = value["cron"]
            if not isinstance(expression, str):
                raise ValueError("config.cron: must be a string")
            try:
                validate_cron(expression)
            except CronError as exc:
                raise ValueError(f"config.cron: {exc}") from exc
            return value
        raise ValueError(
            "config: schedule triggers require exactly one of "
            "'every_seconds' or 'cron'"
        )


class Action(BaseModel):
    """One step a flow executes.

    Attributes:
        type: One of ``SUPPORTED_TYPES`` (validated).
        config: Action-specific settings.
    """

    type: str
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def _type_must_be_supported(cls, value: str) -> str:
        """Reject a type outside the single supported registry."""
        if value not in SUPPORTED_TYPES:
            raise ValueError(
                f"unsupported type '{value}' (supported: {_supported_listing()})"
            )
        return value


class FlowDefinition(BaseModel):
    """A complete flow definition: one trigger, ordered actions, conditions.

    Attributes:
        trigger: The trigger configuration (required).
        actions: The ordered action steps (may be empty).
        conditions: Optional condition tree (validated at save time via
            :func:`app.services.conditions.validate_conditions`).
    """

    trigger: Trigger
    actions: list[Action] = Field(default_factory=list)
    conditions: dict[str, Any] | None = None

    @field_validator("conditions")
    @classmethod
    def _conditions_must_be_valid(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        """Reject malformed condition trees so C20's 422 machinery sees ValueError."""
        if value is not None:
            validate_conditions(value)
        return value
