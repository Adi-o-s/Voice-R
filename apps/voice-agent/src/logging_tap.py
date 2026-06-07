"""Conversation logging taps for the Pipecat pipeline.

Two processors used together:
  - UserTranscriptTap: placed before context_agg.user() — captures TranscriptionFrame
    (user_agg consumes it and does not push it downstream).
  - ConversationLogger: placed after llm — captures LLMTextFrame, LLMFullResponseEndFrame,
    MetricsFrame, StartFrame, EndFrame.

Both share state via a ConversationLogger instance passed to UserTranscriptTap.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import structlog
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    LLMFullResponseEndFrame,
    LLMTextFrame,
    MetricsFrame,
    StartFrame,
    TranscriptionFrame,
)
from pipecat.metrics.metrics import TTFBMetricsData
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from src.db import supa
from src.settings import settings as _settings

log = structlog.get_logger(__name__)


class ConversationLogger(FrameProcessor):
    """Placed after llm. Writes calls + transcripts rows to Supabase."""

    def __init__(self, *, call_sid: str, caller_phone: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.call_sid = call_sid
        self.caller_phone = caller_phone

        self._call_id: str | None = None
        self._closed: bool = False
        self._turn_index: int = 0

        self._assistant_text: list[str] = []
        self._assistant_started_at: datetime | None = None

        self._stt_ms: int | None = None
        self._llm_ms: int | None = None
        self._tts_ms: int | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            await self._open_call()
        elif isinstance(frame, (EndFrame, CancelFrame)):
            # EndFrame = graceful end (bot said goodbye). CancelFrame = abrupt
            # hang-up; close here too, before the handler coroutine is cancelled.
            await self._close_call()
        elif isinstance(frame, LLMTextFrame):
            if not self._assistant_started_at:
                self._assistant_started_at = datetime.now(UTC)
            self._assistant_text.append(frame.text)
        elif isinstance(frame, LLMFullResponseEndFrame):
            asyncio.ensure_future(self._flush_assistant_turn())
        elif isinstance(frame, MetricsFrame):
            self._ingest_metrics(frame)

        await self.push_frame(frame, direction)

    # ------------------------------------------------------------------
    # Called by UserTranscriptTap
    # ------------------------------------------------------------------

    async def _log_user_turn(self, frame: TranscriptionFrame) -> None:
        if not self._call_id or not frame.text.strip():
            return
        self._turn_index += 1
        now = datetime.now(UTC)
        try:
            supa().table("transcripts").insert(
                {
                    "call_id": self._call_id,
                    "turn_index": self._turn_index,
                    "role": "user",
                    "text": frame.text,
                    "started_at": now.isoformat(),
                    "ended_at": now.isoformat(),
                    "stt_latency_ms": self._stt_ms,
                }
            ).execute()
            log.debug("user_turn_logged", turn=self._turn_index, text=frame.text[:50])
        except Exception as exc:
            log.warning("user_turn_log_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _open_call(self) -> None:
        try:
            biz = (
                supa()
                .table("businesses")
                .select("id")
                .eq("slug", _settings.business_slug)
                .single()
                .execute()
            )
            business_id = biz.data["id"] if biz.data else None
            row = (
                supa()
                .table("calls")
                .insert(
                    {
                        "business_id": business_id,
                        "twilio_call_sid": self.call_sid,
                        "caller_phone": self.caller_phone,
                    }
                )
                .execute()
            )
            self._call_id = row.data[0]["id"]
            log.info("call_opened", call_id=self._call_id, sid=self.call_sid)
        except Exception as exc:
            log.warning("call_open_failed", error=str(exc))

    async def _flush_assistant_turn(self) -> None:
        if not self._call_id or not self._assistant_text:
            return
        text = "".join(self._assistant_text)
        started = self._assistant_started_at or datetime.now(UTC)
        ended = datetime.now(UTC)
        self._turn_index += 1
        try:
            supa().table("transcripts").insert(
                {
                    "call_id": self._call_id,
                    "turn_index": self._turn_index,
                    "role": "assistant",
                    "text": text,
                    "started_at": started.isoformat(),
                    "ended_at": ended.isoformat(),
                    "llm_latency_ms": self._llm_ms,
                    "tts_latency_ms": self._tts_ms,
                }
            ).execute()
            log.debug("assistant_turn_logged", turn=self._turn_index, chars=len(text))
        except Exception as exc:
            log.warning("assistant_turn_log_failed", error=str(exc))
        finally:
            self._assistant_text = []
            self._assistant_started_at = None

    async def _close_call(self, fallback_outcome: str = "info_only") -> None:
        """Write ended_at + latency_metrics. Sets outcome only if a tool hasn't already."""
        if self._closed or not self._call_id:
            return
        self._closed = True
        now = datetime.now(UTC).isoformat()
        try:
            supa().table("calls").update(
                {
                    "ended_at": now,
                    "latency_metrics": {
                        "stt_ms_p50": self._stt_ms,
                        "llm_ms_p50": self._llm_ms,
                        "tts_ms_p50": self._tts_ms,
                    },
                }
            ).eq("id", self._call_id).execute()
            # Only finalize outcome if no tool already set a terminal one
            # (booked/emergency/dropped). The column defaults to 'in_progress'
            # and is never null, so the old .is_("outcome", null) never matched.
            supa().table("calls").update({"outcome": fallback_outcome}).eq(
                "id", self._call_id
            ).eq("outcome", "in_progress").execute()
            log.info("call_closed", call_id=self._call_id, fallback_outcome=fallback_outcome)
        except Exception as exc:
            log.warning("call_close_failed", error=str(exc))

    def _ingest_metrics(self, frame: MetricsFrame) -> None:
        # Only TTFB (time-to-first-byte/token) is the per-stage latency the budget
        # tracks; route it by the emitting processor's class name. Usage/processing
        # metrics carry token/char counts or whole-turn time, not first-byte latency.
        # NB: pipecat metric objects expose `.processor`, not `.name` — the old
        # `.name` lookup matched nothing, so every latency wrote null.
        for metric in frame.data:
            if not isinstance(metric, TTFBMetricsData):
                continue
            value = metric.value
            if not isinstance(value, (int, float)):
                continue
            ms = int(value * 1000)  # pipecat reports TTFB in seconds
            # Match on collision-free tokens: bare "stt" is a substring of
            # "elevenlab[s tt]sservice", so route on the provider name or the
            # full "Xservice" suffix instead.
            proc = (metric.processor or "").lower()
            if "deepgram" in proc or "sttservice" in proc:
                self._stt_ms = ms
            elif "elevenlabs" in proc or "ttsservice" in proc:
                self._tts_ms = ms
            elif "llm" in proc or "groq" in proc or "google" in proc or "gemini" in proc:
                self._llm_ms = ms


class UserTranscriptTap(FrameProcessor):
    """Placed before context_agg.user(). Captures TranscriptionFrame before it is consumed."""

    def __init__(self, logger: ConversationLogger, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._logger = logger

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        # TranscriptionFrame = final result; InterimTranscriptionFrame = partial.
        # Deepgram never sets frame.finalized=True, so check the type instead.
        if isinstance(frame, TranscriptionFrame) and frame.text.strip():
            asyncio.ensure_future(self._logger._log_user_turn(frame))
        await self.push_frame(frame, direction)


class MetricsTap(FrameProcessor):
    """Placed after tts. The TTS service emits its TTFB MetricsFrame downstream of
    ConversationLogger, which would otherwise never see it (tts_latency_ms stays
    null). This tap feeds those metrics back to the logger. Re-ingesting STT/LLM
    metrics here too is harmless — _ingest_metrics just re-sets the same value."""

    def __init__(self, logger: ConversationLogger, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._logger = logger

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, MetricsFrame):
            self._logger._ingest_metrics(frame)
        await self.push_frame(frame, direction)
