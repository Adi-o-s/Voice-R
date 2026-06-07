"""Unit tests for the LLM-layer debug fixes (ADR-005).

No network: SlidingWindowContext trimming is pure; FailoverLLMService switch
logic is exercised via fake children so the real Gemini/Groq APIs aren't hit.
"""

from __future__ import annotations

import pytest
from pipecat.frames.frames import ErrorFrame, LLMContextFrame

from src.context_window import SlidingWindowContext
from src.llm_failover import FailoverLLMService, _is_failover_now, _is_transient

# --- context window -------------------------------------------------------


def _msgs(n: int) -> list[dict]:
    out = [{"role": "system", "content": "sys"}]
    for i in range(n):
        out.append({"role": "user", "content": f"u{i}"})
        out.append({"role": "assistant", "content": f"a{i}"})
    return out


def test_window_keeps_system_and_bounds_length() -> None:
    win = SlidingWindowContext(max_messages=6)
    trimmed = win._trim(_msgs(20))
    assert trimmed[0] == {"role": "system", "content": "sys"}
    # system + at most 6 non-system
    assert sum(1 for m in trimmed if m["role"] != "system") <= 6
    # most recent turn survives
    assert trimmed[-1] == {"role": "assistant", "content": "a19"}


def test_window_noop_when_short() -> None:
    win = SlidingWindowContext(max_messages=50)
    msgs = _msgs(3)
    assert win._trim(msgs) == msgs


def test_window_never_starts_on_orphan_tool_result() -> None:
    win = SlidingWindowContext(max_messages=3)
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "book it"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "tool_call_id": "1", "content": "ok"},
        {"role": "assistant", "content": "done"},
    ]
    trimmed = win._trim(msgs)
    non_system = [m for m in trimmed if m["role"] != "system"]
    assert non_system[0]["role"] != "tool"  # no dangling tool result


# --- transient classification ---------------------------------------------


@pytest.mark.parametrize(
    "msg,expected",
    [
        ("503 service unavailable", True),
        ("completion timeout", True),
        ("invalid api key", False),
        ("bad request: malformed tool schema", False),
        # 429 is NOT transient — it's a failover_now error (retry window is minutes)
        ("Error during completion: 429 Too Many Requests", False),
        ("RESOURCE_EXHAUSTED: quota exceeded", False),
    ],
)
def test_is_transient(msg: str, expected: bool) -> None:
    assert _is_transient(None, msg) is expected


@pytest.mark.parametrize(
    "msg,expected",
    [
        ("Error during completion: 429 Too Many Requests", True),
        ("RESOURCE_EXHAUSTED: quota exceeded", True),
        ("rate limit exceeded", True),
        ("503 service unavailable", False),
        ("invalid api key", False),
    ],
)
def test_is_failover_now(msg: str, expected: bool) -> None:
    assert _is_failover_now(None, msg) is expected


# --- failover switch logic ------------------------------------------------


class _FakeChild:
    """Stand-in for a child LLM service: optionally reports an error via the
    composite's on_error handler, exactly like the real services do."""

    def __init__(self, composite: FailoverLLMService, *, error: str | None) -> None:
        self._composite = composite
        self._error = error
        self.calls = 0

    async def process_frame(self, frame, direction) -> None:  # noqa: ANN001
        self.calls += 1
        if self._error is not None:
            self._composite._on_child_error(self, ErrorFrame(error=self._error, exception=None))


def _make_service() -> FailoverLLMService:
    return FailoverLLMService(
        gemini_api_key="x",
        gemini_model="gemini-2.0-flash",
        groq_api_key="x",
        groq_model="llama-3.1-8b-instant",
        max_retries=2,
        base_delay_s=0.0,  # no real sleeping in tests
    )


@pytest.mark.asyncio
async def test_attempt_succeeds_no_switch() -> None:
    svc = _make_service()
    good = _FakeChild(svc, error=None)
    ok = await svc._attempt(good, LLMContextFrame(context=None), is_primary=True)
    assert ok is True
    assert good.calls == 1


@pytest.mark.asyncio
async def test_primary_retries_then_fails_transient() -> None:
    # 503 is transient → retries up to max_retries
    svc = _make_service()
    bad = _FakeChild(svc, error="503 service unavailable")
    ok = await svc._attempt(bad, LLMContextFrame(context=None), is_primary=True)
    assert ok is False
    assert bad.calls == svc._max_retries + 1


@pytest.mark.asyncio
async def test_primary_failover_now_skips_retries() -> None:
    # 429 is failover_now → no retries, single attempt only
    svc = _make_service()
    bad = _FakeChild(svc, error="429 rate limit exceeded")
    ok = await svc._attempt(bad, LLMContextFrame(context=None), is_primary=True)
    assert ok is False
    assert bad.calls == 1  # no retries — fail fast to Groq


@pytest.mark.asyncio
async def test_non_transient_does_not_retry() -> None:
    svc = _make_service()
    bad = _FakeChild(svc, error="invalid api key")
    ok = await svc._attempt(bad, LLMContextFrame(context=None), is_primary=True)
    assert ok is False
    assert bad.calls == 1  # no retries on a non-transient error


@pytest.mark.asyncio
async def test_fallback_attempt_runs_once() -> None:
    svc = _make_service()
    fb = _FakeChild(svc, error="429")
    ok = await svc._attempt(fb, LLMContextFrame(context=None), is_primary=False)
    assert ok is False
    assert fb.calls == 1  # fallback never retries
