"""Shared routing/security budgets for the local context/action domain slice."""

import pytest

from rtr_copilot.limits.middleware import classify


@pytest.mark.parametrize(("method", "path", "expected"), [
    ("POST", "/api/v1/context/resolve", "default-read"),
    ("POST", "/api/v1/context/packets", "default-read"),
    ("GET", "/api/v1/context/packets/packet-id", "default-read"),
    ("GET", "/api/v1/context/memory", "default-read"),
    ("GET", "/api/v1/context/memory/memory-id", "default-read"),
    ("POST", "/api/v1/context/memory", "upload"),
    ("PUT", "/api/v1/context/memory/memory-id", "upload"),
    ("PATCH", "/api/v1/context/memory/memory-id", "upload"),
    ("DELETE", "/api/v1/context/memory/memory-id", "upload"),
    ("POST", "/api/v1/actions/plans", "render"),
    ("POST", "/api/v1/actions/plans/plan-id/admit", "render"),
    ("POST", "/api/v1/actions/plans/plan-id/approvals", "render"),
    ("POST", "/api/v1/actions/plans/plan-id/validate-ready", "render"),
    ("PUT", "/api/v1/actions/capabilities", "admin"),
    ("POST", "/api/v1/actions/capabilities/admit", "admin"),
    ("DELETE", "/api/v1/actions/capabilities/version-id", "admin"),
    ("POST", "/api/v1/actions/capabilities-like", "render"),
    ("PATCH", "/api/v1/actions/plans/plan-id", "render"),
    ("DELETE", "/api/v1/actions/plans/plan-id", "render"),
    ("GET", "/api/v1/actions/plans/plan-id", "default-read"),
    ("GET", "/api/v1/actions/capabilities", "default-read"),
    ("POST", "/api/v1/context/memory-like", "default-read"),
    ("POST", "/api/v1/actions-like", "default-read"),
])
def test_tip054_write_paths_have_explicit_finite_budget_class(
    method: str, path: str, expected: str,
) -> None:
    assert classify(method, path) == expected
