"""Stress / debug harness for the LLM layer.

Two modes:

  probe  — fire the REAL per-turn payload (system prompt + tool schema +
           a growing synthetic context) at Groq and Gemini and print the
           rate-limit headers. Directly answers "why does Groq 429 after
           one request" and shows Gemini's headroom.

  load   — run N concurrent calls × M turns through the REAL pipeline
           (LLMContextAggregatorPair → SlidingWindowContext →
           FailoverLLMService) against the REAL Gemini/Groq APIs. Reports
           per-call outcome, provider-switch count, latency, and verifies
           the no-dead-air path (apology TTS + EndFrame on total failure).

Usage:
  uv run python scripts/stresstest.py --mode probe --calls 12
  uv run python scripts/stresstest.py --mode load --calls 3 --turns 4
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import statistics
import sys
import time
from pathlib import Path

# Allow `python scripts/stresstest.py` to import the `src` package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import structlog
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.frames.frames import (
    EndFrame,
    EndTaskFrame,
    Frame,
    LLMFullResponseEndFrame,
    LLMRunFrame,
    LLMTextFrame,
    StartFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from src.context_window import SlidingWindowContext
from src.llm_failover import FailoverLLMService
from src.prompts import SYSTEM_PROMPT, TOOL_FUNCTION_SCHEMAS
from src.settings import settings

# ---------------------------------------------------------------------------
# Stub tool handlers for load mode (no Supabase / real DB in stress test).
# Without these, GroqLLMService logs "not registered" on every function call
# and spirals into dozens of re-tries on the same turn.
# ---------------------------------------------------------------------------

_STUB_RESPONSES: dict[str, object] = {
    "get_business_info": {
        "name": "Acme Plumbing",
        "phone": "555-0100",
        "services": [
            {"id": "svc-leak", "name": "Leak Repair", "duration_min": 60},
            {"id": "svc-drain", "name": "Drain Cleaning", "duration_min": 45},
        ],
    },
    "check_availability": [
        {"slot": "2026-05-23T09:00:00", "label": "tomorrow 9 AM"},
        {"slot": "2026-05-23T14:00:00", "label": "tomorrow 2 PM"},
    ],
    "book_appointment": {"status": "confirmed", "confirmation_code": "TEST-001"},
    "escalate_emergency": {"status": "escalated", "eta_min": 30},
    "transfer_to_human": {"status": "transferred"},
}


async def _stub_handler(fn_name: str, params) -> None:  # noqa: ANN001
    await params.result_callback(_STUB_RESPONSES.get(fn_name, {"status": "ok"}))

log = structlog.get_logger("stresstest")

# A few realistic caller turns for the Acme Plumbing receptionist.
CALLER_TURNS = [
    "Hi, my kitchen sink is leaking pretty bad under the cabinet.",
    "It started this morning, there's water pooling on the floor.",
    "Tomorrow afternoon would work. My name is Jordan, phone 555-0142.",
    "The address is 12 Maple Street. Yes that's correct, please book it.",
    "Great, thanks so much. That's all I needed.",
    "Actually, do you also handle water heaters?",
]


# --------------------------------------------------------------------------
# probe mode
# --------------------------------------------------------------------------


def _payload_messages(growth: int) -> list[dict]:
    """System prompt + a synthetic conversation that grows each request —
    mirrors the un-windowed accumulation that triggered the original 429."""
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    for i in range(growth):
        msgs.append({"role": "user", "content": CALLER_TURNS[i % len(CALLER_TURNS)]})
        msgs.append({"role": "assistant", "content": "Sure, I can help with that. " * 6})
    msgs.append({"role": "user", "content": "What times are available tomorrow?"})
    return msgs


def _groq_tools() -> list[dict]:
    return [{"type": "function", "function": t.to_default_dict()} for t in TOOL_FUNCTION_SCHEMAS]


async def probe(calls: int) -> None:
    from groq import Groq

    if not settings.groq_api_key:
        log.error("probe_skip", reason="GROQ_API_KEY missing")
        return

    client = Groq(api_key=settings.groq_api_key)
    log.info("probe_start", provider="groq", model=settings.groq_model, requests=calls)

    for i in range(calls):
        # Each request carries a larger context, exactly like the un-windowed
        # production path did (2 LLM calls per turn, context never trimmed).
        messages = _payload_messages(growth=i)
        t0 = time.monotonic()
        try:
            raw = client.chat.completions.with_raw_response.create(
                model=settings.groq_model,
                messages=messages,
                tools=_groq_tools(),
                max_tokens=settings.llm_max_tokens,
                temperature=settings.llm_temperature,
            )
            dt = (time.monotonic() - t0) * 1000
            h = raw.headers
            log.info(
                "probe_req",
                n=i + 1,
                status=raw.status_code,
                ms=round(dt),
                approx_msgs=len(messages),
                rl_req_remaining=h.get("x-ratelimit-remaining-requests"),
                rl_tok_remaining=h.get("x-ratelimit-remaining-tokens"),
                rl_reset_tok=h.get("x-ratelimit-reset-tokens"),
                retry_after=h.get("retry-after"),
            )
        except Exception as exc:  # noqa: BLE001
            dt = (time.monotonic() - t0) * 1000
            status = getattr(getattr(exc, "response", None), "status_code", "?")
            headers = getattr(getattr(exc, "response", None), "headers", {}) or {}
            log.error(
                "probe_req_failed",
                n=i + 1,
                status=status,
                ms=round(dt),
                retry_after=headers.get("retry-after"),
                rl_tok_remaining=headers.get("x-ratelimit-remaining-tokens"),
                error=str(exc)[:200],
            )
            log.info(
                "probe_conclusion",
                msg=(
                    f"Groq failed on request #{i + 1}. With the OLD un-windowed "
                    "path each conversational turn was ~2 of these (growing) "
                    "requests — hence '429 after one turn'. The sliding window "
                    "+ Gemini-primary now avoids this."
                ),
            )
            return

    log.info("probe_done", note="no 429 hit within the probe budget")


# --------------------------------------------------------------------------
# load mode
# --------------------------------------------------------------------------


class _TurnInjector(FrameProcessor):
    """Drives one synthetic call: feeds a user turn, waits for the assistant
    turn to finish, repeats."""

    def __init__(self, call_id: int, turns: int) -> None:
        super().__init__()
        self._call_id = call_id
        self._turns = turns
        self._turn_done = asyncio.Event()
        self.saw_text = False
        self.saw_apology = False
        self.saw_endframe = False
        self.reply_chars = 0
        self._driver: asyncio.Task | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)

        if isinstance(frame, StartFrame) and self._driver is None:
            self._driver = asyncio.create_task(self._run())

    async def _run(self) -> None:
        for t in range(self._turns):
            text = CALLER_TURNS[t % len(CALLER_TURNS)]
            self._turn_done.clear()
            await self.push_frame(
                TranscriptionFrame(
                    text=text,
                    user_id=f"caller-{self._call_id}",
                    timestamp="",
                    finalized=True,
                ),
                FrameDirection.DOWNSTREAM,
            )
            await self.push_frame(LLMRunFrame(), FrameDirection.DOWNSTREAM)
            try:
                await asyncio.wait_for(self._turn_done.wait(), timeout=30)
            except TimeoutError:
                log.error("call_turn_timeout", call=self._call_id, turn=t + 1)
                break
        await self.push_frame(EndTaskFrame(), FrameDirection.UPSTREAM)


class _TurnObserver(FrameProcessor):
    """Watches the assistant's downstream output at the end of the pipeline
    and updates the injector's state accordingly."""

    def __init__(self, injector: _TurnInjector, assistant_agg: LLMAssistantAggregator) -> None:
        super().__init__()
        self._injector = injector
        self._assistant_agg = assistant_agg

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        log.info("observer_frame", frame=type(frame).__name__, dir=str(direction))

        if direction == FrameDirection.DOWNSTREAM:
            if isinstance(frame, LLMTextFrame):
                self._injector.saw_text = True
                self._injector.reply_chars += len(frame.text)
            elif isinstance(frame, TTSSpeakFrame):
                self._injector.saw_apology = True
            elif isinstance(frame, EndFrame):
                self._injector.saw_endframe = True
            elif isinstance(frame, LLMFullResponseEndFrame):
                if not self._assistant_agg.has_function_calls_in_progress:
                    self._injector._turn_done.set()

        await self.push_frame(frame, direction)


async def _one_call(call_id: int, turns: int) -> dict:
    context = LLMContext(
        messages=[{"role": "system", "content": SYSTEM_PROMPT}],
        tools=ToolsSchema(standard_tools=TOOL_FUNCTION_SCHEMAS),
    )
    agg = LLMContextAggregatorPair(context)
    llm = FailoverLLMService(
        gemini_api_key=settings.gemini_api_key,
        gemini_model=settings.gemini_model,
        groq_api_key=settings.groq_api_key,
        groq_model=settings.groq_model,
        max_tokens=settings.llm_max_tokens,
        temperature=settings.llm_temperature,
        max_retries=settings.llm_failover_max_retries,
        base_delay_s=settings.llm_failover_base_delay_s,
    )

    # Register stub handlers so function calls resolve instead of spiralling.
    for fn_name in _STUB_RESPONSES:
        llm.register_function(fn_name, functools.partial(_stub_handler, fn_name))

    injector = _TurnInjector(call_id, turns)
    observer = _TurnObserver(injector, agg.assistant())

    pipeline = Pipeline(
        [
            injector,
            agg.user(),
            SlidingWindowContext(max_messages=settings.llm_context_max_messages),
            llm,
            observer,
            agg.assistant(),
        ]
    )
    task = PipelineTask(
        pipeline,
        params=PipelineParams(enable_metrics=True),
        cancel_on_idle_timeout=False,
    )
    t0 = time.monotonic()
    await PipelineRunner(handle_sigint=False).run(task)
    dt = (time.monotonic() - t0) * 1000

    switched = llm._switched
    return {
        "call": call_id,
        "ms": round(dt),
        "got_reply": injector.saw_text,
        "reply_chars": injector.reply_chars,
        "switched_to_groq": switched,
        "spoke_apology": injector.saw_apology,
        "ended_cleanly": injector.saw_endframe,
    }


async def load(calls: int, turns: int) -> None:
    log.info("load_start", calls=calls, turns=turns, primary=settings.gemini_model)
    results = await asyncio.gather(
        *[_one_call(i + 1, turns) for i in range(calls)], return_exceptions=True
    )
    ok = [r for r in results if isinstance(r, dict)]
    for r in results:
        if isinstance(r, dict):
            log.info("call_result", **r)
        else:
            log.error("call_crashed", error=str(r))

    if ok:
        lat = [r["ms"] for r in ok]
        log.info(
            "load_summary",
            calls=len(ok),
            replied=sum(r["got_reply"] for r in ok),
            switched=sum(r["switched_to_groq"] for r in ok),
            apology=sum(r["spoke_apology"] for r in ok),
            p50_ms=round(statistics.median(lat)),
            max_ms=max(lat),
        )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=["probe", "load"], default="load")
    p.add_argument("--calls", type=int, default=3)
    p.add_argument("--turns", type=int, default=4)
    args = p.parse_args()

    if args.mode == "probe":
        asyncio.run(probe(args.calls))
    else:
        asyncio.run(load(args.calls, args.turns))


if __name__ == "__main__":
    main()
