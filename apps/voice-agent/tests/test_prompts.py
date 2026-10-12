"""Sanity tests on the system prompt + tool schemas."""

from src.prompts import SYSTEM_PROMPT, TOOL_FUNCTION_SCHEMAS, TOOL_SCHEMAS, build_system_prompt


def test_system_prompt_has_persona():
    assert "Mike" in SYSTEM_PROMPT
    assert "Acme Plumbing" in SYSTEM_PROMPT


def test_system_prompt_has_emergency_keywords():
    for kw in ["burst", "flooding", "no heat", "gas"]:
        assert kw in SYSTEM_PROMPT.lower()


def test_system_prompt_forbids_made_up_prices():
    assert "NEVER quote a price" in SYSTEM_PROMPT


def test_all_tools_defined_in_both_schema_lists():
    expected = {
        "get_business_info",
        "check_availability",
        "book_appointment",
        "escalate_emergency",
        "transfer_to_human",
        "find_appointment",
        "reschedule_appointment",
        "cancel_appointment",
    }
    assert {t["function"]["name"] for t in TOOL_SCHEMAS} == expected
    assert {t.name for t in TOOL_FUNCTION_SCHEMAS} == expected


def test_prompt_tells_the_model_the_callers_number():
    assert "+15550100142" in build_system_prompt(caller_phone="+15550100142")


def test_prompt_omits_a_withheld_caller_id():
    assert "The caller is dialing from" not in build_system_prompt(caller_phone="anonymous")


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
    assert {"service_id", "scheduled_at_iso", "customer_name", "customer_address"}.issubset(required)
    # Caller ID is the default; the model only passes a phone the caller dictated.
    assert "customer_phone" not in required
