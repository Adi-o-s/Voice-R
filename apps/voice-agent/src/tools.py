"""LLM tool handlers — pure async functions invoked by the GroqLLMService.

Each handler:
  - Takes a dict of args (validated against the JSON schema in prompts.py).
  - Returns a dict that becomes the tool_result the LLM reads back.
  - Side effects: DB writes, SMS sends.

NOTE: Sprint 1 ships only stubs that return canned data. Sprint 2 wires up
the real DB/SMS calls. The tests in tests/test_tools.py mock both sides.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Any

import structlog

from src.db import supa
from src.settings import settings
from src.sms import send_sms

log = structlog.get_logger(__name__)


# Cached business row for the run — set on call open by ConversationLogger.
_business_cache: dict[str, Any] | None = None


def _get_business() -> dict[str, Any]:
    global _business_cache
    if _business_cache is None:
        rows = (
            supa()
            .table("businesses")
            .select("*, services(*)")
            .eq("slug", settings.business_slug)
            .limit(1)
            .execute()
            .data
        )
        if not rows:
            raise RuntimeError(f"Business {settings.business_slug!r} not found in DB")
        _business_cache = rows[0]
    return _business_cache


# -------- 1) get_business_info ---------------------------------------------


async def get_business_info() -> dict[str, Any]:
    b = _get_business()
    return {
        "name": b["name"],
        "hours": b["business_hours"],
        "services": [
            {
                "id": s["id"],
                "name": s["name"],
                "price_cents": s["base_price_cents"],
                "duration_minutes": s["duration_minutes"],
                "emergency_eligible": s["emergency_eligible"],
            }
            for s in b["services"]
        ],
        "emergency_keywords": ["burst", "flooding", "no heat", "gas", "water everywhere"],
    }


# -------- 2) check_availability --------------------------------------------


async def check_availability(service_id: str, date_iso: str) -> dict[str, Any]:
    """Return up to 5 available slots on the given date.

    v1: naive slot generator — hour-aligned slots inside business hours,
    excluding any that conflict with existing appointments.
    """
    b = _get_business()
    day = datetime.fromisoformat(date_iso)
    weekday = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][day.weekday()]
    hours = b["business_hours"].get(weekday)
    if hours is None:
        return {"available_slots": [], "note": "Closed that day."}

    start_hour, end_hour = hours

    existing = (
        supa()
        .table("appointments")
        .select("scheduled_at")
        .gte("scheduled_at", day.isoformat())
        .lt("scheduled_at", (day + timedelta(days=1)).isoformat())
        .execute()
        .data
    )
    booked = {
        datetime.fromisoformat(r["scheduled_at"].replace("Z", "+00:00")).hour for r in existing
    }

    slots = [
        day.replace(hour=h, minute=0, second=0, microsecond=0).isoformat()
        for h in range(start_hour, end_hour)
        if h not in booked
    ][:5]

    return {"available_slots": slots}


# -------- 3) book_appointment ----------------------------------------------


def _normalize_phone(phone: str) -> str:
    """Best-effort E.164 normalization for Indian numbers spoken to the STT.

    Twilio rejects non-E.164 numbers with error 21211. The LLM often omits
    the country code when the caller speaks digits. Heuristic: a 10-digit
    string starting with 6-9 is a valid Indian mobile → prepend +91.
    """
    digits = "".join(c for c in phone if c.isdigit())
    if phone.startswith("+"):
        return phone  # already E.164
    if len(digits) == 10 and digits[0] in "6789":
        return f"+91{digits}"
    if len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    return phone  # return as-is; Twilio will reject and we log the warning


async def book_appointment(
    service_id: str,
    scheduled_at_iso: str,
    customer_name: str,
    customer_phone: str,
    customer_address: str,
    notes: str | None = None,
    _call_id: str | None = None,
) -> dict[str, Any]:
    b = _get_business()

    # Reject past-dated bookings. The model occasionally emits a stale year;
    # return an error so it re-asks rather than confirming an impossible slot.
    try:
        when = datetime.fromisoformat(scheduled_at_iso)
    except ValueError:
        return {"error": "invalid_datetime", "message": "Use ISO 8601 for scheduled_at_iso."}
    ref = datetime.now(when.tzinfo) if when.tzinfo else datetime.now()
    if when < ref:
        return {
            "error": "past_date",
            "message": (
                f"{scheduled_at_iso} is in the past. Ask the caller for a future "
                "date and call book_appointment again."
            ),
        }

    customer_phone = _normalize_phone(customer_phone)
    code = "ACM-" + secrets.token_hex(3).upper()

    row = (
        supa()
        .table("appointments")
        .insert(
            {
                "call_id": _call_id,
                "business_id": b["id"],
                "service_id": service_id,
                "customer_name": customer_name,
                "customer_phone": customer_phone,
                "customer_address": customer_address,
                "scheduled_at": scheduled_at_iso,
                "confirmation_code": code,
                "notes": notes,
            }
        )
        .execute()
        .data
    )

    if _call_id:
        supa().table("calls").update({"outcome": "booked"}).eq("id", _call_id).execute()

    sms_sent = False
    try:
        send_sms(
            customer_phone,
            f"Acme Plumbing — booking confirmed for {scheduled_at_iso}. "
            f"Confirmation code: {code}. Reply HELP for support.",
        )
        sms_sent = True
    except Exception as e:
        log.warning("sms_send_failed", err=str(e))

    log.info("appointment_booked", code=code, scheduled_at=scheduled_at_iso)
    return {
        "confirmation_code": code,
        "scheduled_at_iso": scheduled_at_iso,
        "sms_sent": sms_sent,
        "appointment_id": row[0]["id"] if row else None,
    }


# -------- 4) escalate_emergency --------------------------------------------


async def escalate_emergency(
    reason: str,
    callback_phone: str,
    _call_id: str | None = None,
) -> dict[str, Any]:
    b = _get_business()
    try:
        send_sms(
            b["emergency_phone"],
            f"🚨 EMERGENCY for {b['name']}: {reason}. Callback: {callback_phone}.",
        )
        paged = True
    except Exception as e:
        log.exception("emergency_sms_failed", err=str(e))
        paged = False

    if _call_id:
        supa().table("calls").update({"outcome": "emergency"}).eq("id", _call_id).execute()

    log.warning("emergency_escalated", reason=reason, callback=callback_phone)
    return {"paged": paged, "eta_minutes": 5}


# -------- 5) transfer_to_human ---------------------------------------------


async def transfer_to_human(reason: str, _call_id: str | None = None) -> dict[str, Any]:
    log.info("transfer_to_human", reason=reason)
    if _call_id:
        supa().table("calls").update({"outcome": "dropped"}).eq("id", _call_id).execute()
    return {"transferred": True}
