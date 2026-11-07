"""Condition evaluation for flows (C21) — explicit operator registry, no eval.

A condition tree is ``{"all": [node, ...]}`` or ``{"any": [node, ...]}``
(nestable), where a leaf is ``{"field": "a.b.c", "op": name, "value": ...}``.
Field paths are dot-lookups into the payload dict.

Validation (save time) is strict and raises :class:`ConditionValidationError`
with the JSON path of the first problem. Evaluation (run time) never raises:
an unknown operator, a missing payload field, or a type mismatch simply
makes the clause False and records its path in ``failed_paths`` for the UI.

Vacuous truth, documented: an empty ``all`` matches everything (True), an
empty ``any`` matches nothing (False).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

SUPPORTED_OPERATORS = ("contains", "eq", "exists", "gt", "gte", "lt", "lte", "ne")


class ConditionValidationError(ValueError):
    """A condition tree is malformed (unknown operator, bad shape, ...)."""


def _numeric_pair(left: Any, right: Any) -> tuple[float, float] | None:
    """Return both values as numbers, or None on a type mismatch."""
    if isinstance(left, bool) or isinstance(right, bool):
        return None
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return float(left), float(right)
    return None


def _op_eq(left: Any, right: Any) -> bool:
    return left == right


def _op_ne(left: Any, right: Any) -> bool:
    return left != right


def _op_gt(left: Any, right: Any) -> bool:
    pair = _numeric_pair(left, right)
    return pair is not None and pair[0] > pair[1]


def _op_gte(left: Any, right: Any) -> bool:
    pair = _numeric_pair(left, right)
    return pair is not None and pair[0] >= pair[1]


def _op_lt(left: Any, right: Any) -> bool:
    pair = _numeric_pair(left, right)
    return pair is not None and pair[0] < pair[1]


def _op_lte(left: Any, right: Any) -> bool:
    pair = _numeric_pair(left, right)
    return pair is not None and pair[0] <= pair[1]


def _op_contains(left: Any, right: Any) -> bool:
    if isinstance(left, str) and isinstance(right, str):
        return right in left
    if isinstance(left, list):
        return right in left
    return False


def _op_exists(left: Any, _right: Any) -> bool:
    return left is not _MISSING


_OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
    "eq": _op_eq,
    "ne": _op_ne,
    "gt": _op_gt,
    "gte": _op_gte,
    "lt": _op_lt,
    "lte": _op_lte,
    "contains": _op_contains,
    "exists": _op_exists,
}


class _Missing:
    """Sentinel for absent payload fields (None is a legitimate value)."""


_MISSING = _Missing()


def _supported_listing() -> str:
    return ", ".join(sorted(_OPERATORS))


def _lookup(payload: dict[str, Any], path: str) -> Any:
    """Resolve a dot path in the payload; _MISSING when any step is absent."""
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


@dataclass(frozen=True)
class EvaluationResult:
    """Outcome of evaluating a condition tree against one payload.

    Attributes:
        matched: True when the tree holds for the payload.
        failed_paths: Human-readable paths of every failed clause, e.g.
            ``"all[0]: amount gt 100"`` — rendered for the UI.
    """

    matched: bool
    failed_paths: list[str] = field(default_factory=list)


def _render_clause(clause: dict[str, Any]) -> str:
    """Render a clause for failed_paths, e.g. 'amount gt 100'."""
    value = clause.get("value")
    return f"{clause.get('field')} {clause.get('op')} {value!r}"


def _validate_clause(clause: Any, path: str) -> None:
    """Raise ConditionValidationError naming the first problem in a leaf."""
    if not isinstance(clause, dict):
        raise ConditionValidationError(f"{path}: clause must be an object")
    field_path = clause.get("field")
    if not isinstance(field_path, str) or not field_path:
        raise ConditionValidationError(f"{path}.field: missing or invalid field path")
    operator = clause.get("op")
    if not isinstance(operator, str) or not operator:
        raise ConditionValidationError(f"{path}.op: missing or invalid operator")
    if operator not in _OPERATORS:
        raise ConditionValidationError(
            f"{path}.op: unknown operator '{operator}' (supported: {_supported_listing()})"
        )


def _validate_node(node: Any, path: str) -> None:
    """Recursively validate a tree node, raising on the first problem."""
    if not isinstance(node, dict):
        raise ConditionValidationError(f"{path}: node must be an object")
    keys = set(node)
    if keys == {"all"} or keys == {"any"}:
        combinator = "all" if "all" in keys else "any"
        children = node[combinator]
        if not isinstance(children, list):
            raise ConditionValidationError(f"{path}: children must be a list")
        for index, child in enumerate(children):
            _validate_node(child, f"{path}[{index}]")
        return
    if "all" in keys or "any" in keys:
        raise ConditionValidationError(f"{path}: 'all'/'any' cannot be combined with clause keys")
    _validate_clause(node, path)


def validate_conditions(tree: Any) -> None:
    """Validate a condition tree, raising on the first problem.

    Args:
        tree: The condition tree (all/any nodes and leaf clauses).

    Raises:
        ConditionValidationError: With the JSON path of the first problem.
    """
    _validate_node(tree, _root_path(tree))


def _root_path(tree: Any) -> str:
    """The display root: the top-level combinator, or '$' for a bare node."""
    if isinstance(tree, dict):
        if set(tree) == {"all"}:
            return "all"
        if set(tree) == {"any"}:
            return "any"
    return "$"


def _evaluate_node(node: Any, payload: dict[str, Any], path: str, failed: list[str]) -> bool:
    """Evaluate one node, appending rendered paths of failed clauses."""
    if not isinstance(node, dict):
        failed.append(path)
        return False
    if set(node) == {"all"}:
        # Every child evaluates (failed_paths must be complete); empty all -> True.
        results = [
            _evaluate_node(child, payload, f"{path}[{index}]", failed)
            for index, child in enumerate(node["all"])
        ]
        return all(results)
    if set(node) == {"any"}:
        # Empty any -> False (documented).
        branch_failures: list[str] = []
        matched_any = False
        for index, child in enumerate(node["any"]):
            branch_failed: list[str] = []
            if _evaluate_node(child, payload, f"{path}[{index}]", branch_failed):
                matched_any = True
            else:
                branch_failures.extend(branch_failed)
        if matched_any:
            return True
        failed.extend(branch_failures)
        return False
    field_path = node.get("field")
    operator = node.get("op")
    predicate = _OPERATORS.get(operator) if isinstance(operator, str) else None
    if not isinstance(field_path, str) or predicate is None:
        failed.append(f"{path}: {_render_clause(node) if isinstance(node, dict) else path}")
        return False
    value = _lookup(payload, field_path)
    clause_path = f"{path}: {_render_clause(node)}"
    if value is _MISSING:
        failed.append(clause_path)
        return False
    try:
        matched = predicate(value, node.get("value"))
    except Exception:  # noqa: BLE001 — evaluation must never raise
        matched = False
    if not matched:
        failed.append(clause_path)
    return matched


def evaluate(tree: dict[str, Any], payload: dict[str, Any]) -> EvaluationResult:
    """Evaluate a condition tree against an event payload.

    Never raises: unknown operators, missing fields and type mismatches all
    degrade the affected clause to False and record its path.

    Args:
        tree: The condition tree (ideally pre-validated by
            :func:`validate_conditions` at save time).
        payload: The event payload (a nested dict).

    Returns:
        The :class:`EvaluationResult` with the overall match and the
        rendered failed-clause paths for the UI.
    """
    failed: list[str] = []
    matched = _evaluate_node(tree, payload, _root_path(tree), failed)
    return EvaluationResult(matched=matched, failed_paths=failed)
