"""Tool-handler unit tests — signatures, plus behaviour against an in-memory Supabase fake."""

import inspect
from datetime import UTC, datetime, timedelta

import pytest

from src import tools
from src.prompts import BUSINESS_TZ


@pytest.mark.parametrize(
    "fn_name",
    [
        "get_business_info",
        "check_availability",
        "book_appointment",
        "escalate_emergency",
        "transfer_to_human",
        "find_appointment",
        "reschedule_appointment",
        "cancel_appointment",
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
        "customer_address",
    }
    assert required.issubset(public_params)
    assert sig.parameters["customer_phone"].default is None


def test_escalate_signature():
    sig = inspect.signature(tools.escalate_emergency)
    public_params = {p for p in sig.parameters if not p.startswith("_")}
    assert {"reason", "callback_phone"}.issubset(public_params)


# --- behaviour against an in-memory Supabase ------------------------------------

CALLER = "+15550100142"


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


class _Query:
    """Just enough of the supabase-py builder for the filters tools.py uses."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self._filters: list = []
        self._insert: dict | None = None
        self._patch: dict | None = None
        self._order: str | None = None
        self._limit: int | None = None

    def select(self, *_cols):
        return self

    def insert(self, row):
        self._insert = row
        return self

    def update(self, patch):
        self._patch = patch
        return self

    def eq(self, col, val):
        self._filters.append(lambda r: r.get(col) == val)
        return self

    def neq(self, col, val):
        self._filters.append(lambda r: r.get(col) != val)
        return self

    def gte(self, col, val):
        self._filters.append(lambda r: _ts(r[col]) >= _ts(val))
        return self

    def lt(self, col, val):
        self._filters.append(lambda r: _ts(r[col]) < _ts(val))
        return self

    def order(self, col):
        self._order = col
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        if self._insert is not None:
            row = {"id": f"appt-{len(self._rows) + 1}", "status": "confirmed", **self._insert}
            self._rows.append(row)
            return _Result([row])
        matched = [r for r in self._rows if all(f(r) for f in self._filters)]
        if self._patch is not None:
            for r in matched:
                r.update(self._patch)
        if self._order:
            matched.sort(key=lambda r: _ts(r[self._order]))
        return _Result(matched[: self._limit] if self._limit else matched)


class _Result:
    def __init__(self, data: list[dict]) -> None:
        self.data = data


class _Supa:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict]] = {"appointments": [], "calls": []}

    def table(self, name: str) -> _Query:
        return _Query(self.tables[name])


def _next_monday(hour: int) -> datetime:
    now = datetime.now(BUSINESS_TZ)
    monday = now + timedelta(days=7 - now.weekday())
    return monday.replace(hour=hour, minute=0, second=0, microsecond=0)


def _utc_iso(when: datetime) -> str:
    """How Postgres hands a timestamptz back."""
    return when.astimezone(UTC).isoformat()


@pytest.fixture
def db(monkeypatch):
    fake = _Supa()
    texts: list[tuple[str, str]] = []
    monkeypatch.setattr(tools, "supa", lambda: fake)
    monkeypatch.setattr(
        tools,
        "_business_cache",
        {
            "id": "biz-1",
            "name": "Acme Plumbing",
            "business_hours": {"mon": [8, 18], "sun": None},
        },
    )
    monkeypatch.setattr(tools, "send_sms", lambda to, body: texts.append((to, body)))

    def _no_whatsapp(*_args):
        raise RuntimeError("sandbox not joined")

    monkeypatch.setattr(tools, "send_whatsapp", _no_whatsapp)
    fake.texts = texts
    return fake


def _seed(db, *, hour=10, phone=CALLER, status="confirmed", appt_id="appt-seed") -> dict:
    row = {
        "id": appt_id,
        "status": status,
        "customer_phone": phone,
        "customer_name": "Aditya",
        "customer_address": "12 Maple Street",
        "confirmation_code": "ACM-SEED01",
        "service_id": "svc-leak",
        "services": {"name": "Leak repair"},
        "scheduled_at": _utc_iso(_next_monday(hour)),
    }
    db.tables["appointments"].append(row)
    return row


async def _book(**overrides) -> dict:
    args = {
        "service_id": "svc-leak",
        "scheduled_at_iso": _next_monday(10).isoformat(),
        "customer_name": "Aditya",
        "customer_address": "12 Maple Street",
        "_caller_phone": CALLER,
    }
    return await tools.book_appointment(**{**args, **overrides})


@pytest.mark.asyncio
async def test_book_uses_caller_id_when_phone_omitted(db):
    result = await _book()
    assert db.tables["appointments"][0]["customer_phone"] == CALLER
    assert db.texts[0][0] == CALLER
    assert result["sms_sent"] is True
    assert result["whatsapp_sent"] is False


@pytest.mark.asyncio
async def test_book_prefers_a_usable_dictated_number(db):
    await _book(customer_phone="98765 43210")
    assert db.tables["appointments"][0]["customer_phone"] == "+919876543210"


@pytest.mark.asyncio
async def test_book_falls_back_to_caller_id_on_garbage_number(db):
    await _book(customer_phone="five five five")
    assert db.tables["appointments"][0]["customer_phone"] == CALLER


@pytest.mark.asyncio
async def test_book_without_any_phone_asks_instead_of_inventing(db):
    result = await _book(_caller_phone="anonymous")
    assert result["error"] == "missing_phone"
    assert db.tables["appointments"] == []


@pytest.mark.asyncio
async def test_availability_blocks_the_local_hour_not_the_utc_hour(db):
    _seed(db, hour=10)
    day = _next_monday(10)
    slots = (await tools.check_availability("svc-leak", f"{day:%Y-%m-%d}"))["available_slots"]
    hours = {datetime.fromisoformat(s).hour for s in slots}
    assert 10 not in hours
    assert {8, 9, 11}.issubset(hours)


@pytest.mark.asyncio
async def test_cancelled_appointment_frees_its_slot(db):
    _seed(db, hour=8, status="cancelled")
    day = _next_monday(8)
    slots = (await tools.check_availability("svc-leak", f"{day:%Y-%m-%d}"))["available_slots"]
    assert datetime.fromisoformat(slots[0]).hour == 8


@pytest.mark.asyncio
async def test_find_returns_only_the_callers_upcoming_confirmed(db):
    _seed(db, appt_id="mine")
    _seed(db, appt_id="cancelled", status="cancelled")
    _seed(db, appt_id="someone-else", phone="+15550001111")
    past = _seed(db, appt_id="past")
    past["scheduled_at"] = _utc_iso(datetime.now(BUSINESS_TZ) - timedelta(days=2))

    found = (await tools.find_appointment(_caller_phone=CALLER))["appointments"]
    assert [a["appointment_id"] for a in found] == ["mine"]
    assert found[0]["service_name"] == "Leak repair"
    assert datetime.fromisoformat(found[0]["scheduled_at_iso"]).hour == 10


@pytest.mark.asyncio
async def test_find_without_a_number_returns_nothing(db):
    _seed(db)
    result = await tools.find_appointment(_caller_phone="unknown")
    assert result["appointments"] == []
    assert "note" in result


@pytest.mark.asyncio
async def test_reschedule_moves_the_appointment_and_texts_the_customer(db):
    row = _seed(db, hour=10)
    new_time = _next_monday(14)
    result = await tools.reschedule_appointment("appt-seed", new_time.isoformat())
    assert result["rescheduled"] is True
    assert _ts(row["scheduled_at"]) == new_time
    assert db.texts[-1][0] == CALLER


@pytest.mark.asyncio
async def test_reschedule_rejects_a_taken_slot(db):
    row = _seed(db, hour=10)
    _seed(db, hour=14, appt_id="other", phone="+15550001111")
    before = row["scheduled_at"]
    result = await tools.reschedule_appointment("appt-seed", _next_monday(14).isoformat())
    assert result["error"] == "slot_taken"
    assert row["scheduled_at"] == before


@pytest.mark.asyncio
async def test_reschedule_to_its_own_slot_is_not_a_conflict(db):
    _seed(db, hour=10)
    result = await tools.reschedule_appointment("appt-seed", _next_monday(10).isoformat())
    assert result["rescheduled"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("new_time", "error"),
    [
        (lambda: datetime.now(BUSINESS_TZ) - timedelta(days=1), "past_date"),
        (lambda: _next_monday(20), "outside_hours"),
        (lambda: _next_monday(10) + timedelta(days=6), "outside_hours"),  # Sunday: closed
    ],
)
async def test_reschedule_rejects_bad_times(db, new_time, error):
    _seed(db, hour=10)
    result = await tools.reschedule_appointment("appt-seed", new_time().isoformat())
    assert result["error"] == error


@pytest.mark.asyncio
async def test_reschedule_and_cancel_reject_unknown_or_cancelled_ids(db):
    _seed(db, status="cancelled")
    when = _next_monday(14).isoformat()
    assert (await tools.reschedule_appointment("appt-seed", when))["error"] == "not_found"
    assert (await tools.reschedule_appointment("made-up", when))["error"] == "not_found"
    assert (await tools.cancel_appointment("made-up"))["error"] == "not_found"


@pytest.mark.asyncio
async def test_cancel_marks_cancelled_and_texts_the_customer(db):
    row = _seed(db)
    result = await tools.cancel_appointment("appt-seed")
    assert result["cancelled"] is True
    assert row["status"] == "cancelled"
    assert "cancelled" in db.texts[-1][1]
    assert (await tools.find_appointment(_caller_phone=CALLER))["appointments"] == []
