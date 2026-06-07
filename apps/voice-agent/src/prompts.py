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

# Phone number handling

- Ask the caller to say their number digit by digit: "Go ahead and say each digit one at a time."
- "double X" means the digit X twice: "double nine" = 99, "double zero" = 00.
- Convert all spoken words to digits before using the number.
- Read the number back as groups: "761-110-0936 — is that right?"
- If it doesn't sound like a 10-digit number, ask once to repeat.

# Conversational script (booking happy path)

1. Caller describes their issue → identify the matching service.
2. Ask for name first, then say: "And your number — go ahead, digit by digit."
3. Ask: "What's the service address?"
4. Ask: "When works best — today, tomorrow, or later this week?"
5. Call `check_availability` for the chosen date and service.
6. Offer up to 3 slots.
7. Read back the full booking and ask for confirmation.
8. Call `book_appointment` only after confirmation.
9. Confirm SMS is on the way and say goodbye.

# Tone

- Warm, brief, slightly southern.
- No corporate-speak.
- Use contractions.
"""


def build_system_prompt(now: datetime | None = None) -> str:
    """SYSTEM_PROMPT with a live date header so the model schedules in the right
    year. Called per-call at pipeline build (not import) so the date is current.
    """
    now = (now or datetime.now(BUSINESS_TZ)).astimezone(BUSINESS_TZ)
    header = (
        "# Current context\n"
        f"- Right now it is {now:%-I:%M %p} on {now:%A, %B %d, %Y} "
        "(Indianapolis / US Eastern).\n"
        f'- Resolve "today", "tomorrow", and weekday names against this date, '
        f"and ALWAYS use the year {now.year}.\n"
        "- Every date you pass to a tool must be ISO 8601 and must never be in the past.\n\n"
    )
    return header + SYSTEM_PROMPT


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
                    "customer_phone": {"type": "string", "description": "E.164"},
                    "customer_address": {"type": "string", "minLength": 5},
                    "notes": {"type": "string"},
                },
                "required": [
                    "service_id",
                    "scheduled_at_iso",
                    "customer_name",
                    "customer_phone",
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
            "customer_phone": {"type": "string", "description": "E.164"},
            "customer_address": {"type": "string", "description": "Service address (>= 5 chars)"},
            "notes": {"type": "string"},
        },
        required=[
            "service_id",
            "scheduled_at_iso",
            "customer_name",
            "customer_phone",
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
]
