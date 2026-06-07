"""No-dead-air filler — speaks a short bridge phrase when the bot is slow to respond.

Problem: even a fast LLM (~350ms) plus the India→US round-trip and the 1s
utterance-end wait leaves an audible silence after the caller stops talking.
Under rate-limit stalls it's multiple seconds. Production voice agents (Vapi,
Retell, Telo) mask this with a filler the instant the user finishes.

This processor arms a timer on UserStoppedSpeakingFrame. If the bot hasn't begun
responding within `delay_s`, it pushes a short TTSSpeakFrame ("One sec.") so the
caller never hears dead air. The timer is cancelled the moment a real response
starts (LLMFullResponseStartFrame / BotStartedSpeakingFrame) or the caller speaks
again (barge-in). Fillers are kept ultra-short so if the real response lands a
beat later, the overlap still sounds natural.

Placed AFTER the LLM, so it sees both the user-stop signal (flowing downstream)
and the response-start signal (emitted by the LLM composite) promptly.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

import structlog
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    Frame,
    InterruptionFrame,
    LLMFullResponseStartFrame,
    TTSSpeakFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

log = structlog.get_logger(__name__)

# Ultra-short, low-commitment bridges. Short enough that if the real LLM response
# lands a beat later, "One sec.— Sure, I can help with that" still sounds natural.
_FILLERS = ["Mm-hmm.", "One sec.", "Let me check.", "Sure thing.", "Okay,"]


class NoDeadAirFiller(FrameProcessor):
    """Speaks a filler if the bot is silent `delay_s` after the user stops."""

    def __init__(self, *, delay_s: float = 0.6, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._delay_s = delay_s
        self._timer: asyncio.Task | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, UserStoppedSpeakingFrame):
            self._arm()
        elif isinstance(
            frame,
            (
                LLMFullResponseStartFrame,  # real response beginning
                BotStartedSpeakingFrame,  # bot audio already going out
                UserStartedSpeakingFrame,  # caller resumed → barge-in
                InterruptionFrame,
            ),
        ):
            self._disarm()

        await self.push_frame(frame, direction)

    def _arm(self) -> None:
        self._disarm()
        self._timer = asyncio.create_task(self._fire())

    def _disarm(self) -> None:
        if self._timer is not None and not self._timer.done():
            self._timer.cancel()
        self._timer = None

    async def _fire(self) -> None:
        try:
            await asyncio.sleep(self._delay_s)
        except asyncio.CancelledError:
            return
        filler = random.choice(_FILLERS)
        log.debug("filler_spoken", text=filler)
        try:
            await self.push_frame(TTSSpeakFrame(text=filler), FrameDirection.DOWNSTREAM)
        except Exception as exc:  # noqa: BLE001 - never let a filler crash the call
            log.warning("filler_push_failed", error=str(exc))
