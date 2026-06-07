"""Unit tests for NoDeadAirFiller arm/disarm logic.

Live timing (does the filler actually fire mid-call) can only be verified on a
real call. These tests pin the state machine: arm on user-stop, disarm on
response-start / barge-in, and that a fast response cancels the timer before it
fires.
"""

from __future__ import annotations

import asyncio

import pytest
from pipecat.frames.frames import (
    LLMFullResponseStartFrame,
    TTSSpeakFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from src.filler import NoDeadAirFiller


def _make(delay_s: float = 0.05) -> tuple[NoDeadAirFiller, list]:
    """Filler wired to capture frames it pushes downstream."""
    filler = NoDeadAirFiller(delay_s=delay_s)
    pushed: list = []

    async def _capture(frame, direction=FrameDirection.DOWNSTREAM):  # noqa: ANN001
        pushed.append(frame)

    filler.push_frame = _capture  # type: ignore[method-assign]
    return filler, pushed


@pytest.mark.asyncio
async def test_fires_when_bot_stays_silent() -> None:
    filler, pushed = _make(delay_s=0.05)
    await filler.process_frame(UserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await asyncio.sleep(0.12)  # past the delay
    assert any(isinstance(f, TTSSpeakFrame) for f in pushed)


@pytest.mark.asyncio
async def test_response_start_cancels_filler() -> None:
    filler, pushed = _make(delay_s=0.1)
    await filler.process_frame(UserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    # Bot starts responding before the timer elapses → no filler.
    await filler.process_frame(LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM)
    await asyncio.sleep(0.15)
    assert not any(isinstance(f, TTSSpeakFrame) for f in pushed)


@pytest.mark.asyncio
async def test_barge_in_cancels_filler() -> None:
    filler, pushed = _make(delay_s=0.1)
    await filler.process_frame(UserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    # Caller resumes talking → cancel.
    await filler.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await asyncio.sleep(0.15)
    assert not any(isinstance(f, TTSSpeakFrame) for f in pushed)


@pytest.mark.asyncio
async def test_passes_all_frames_through() -> None:
    filler, pushed = _make()
    frame = UserStoppedSpeakingFrame()
    await filler.process_frame(frame, FrameDirection.DOWNSTREAM)
    assert frame in pushed  # original frame always forwarded
