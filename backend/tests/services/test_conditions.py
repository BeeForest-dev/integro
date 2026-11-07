"""Tests for C21 services.conditions — pure stdlib, no database."""

import inspect
from pathlib import Path

import pytest

from app.services import conditions
from app.services.conditions import (
    ConditionValidationError,
    EvaluationResult,
    evaluate,
    validate_conditions,
)

MODULE_SOURCE = Path(inspect.getsourcefile(conditions)).read_text(encoding="utf-8")

PAYLOAD = {"amount": 100, "lead": {"email": "a@example.com"}, "tags": ["vip", "eu"]}


@pytest.mark.parametrize(
    ("op", "value", "expected"),
    [
        ("eq", 100, True),
        ("eq", 99, False),
        ("ne", 99, True),
        ("ne", 100, False),
        ("gt", 99, True),
        ("gt", 100, False),
        ("gt", 101, False),
        ("gte", 100, True),
        ("gte", 101, False),
        ("lt", 101, True),
        ("lt", 100, False),
        ("lte", 100, True),
        ("lte", 99, False),
    ],
)
def test_numeric_truth_table_with_boundaries(op, value, expected):
    """Numeric operators honor their boundaries exactly."""
    tree = {"all": [{"field": "amount", "op": op, "value": value}]}
    assert evaluate(tree, PAYLOAD).matched is expected


def test_contains_substring_and_list_membership():
    """contains works for substrings and list membership."""
    substring = {"all": [{"field": "lead.email", "op": "contains", "value": "@example.com"}]}
    assert evaluate(substring, PAYLOAD).matched
    member = {"all": [{"field": "tags", "op": "contains", "value": "vip"}]}
    assert evaluate(member, PAYLOAD).matched
    missing = {"all": [{"field": "tags", "op": "contains", "value": "nope"}]}
    assert not evaluate(missing, PAYLOAD).matched


def test_exists_ignores_the_value():
    """exists checks presence; the configured value is irrelevant."""
    assert evaluate({"all": [{"field": "amount", "op": "exists", "value": None}]}, PAYLOAD).matched
    assert not evaluate({"all": [{"field": "missing", "op": "exists"}]}, PAYLOAD).matched


def test_nested_field_paths():
    """Dot paths resolve through nested payload dicts."""
    tree = {"all": [{"field": "lead.email", "op": "eq", "value": "a@example.com"}]}
    assert evaluate(tree, PAYLOAD).matched


def test_missing_field_is_false_with_path_not_raise():
    """An absent payload field -> False plus a rendered path, no exception."""
    result = evaluate({"all": [{"field": "amount", "op": "gt", "value": 50}]}, {})
    assert result.matched is False
    assert result.failed_paths == ["all[0]: amount gt 50"]


def test_type_mismatch_is_false_not_raise():
    """Comparing a string payload value numerically -> False, no exception."""
    tree = {"all": [{"field": "lead.email", "op": "gt", "value": 10}]}
    assert evaluate(tree, PAYLOAD).matched is False


def test_all_and_any_nesting():
    """all/any nest; empty all is True, empty any is False (vacuous truth)."""
    nested = {
        "all": [
            {
                "any": [
                    {"field": "amount", "op": "gt", "value": 90},
                    {"field": "amount", "op": "lt", "value": 10},
                ]
            },
            {"field": "tags", "op": "contains", "value": "vip"},
        ]
    }
    assert evaluate(nested, PAYLOAD).matched
    assert evaluate({"all": []}, PAYLOAD) == EvaluationResult(matched=True, failed_paths=[])
    assert evaluate({"any": []}, PAYLOAD).matched is False


def test_failed_paths_render_for_ui():
    """Multiple failures render one entry per failed clause."""
    tree = {
        "all": [
            {"field": "amount", "op": "gt", "value": 500},
            {"field": "tags", "op": "contains", "value": "x"},
        ]
    }
    result = evaluate(tree, PAYLOAD)
    assert result.matched is False
    assert result.failed_paths == ["all[0]: amount gt 500", "all[1]: tags contains 'x'"]


def test_validate_unknown_operator_lists_supported_with_path():
    """Save-time validation rejects unknown operators with path and list."""
    with pytest.raises(ConditionValidationError) as exc_info:
        validate_conditions({"all": [{"field": "x", "op": "regex", "value": ".*"}]})

    message = str(exc_info.value)
    assert "all[0].op:" in message
    assert "'regex'" in message
    for supported in ("contains", "eq", "exists", "gt", "ne"):
        assert supported in message


@pytest.mark.parametrize(
    "tree",
    [
        ["not", "a", "dict"],
        {"all": [{"field": "amount"}]},
        {"all": [{"op": "gt", "value": 1}]},
        {"all": ["clause-as-string"]},
        {"all": [{"field": "x", "op": "eq", "value": 1}], "any": []},
    ],
)
def test_validate_malformed_trees(tree):
    """Malformed trees raise ConditionValidationError."""
    with pytest.raises(ConditionValidationError):
        validate_conditions(tree)


def test_runtime_unknown_operator_is_false_not_raise():
    """An operator removed from the registry degrades to False at runtime."""
    tree = {"all": [{"field": "amount", "op": "regex", "value": ".*"}]}
    result = evaluate(tree, PAYLOAD)
    assert result.matched is False
    assert result.failed_paths


def test_module_source_contains_no_eval():
    """The contract's hard rule: no eval anywhere in the module source."""
    assert "eval(" not in MODULE_SOURCE
    assert "exec(" not in MODULE_SOURCE
