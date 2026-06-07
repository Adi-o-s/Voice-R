"""Gemini-primary / Groq-fallback composite LLM service.

ADR-005: Gemini 2.0 Flash is the runtime LLM. Groq is the warm fallback.

`GoogleLLMService` and `GroqLLMService` both swallow API errors into an
`on_error` event + an upstream `ErrorFrame` (they never raise out of
`process_frame`). So this composite:

  * owns both services as real, set-up child `FrameProcessor`s (NOT pipeline
    nodes);
  * routes every child-pushed frame through a forwarder that strips the
    children's own response-bracketing / error frames, so the composite is the
    single source of `LLMFullResponseStart/EndFrame`;
  * delegates each `LLMContextFrame` to the active child's `process_frame`,
    then inspects the captured `on_error` to decide retry / sticky-switch;
  * on total failure speaks a cached apology and ends the call (no dead air).

Function handlers are registered on BOTH children so tools work regardless of
which provider is live.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

import structlog
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    ErrorFrame,
    Frame,
    InterruptionFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    StartFrame,
    TTSSpeakFrame,
)
from pipecat.processors.frame_processor import (
    FrameDirection,
    FrameProcessor,
    FrameProcessorSetup,
)
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.groq.llm import GroqLLMService
from pipecat.services.llm_service import LLMService
from pipecat.services.settings import LLMSettings

log = structlog.get_logger(__name__)

FALLBACK_LINE = (
    "I'm so sorry — I'm having trouble on my end right now. "
    "Let me have someone call you right back. Goodbye."
)

# Frames the composite itself owns; a child must not be allowed to emit its own
# copies (they would double-bracket / tear down the call early).
_CONTROL_FRAMES = (
    StartFrame,
    EndFrame,
    CancelFrame,
    InterruptionFrame,
    ErrorFrame,
    LLMFullResponseStartFrame,
    LLMFullResponseEndFrame,
)

# google API error classes (imported defensively — package layout varies).
try:  # pragma: no cover - import shim
    from google.api_core.exceptions import (  # type: ignore
        DeadlineExceeded,
        InternalServerError,
        ResourceExhausted,
        ServiceUnavailable,
    )

    _TRANSIENT_EXC: tuple[type[BaseException], ...] = (
        ResourceExhausted,
        DeadlineExceeded,
        ServiceUnavailable,
        InternalServerError,
        TimeoutError,
        asyncio.TimeoutError,
    )
except Exception:  # pragma: no cover
    _TRANSIENT_EXC = (TimeoutError, asyncio.TimeoutError)

# Errors worth retrying (short-lived server hiccups).
_TRANSIENT_TOKENS = ("timeout", "unavailable", "503", "500", "internal")

# Errors that should trigger immediate failover — retrying wastes quota and adds dead air.
# 429 rate-limit windows are minutes long; no point sleeping 0.3s and trying again.
_FAILOVER_NOW_TOKENS = ("429", "rate limit", "quota", "exhausted", "resource_exhausted")


def _is_transient(exc: BaseException | None, msg: str) -> bool:
    if exc is not None and isinstance(exc, _TRANSIENT_EXC):
        return True
    text = f"{msg} {exc}".lower()
    return any(tok in text for tok in _TRANSIENT_TOKENS)


def _is_failover_now(exc: BaseException | None, msg: str) -> bool:
    """True for errors that should skip retries and go straight to fallback.

    Rate-limit windows last minutes — retrying with 0.3s backoff just wastes
    quota and adds dead air. Fail fast and let Groq handle the call.
    """
    text = f"{msg} {exc}".lower()
    return any(tok in text for tok in _FAILOVER_NOW_TOKENS)


class _ChildFrameForwarder(FrameProcessor):
    """Sink for a child service: re-pushes content frames through the composite,
    drops control/bracketing/error frames (the composite owns those)."""

    def __init__(self, composite: FailoverLLMService, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._composite = composite

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, _CONTROL_FRAMES):
            return
        await self._composite.push_frame(frame, direction)


class FailoverLLMService(LLMService):
    """Composite LLM: Gemini primary, Groq fallback, sticky after switch."""

    def __init__(
        self,
        *,
        gemini_api_key: str,
        gemini_model: str,
        groq_api_key: str,
        groq_model: str,
        max_tokens: int = 300,
        temperature: float = 0.4,
        max_retries: int = 2,
        base_delay_s: float = 0.3,
        **kwargs: Any,
    ) -> None:
        # Populate the LLMService settings store so pipecat's validate_complete()
        # doesn't log an error. The composite itself never uses these directly —
        # all actual inference goes through the child services.
        super().__init__(
            settings=LLMSettings(
                model=gemini_model,  # primary model for display / metrics
                system_instruction=None,
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=None,
                top_k=None,
                frequency_penalty=None,
                presence_penalty=None,
                seed=None,
                filter_incomplete_user_turns=None,
                user_turn_completion_config=None,
            ),
            **kwargs,
        )

        self._primary = GoogleLLMService(
            api_key=gemini_api_key,
            settings=GoogleLLMService.Settings(
                model=gemini_model,
                temperature=temperature,
                max_tokens=max_tokens,
            ),
        )
        self._fallback = GroqLLMService(
            api_key=groq_api_key,
            settings=GroqLLMService.Settings(
                model=groq_model,
                temperature=temperature,
                max_tokens=max_tokens,
            ),
        )

        self._forwarder = _ChildFrameForwarder(self)
        self._primary.link(self._forwarder)
        self._fallback.link(self._forwarder)

        self._active: LLMService = self._primary
        self._switched = False
        self._max_retries = max_retries
        self._base_delay_s = base_delay_s

        # Set synchronously by the on_error handler during a child's
        # process_frame; read immediately after to detect failure.
        self._child_error: ErrorFrame | None = None
        self._primary.add_event_handler("on_error", self._on_child_error)
        self._fallback.add_event_handler("on_error", self._on_child_error)

    # --- function registration: fan out to both children -------------------

    def register_function(self, function_name: str | None, *args: Any, **kwargs: Any) -> None:
        self._primary.register_function(function_name, *args, **kwargs)
        self._fallback.register_function(function_name, *args, **kwargs)

    def register_direct_function(self, *args: Any, **kwargs: Any) -> None:
        self._primary.register_direct_function(*args, **kwargs)
        self._fallback.register_direct_function(*args, **kwargs)

    # --- lifecycle: set up / tear down both children + forwarder -----------

    async def setup(self, setup: FrameProcessorSetup) -> None:
        await super().setup(setup)
        await self._primary.setup(setup)
        await self._fallback.setup(setup)
        await self._forwarder.setup(setup)

    async def cleanup(self) -> None:
        await self._primary.cleanup()
        await self._fallback.cleanup()
        await self._forwarder.cleanup()
        await super().cleanup()

    def _on_child_error(self, _processor: FrameProcessor, error: ErrorFrame) -> None:
        self._child_error = error

    # --- frame processing --------------------------------------------------

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, (StartFrame, EndFrame, CancelFrame, InterruptionFrame)):
            # Drive both children's internal state, then pass the control frame
            # along the real pipeline exactly once.
            # Primary is optional — if its key is missing / init fails, fall
            # through to Groq silently rather than crashing the whole call.
            try:
                await self._primary.process_frame(frame, direction)
            except Exception as exc:
                if not self._switched:
                    log.warning(
                        "primary_init_failed_switching_to_groq",
                        error=str(exc),
                    )
                    self._switched = True
                    self._active = self._fallback
            await self._fallback.process_frame(frame, direction)
            await self.push_frame(frame, direction)
            return

        if not isinstance(frame, LLMContextFrame):
            await self.push_frame(frame, direction)
            return

        await self.push_frame(LLMFullResponseStartFrame())
        await self.start_processing_metrics()
        try:
            ok = await self._attempt(self._active, frame, is_primary=not self._switched)

            if not ok and not self._switched:
                self._switched = True
                self._active = self._fallback
                log.warning("llm_failover_switch", to="groq", reason="gemini_failed")
                ok = await self._attempt(self._fallback, frame, is_primary=False)

            if not ok:
                log.error("llm_failover_exhausted", both_providers_down=True)
                await self.push_frame(TTSSpeakFrame(text=FALLBACK_LINE))
                await self.push_frame(EndFrame())
        finally:
            await self.stop_processing_metrics()
            await self.push_frame(LLMFullResponseEndFrame())

    async def _attempt(
        self, child: LLMService, frame: LLMContextFrame, *, is_primary: bool
    ) -> bool:
        """Run one child. Retry (primary only) on transient errors with backoff.

        Returns True if the child produced a response without an error.
        """
        attempts = self._max_retries + 1 if is_primary else 1
        for i in range(attempts):
            self._child_error = None
            await child.process_frame(frame, FrameDirection.DOWNSTREAM)
            err = self._child_error
            if err is None:
                return True

            error_msg = err.error or ""
            failover_now = _is_failover_now(err.exception, error_msg)
            transient = not failover_now and _is_transient(err.exception, error_msg)
            log.warning(
                "llm_attempt_failed",
                provider="gemini" if child is self._primary else "groq",
                attempt=i + 1,
                transient=transient,
                failover_now=failover_now,
                error=str(error_msg),
            )
            # Rate-limit: skip remaining retries, fall through to Groq immediately.
            if failover_now:
                return False
            if not (is_primary and transient and i < attempts - 1):
                return False

            delay = self._base_delay_s * (2**i) + random.uniform(0, 0.1)
            await asyncio.sleep(delay)
        return False
