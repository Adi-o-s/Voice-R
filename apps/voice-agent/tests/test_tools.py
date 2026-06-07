"""Tool-handler unit tests. Sprint 1 wires real DB; for Sprint 0 we just verify importability + signatures.

Real DB-backed tests run in Sprint 2 against a Supabase test project (or local PG via docker — out of scope for v1).
"""

import inspect

import pytest

from src import tools


@pytest.mark.parametrize(
    "fn_name",
    [
        "get_business_info",
        "check_availability",
        "book_appointment",
        "escalate_emergency",
        "transfer_to_human",
    ],
)
def test_tool_is_async(fn_name):
    fn = getattr(tools, fn_name)
    assert inspect.iscoroutinefunction(fn), f"{fn_name} must be async"


def test_book_appointment_signature_matches_schema():
    sig = inspect.signature(tools.book_appointment)
    public_params = {p for p in sig.parameters if not p.startswith("_")}
    # Must accept every required field from the schema.
    required = {
        "service_id",
        "scheduled_at_iso",
        "customer_name",
        "customer_phone",
        "customer_address",
    }
    assert required.issubset(public_params)


def test_escalate_signature():
    sig = inspect.signature(tools.escalate_emergency)
    public_params = {p for p in sig.parameters if not p.startswith("_")}
    assert {"reason", "callback_phone"}.issubset(public_params)
