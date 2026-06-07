"""Sliding-window context trimmer.

The pipeline never bounded conversation history — every turn resent the full
(growing) message list plus the tool schema, which is what blew the Groq
free-tier token-per-minute cap "after one request". This processor enforces a
hard message window in front of the LLM, provider-neutrally.

Placed between `context_agg.user()` and the LLM. On each `LLMContextFrame` it
keeps the leading system message(s) + the last N non-system messages, and
never leaves a `tool`/`function` result as the first kept message (an orphaned
tool result is rejected by both the OpenAI/Groq and Gemini validators).
"""

from __future__ import annotations

from typing import Any

import structlog
from pipecat.frames.frames import Frame, LLMContextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

log = structlog.get_logger(__name__)


def _role(msg: Any) -> str:
    if isinstance(msg, dict):
        return msg.get("role", "")
    return getattr(msg, "role", "")


class SlidingWindowContext(FrameProcessor):
    def __init__(self, max_messages: int = 20, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._max = max_messages

    def _trim(self, messages: list[Any]) -> list[Any]:
        system = [m for m in messages if _role(m) == "system"]
        rest = [m for m in messages if _role(m) != "system"]
        if len(rest) <= self._max:
            return messages

        window = rest[-self._max :]
        # Don't start the window on an orphaned tool/function result.
        while window and _role(window[0]) in ("tool", "function"):
            window.pop(0)
        return system + window

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMContextFrame):
            before = len(frame.context.get_messages())
            frame.context.transform_messages(self._trim)
            after = len(frame.context.get_messages())
            if after < before:
                log.info("context_trimmed", before=before, after=after)

        await self.push_frame(frame, direction)
