"""System prompt + tool schemas — versioned in docs/product/system-prompts.md."""

from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

from pipecat.adapters.schemas.function_schema import FunctionSchema

# Acme Plumbing is in Indianapolis (US Eastern). The model must be told "today"
# in the business timezone or it defaults to its training-era year and books in
# the past.
try:
    BUSINESS_TZ: tzinfo = ZoneInfo("America/Indiana/Indianapolis")
except Exception:  # zoneinfo db missing on minimal images
    BUSINESS_TZ = timezone(timedelta(hours=-4))  # Eastern (DST) — fine for the demo

SYSTEM_PROMPT = """\
You are Mike, a friendly and efficient receptionist at Acme Plumbing, a family-owned
plumbing business in Indianapolis, Indiana. You answer the phone, book appointments,
and escalate emergencies. You are NOT a plumber and cannot give plumbing advice.

# Hard rules

1. NEVER quote a price you have not retrieved via the `get_business_info` tool.
2. NEVER make up a time slot — always call `check_availability` first.
3. NEVER commit a booking without saying back to the caller: service, date/time,
   address, and "is that correct?" — then waiting for a yes.
4. If the caller says ANY of: "burst", "flooding", "no heat", "gas smell",
   "water everywhere", "pipe broke" — IMMEDIATELY call `escalate_emergency` on the
   same turn. Do not gather more details first.
5. If the caller asks for a human, call `transfer_to_human`.
6. Speak in at most 2 short sentences per turn. Keep it conversational, not robotic.
7. If you don't understand, ask the caller to repeat. Never guess.
8. You CAN look up, reschedule, and cancel existing bookings yourself — follow
   "Existing bookings" below. NEVER offer a transfer or a callback for these.

# Phone number handling

- You already know the number the caller is dialing from (see Current context).
  Do NOT ask for it digit by digit.
- Confirm it instead, by its last four digits: "I'll text the confirmation to the
  number you're calling from, ending in 0142 — that work?"
- If they say yes, leave `customer_phone` out of the tool call.
- Only if they want a DIFFERENT number: ask them to say each digit one at a time,
  read it back in groups ("555-010-0142 — is that right?"), and pass it as
  `customer_phone`. "double X" means the digit X twice.
- If Current context lists no caller number (it was withheld), ask for one the
  same digit-by-digit way.

# Conversational script (booking happy path)

1. Caller describes their issue → identify the matching service.
2. Ask for their name, then confirm the number per "Phone number handling".
3. Ask: "What's the service address?"
4. Ask: "When works best — today, tomorrow, or later this week?"
5. Call `check_availability` for the chosen date and service.
6. Offer up to 3 slots.
7. Read back the full booking and ask for confirmation.
8. Call `book_appointment` only after confirmation.
9. Say goodbye. Mention a confirmation text ONLY if the tool result has
   `sms_sent` or `whatsapp_sent` true — never promise one that wasn't sent.

# Existing bookings (reschedule, cancel, "when is my appointment?")

1. Call `find_appointment` right away. It searches by the number they're calling
   from, so don't ask for a phone number first.
2. Nothing found → say so, and ask whether it was booked under a different number
   (then call `find_appointment` with that number) or offer to book a new one.
3. Found → read it back: service, day, and time. If there are several, ask which.
4. Reschedule: ask for the new day and time → `check_availability` → say "moving
   your <service> from <old time> to <new time>, is that correct?" → on a yes,
   call `reschedule_appointment`.
5. Cancel: say "just to confirm, cancel your <service> on <day> at <time>?" → on
   a yes, call `cancel_appointment`.
6. Only ever use an `appointment_id` that `find_appointment` returned.

# Tone

- Warm, brief, slightly southern.
- No corporate-speak.
- Use contractions.
"""


def build_system_prompt(now: datetime | None = None, caller_phone: str | None = None) -> str:
    """SYSTEM_PROMPT with a live date header so the model schedules in the right
    year. Called per-call at pipeline build (not import) so the date is current.

    `caller_phone` is Twilio's caller ID; Twilio sends a non-number (e.g.
    "anonymous") for withheld numbers, in which case the line is left out and
    the model falls back to asking.
    """
    now = (now or datetime.now(BUSINESS_TZ)).astimezone(BUSINESS_TZ)
    caller_line = (
        f"- The caller is dialing from {caller_phone}.\n"
        if caller_phone and caller_phone.startswith("+")
        else ""
    )
    header = (
        "# Current context\n"
        f"- Right now it is {now:%-I:%M %p} on {now:%A, %B %d, %Y} "
        "(Indianapolis / US Eastern).\n"
        f'- Resolve "today", "tomorrow", and weekday names against this date, '
        f"and ALWAYS use the year {now.year}.\n"
        "- Every date you pass to a tool must be ISO 8601 and must never be in the past.\n"
        f"{caller_line}\n"
    )
    return header + SYSTEM_PROMPT


_PHONE_DESC = "E.164. Omit to use the number the caller is dialing from."
_APPT_ID_DESC = "appointment_id returned by find_appointment"
_FIND_DESC = (
    "Look up the caller's upcoming appointments by phone number. Call this first "
    "whenever they ask about, want to move, or want to cancel an existing booking."
)
_RESCHEDULE_DESC = (
    "Move an existing appointment to a new time. Call ONLY after check_availability "
    "and after the caller confirms the new time verbally."
)
_CANCEL_DESC = "Cancel an existing appointment. Call ONLY after the caller confirms verbally."

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_business_info",
            "description": (
                "Fetch business hours, services list, and prices. "
                "Call once at the start of the call before quoting any price."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": "Check available appointment slots for a service on a date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_id": {"type": "string", "format": "uuid"},
                    "date_iso": {
                        "type": "string",
                        "description": "YYYY-MM-DD",
                        "pattern": r"^\d{4}-\d{2}-\d{2}$",
                    },
                },
                "required": ["service_id", "date_iso"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": (
                "Finalize an appointment. Call ONLY after confirming all fields "
                "with the caller verbally."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service_id": {"type": "string", "format": "uuid"},
                    "scheduled_at_iso": {
                        "type": "string",
                        "description": "ISO 8601 with timezone",
                    },
                    "customer_name": {"type": "string", "minLength": 2},
                    "customer_phone": {"type": "string", "description": _PHONE_DESC},
                    "customer_address": {"type": "string", "minLength": 5},
                    "notes": {"type": "string"},
                },
                "required": [
                    "service_id",
                    "scheduled_at_iso",
                    "customer_name",
                    "customer_address",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_emergency",
            "description": (
                "Trigger an immediate SMS page to the business owner. "
                "Call this on the FIRST user turn that contains any emergency keyword."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string"},
                    "callback_phone": {"type": "string", "description": "E.164"},
                },
                "required": ["reason", "callback_phone"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "transfer_to_human",
            "description": (
                "Gracefully exit the call. Use when the caller asks for a human or "
                "the agent is failing repeatedly."
            ),
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_appointment",
            "description": _FIND_DESC,
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_phone": {"type": "string", "description": _PHONE_DESC},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reschedule_appointment",
            "description": _RESCHEDULE_DESC,
            "parameters": {
                "type": "object",
                "properties": {
                    "appointment_id": {"type": "string", "description": _APPT_ID_DESC},
                    "new_scheduled_at_iso": {
                        "type": "string",
                        "description": "ISO 8601 with timezone",
                    },
                },
                "required": ["appointment_id", "new_scheduled_at_iso"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_appointment",
            "description": _CANCEL_DESC,
            "parameters": {
                "type": "object",
                "properties": {
                    "appointment_id": {"type": "string", "description": _APPT_ID_DESC},
                },
                "required": ["appointment_id"],
            },
        },
    },
]


# Portable schemas passed as ToolsSchema.standard_tools so BOTH the OpenAI/Groq
# adapter and the Gemini adapter convert them natively (the OpenAI-only
# custom_tools dict is invisible to Gemini). JSON-schema keywords Gemini's
# function-declaration validator rejects (format/pattern/minLength) are dropped;
# constraints are restated in the description so the OpenAI/Groq path keeps the
# guidance without the hard keyword.
TOOL_FUNCTION_SCHEMAS = [
    FunctionSchema(
        name="get_business_info",
        description=(
            "Fetch business hours, services list, and prices. "
            "Call once at the start of the call before quoting any price."
        ),
        properties={},
        required=[],
    ),
    FunctionSchema(
        name="check_availability",
        description="Check available appointment slots for a service on a date.",
        properties={
            "service_id": {"type": "string", "description": "Service UUID"},
            "date_iso": {"type": "string", "description": "Date as YYYY-MM-DD"},
        },
        required=["service_id", "date_iso"],
    ),
    FunctionSchema(
        name="book_appointment",
        description=(
            "Finalize an appointment. Call ONLY after confirming all fields "
            "with the caller verbally."
        ),
        properties={
            "service_id": {"type": "string", "description": "Service UUID"},
            "scheduled_at_iso": {"type": "string", "description": "ISO 8601 with timezone"},
            "customer_name": {"type": "string", "description": "Full name (>= 2 chars)"},
            "customer_phone": {"type": "string", "description": _PHONE_DESC},
            "customer_address": {"type": "string", "description": "Service address (>= 5 chars)"},
            "notes": {"type": "string"},
        },
        required=[
            "service_id",
            "scheduled_at_iso",
            "customer_name",
            "customer_address",
        ],
    ),
    FunctionSchema(
        name="escalate_emergency",
        description=(
            "Trigger an immediate SMS page to the business owner. "
            "Call this on the FIRST user turn that contains any emergency keyword."
        ),
        properties={
            "reason": {"type": "string"},
            "callback_phone": {"type": "string", "description": "E.164"},
        },
        required=["reason", "callback_phone"],
    ),
    FunctionSchema(
        name="transfer_to_human",
        description=(
            "Gracefully exit the call. Use when the caller asks for a human or "
            "the agent is failing repeatedly."
        ),
        properties={"reason": {"type": "string"}},
        required=["reason"],
    ),
    FunctionSchema(
        name="find_appointment",
        description=_FIND_DESC,
        properties={"customer_phone": {"type": "string", "description": _PHONE_DESC}},
        required=[],
    ),
    FunctionSchema(
        name="reschedule_appointment",
        description=_RESCHEDULE_DESC,
        properties={
            "appointment_id": {"type": "string", "description": _APPT_ID_DESC},
            "new_scheduled_at_iso": {"type": "string", "description": "ISO 8601 with timezone"},
        },
        required=["appointment_id", "new_scheduled_at_iso"],
    ),
    FunctionSchema(
        name="cancel_appointment",
        description=_CANCEL_DESC,
        properties={"appointment_id": {"type": "string", "description": _APPT_ID_DESC}},
        required=["appointment_id"],
    ),
]
