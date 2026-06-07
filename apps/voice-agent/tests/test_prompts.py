"""Sanity tests on the system prompt + tool schemas."""

from src.prompts import SYSTEM_PROMPT, TOOL_SCHEMAS


def test_system_prompt_has_persona():
    assert "Mike" in SYSTEM_PROMPT
    assert "Acme Plumbing" in SYSTEM_PROMPT


def test_system_prompt_has_emergency_keywords():
    for kw in ["burst", "flooding", "no heat", "gas"]:
        assert kw in SYSTEM_PROMPT.lower()


def test_system_prompt_forbids_made_up_prices():
    assert "NEVER quote a price" in SYSTEM_PROMPT


def test_all_five_tools_defined():
    names = {t["function"]["name"] for t in TOOL_SCHEMAS}
    assert names == {
        "get_business_info",
        "check_availability",
        "book_appointment",
        "escalate_emergency",
        "transfer_to_human",
    }


def test_each_tool_has_description_and_parameters():
    for t in TOOL_SCHEMAS:
        fn = t["function"]
        assert fn["description"]
        assert fn["parameters"]["type"] == "object"
        # required fields must be a subset of properties
        required = set(fn["parameters"].get("required", []))
        properties = set(fn["parameters"]["properties"])
        assert required.issubset(properties), f"{fn['name']}: required not in properties"


def test_book_appointment_requires_confirmation_fields():
    fn = next(t["function"] for t in TOOL_SCHEMAS if t["function"]["name"] == "book_appointment")
    required = set(fn["parameters"]["required"])
    assert {"service_id", "scheduled_at_iso", "customer_name", "customer_phone", "customer_address"}.issubset(required)
