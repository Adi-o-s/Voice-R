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
from src.prompts import BUSINESS_TZ
from src.settings import settings
from src.sms import send_sms, send_whatsapp

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


def _business_time(iso: str) -> datetime:
    """Parse an ISO date/datetime into business time; naive values are taken as local."""
    when = datetime.fromisoformat(iso)
    if when.tzinfo is None:
        return when.replace(tzinfo=BUSINESS_TZ)
    return when.astimezone(BUSINESS_TZ)


def _open_hours(day: datetime) -> tuple[int, int] | None:
    weekday = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][day.weekday()]
    hours = _get_business()["business_hours"].get(weekday)
    return (hours[0], hours[1]) if hours else None


def _taken_hours(day: datetime, exclude_id: str | None = None) -> set[int]:
    """Business-time hours on `day` already held by a live appointment.

    Hours are compared in business time: `scheduled_at` comes back from Postgres
    in UTC, so its raw hour is 4-5 hours off the local slot it occupies.
    """
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = (
        supa()
        .table("appointments")
        .select("id, scheduled_at")
        .neq("status", "cancelled")
        .gte("scheduled_at", start.isoformat())
        .lt("scheduled_at", (start + timedelta(days=1)).isoformat())
        .execute()
        .data
    )
    return {_business_time(r["scheduled_at"]).hour for r in rows if r["id"] != exclude_id}


async def check_availability(service_id: str, date_iso: str) -> dict[str, Any]:
    """Return up to 5 available slots on the given date.

    v1: naive slot generator — hour-aligned slots inside business hours,
    excluding any that conflict with existing appointments.
    """
    day = _business_time(date_iso)
    hours = _open_hours(day)
    if hours is None:
        return {"available_slots": [], "note": "Closed that day."}

    taken = _taken_hours(day)
    slots = [
        day.replace(hour=h, minute=0, second=0, microsecond=0).isoformat()
        for h in range(*hours)
        if h not in taken
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
        return f"+{digits}"
    if len(digits) == 10 and digits[0] in "6789":
        return f"+91{digits}"
    if len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    return phone  # return as-is; Twilio will reject and we log the warning


def _is_e164(phone: str) -> bool:
    return phone.startswith("+") and phone[1:].isdigit() and 8 <= len(phone) - 1 <= 15


def _resolve_phone(spoken: str | None, caller: str | None) -> str | None:
    """The customer's number: what they dictated if usable, else their caller ID.

    Caller ID is the default identity — dictated digits are the least reliable
    thing the STT + LLM hand us, and a made-up number sends the SMS nowhere.
    """
    if spoken and _is_e164(normalized := _normalize_phone(spoken)):
        return normalized
    if caller and _is_e164(caller):
        return caller
    return None


def _check_future(iso: str) -> dict[str, Any] | None:
    """Error payload if `iso` is unparseable or in the past, else None.

    The model occasionally emits a stale year; returning an error makes it
    re-ask rather than confirm an impossible slot.
    """
    try:
        when = _business_time(iso)
    except ValueError:
        return {"error": "invalid_datetime", "message": "Use ISO 8601 for the date and time."}
    if when < datetime.now(BUSINESS_TZ):
        return {
            "error": "past_date",
            "message": f"{iso} is in the past. Ask the caller for a future date and try again.",
        }
    return None


def _spoken_time(when: datetime) -> str:
    return f"{when:%a %b %-d, %-I:%M %p}"


def _notify(phone: str, body: str) -> dict[str, bool]:
    """Text the customer on SMS and WhatsApp. A failed channel is logged, never raised."""
    sent: dict[str, bool] = {}
    for channel, send in (("sms", send_sms), ("whatsapp", send_whatsapp)):
        try:
            send(phone, body)
            sent[f"{channel}_sent"] = True
        except Exception as e:
            log.warning(f"{channel}_send_failed", err=str(e))
            sent[f"{channel}_sent"] = False
    return sent


async def book_appointment(
    service_id: str,
    scheduled_at_iso: str,
    customer_name: str,
    customer_address: str,
    customer_phone: str | None = None,
    notes: str | None = None,
    _call_id: str | None = None,
    _caller_phone: str | None = None,
) -> dict[str, Any]:
    b = _get_business()

    if err := _check_future(scheduled_at_iso):
        return err

    phone = _resolve_phone(customer_phone, _caller_phone)
    if phone is None:
        return {
            "error": "missing_phone",
            "message": "No usable phone number. Ask the caller for one, digit by digit.",
        }
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
                "customer_phone": phone,
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

    sent = _notify(
        phone,
        f"{b['name']} — booking confirmed for {_spoken_time(_business_time(scheduled_at_iso))}. "
        f"Confirmation code: {code}. Reply HELP for support.",
    )

    log.info("appointment_booked", code=code, scheduled_at=scheduled_at_iso)
    return {
        "confirmation_code": code,
        "scheduled_at_iso": scheduled_at_iso,
        **sent,
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


# -------- 6) find / reschedule / cancel an existing appointment -------------


def _live_appointment(appointment_id: str) -> dict[str, Any] | None:
    """The confirmed appointment with this id, or None.

    The id comes from the model, so a malformed one (Postgres rejects a
    non-UUID with an exception) is treated the same as a missing row.
    """
    try:
        rows = (
            supa()
            .table("appointments")
            .select("*")
            .eq("id", appointment_id)
            .eq("status", "confirmed")
            .limit(1)
            .execute()
            .data
        )
    except Exception as e:
        log.warning("appointment_lookup_failed", err=str(e))
        return None
    return rows[0] if rows else None


_NOT_FOUND = {
    "error": "not_found",
    "message": "No active appointment with that id. Call find_appointment first.",
}


async def find_appointment(
    customer_phone: str | None = None,
    _caller_phone: str | None = None,
) -> dict[str, Any]:
    phone = _resolve_phone(customer_phone, _caller_phone)
    if phone is None:
        return {
            "appointments": [],
            "note": "No phone number to search by. Ask which number the booking is under.",
        }

    rows = (
        supa()
        .table("appointments")
        .select(
            "id, confirmation_code, customer_name, customer_address, scheduled_at, "
            "service_id, services(name)"
        )
        .eq("customer_phone", phone)
        .eq("status", "confirmed")
        .gte("scheduled_at", datetime.now(BUSINESS_TZ).isoformat())
        .order("scheduled_at")
        .limit(3)
        .execute()
        .data
    )
    return {
        "appointments": [
            {
                "appointment_id": r["id"],
                "confirmation_code": r["confirmation_code"],
                "service_id": r["service_id"],
                "service_name": (r.get("services") or {}).get("name"),
                "scheduled_at_iso": _business_time(r["scheduled_at"]).isoformat(),
                "customer_name": r["customer_name"],
                "customer_address": r["customer_address"],
            }
            for r in rows
        ]
    }


async def reschedule_appointment(
    appointment_id: str,
    new_scheduled_at_iso: str,
    _call_id: str | None = None,
) -> dict[str, Any]:
    if err := _check_future(new_scheduled_at_iso):
        return err
    appt = _live_appointment(appointment_id)
    if appt is None:
        return _NOT_FOUND

    when = _business_time(new_scheduled_at_iso)
    hours = _open_hours(when)
    if hours is None or not hours[0] <= when.hour < hours[1]:
        return {
            "error": "outside_hours",
            "message": "We're closed then. Call check_availability and offer an open slot.",
        }
    if when.hour in _taken_hours(when, exclude_id=appointment_id):
        return {
            "error": "slot_taken",
            "message": "That time is already booked. Call check_availability and offer another.",
        }

    supa().table("appointments").update({"scheduled_at": when.isoformat()}).eq(
        "id", appointment_id
    ).execute()
    if _call_id:
        supa().table("calls").update({"outcome": "booked"}).eq("id", _call_id).execute()

    code = appt["confirmation_code"]
    sent = _notify(
        appt["customer_phone"],
        f"{_get_business()['name']} — your appointment {code} is now {_spoken_time(when)}.",
    )
    log.info("appointment_rescheduled", code=code, scheduled_at=when.isoformat())
    return {
        "rescheduled": True,
        "confirmation_code": code,
        "scheduled_at_iso": when.isoformat(),
        **sent,
    }


async def cancel_appointment(appointment_id: str) -> dict[str, Any]:
    appt = _live_appointment(appointment_id)
    if appt is None:
        return _NOT_FOUND

    supa().table("appointments").update({"status": "cancelled"}).eq(
        "id", appointment_id
    ).execute()

    code = appt["confirmation_code"]
    sent = _notify(
        appt["customer_phone"],
        f"{_get_business()['name']} — your appointment {code} for "
        f"{_spoken_time(_business_time(appt['scheduled_at']))} is cancelled.",
    )
    log.info("appointment_cancelled", code=code)
    return {"cancelled": True, "confirmation_code": code, **sent}
