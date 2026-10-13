"""ConversationLogger teardown: a hang-up must close the call row immediately."""

from __future__ import annotations

import pytest
from pipecat.frames.frames import CancelFrame, LLMTextFrame
from pipecat.processors.frame_processor import FrameDirection

from src import logging_tap
from src.logging_tap import ConversationLogger


class _Table:
    def __init__(self, name: str, writes: list) -> None:
        self._name = name
        self._writes = writes

    def insert(self, row):
        self._writes.append((self._name, "insert", row))
        return self

    def update(self, patch):
        self._writes.append((self._name, "update", patch))
        return self

    def eq(self, *_args):
        return self

    def execute(self):
        return self


class _Supa:
    def __init__(self) -> None:
        self.writes: list = []

    def table(self, name: str) -> _Table:
        return _Table(name, self.writes)


@pytest.fixture
def logger(monkeypatch):
    fake = _Supa()
    monkeypatch.setattr(logging_tap, "supa", lambda: fake)
    conv = ConversationLogger(call_sid="CA_test", caller_phone="+15550100142")
    conv._call_id = "call-1"

    async def _drop(frame, direction=FrameDirection.DOWNSTREAM):  # noqa: ANN001
        pass

    conv.push_frame = _drop  # type: ignore[method-assign]
    conv.writes = fake.writes
    return conv


@pytest.mark.asyncio
async def test_hangup_closes_the_call_row(logger) -> None:
    await logger.process_frame(CancelFrame(), FrameDirection.DOWNSTREAM)
    closes = [w for w in logger.writes if w[0] == "calls" and "ended_at" in w[2]]
    assert len(closes) == 1


@pytest.mark.asyncio
async def test_hangup_mid_reply_still_logs_what_mike_was_saying(logger) -> None:
    await logger.process_frame(LLMTextFrame("You're all set, "), FrameDirection.DOWNSTREAM)
    await logger.process_frame(LLMTextFrame("have a good one."), FrameDirection.DOWNSTREAM)
    await logger.process_frame(CancelFrame(), FrameDirection.DOWNSTREAM)

    turns = [w[2] for w in logger.writes if w[0] == "transcripts"]
    assert [t["text"] for t in turns] == ["You're all set, have a good one."]
    assert turns[0]["role"] == "assistant"
    # The turn is written before the row is closed.
    kinds = [w[0] for w in logger.writes]
    assert kinds.index("transcripts") < kinds.index("calls")


@pytest.mark.asyncio
async def test_close_is_written_once_even_if_both_end_paths_fire(logger) -> None:
    await logger.process_frame(CancelFrame(), FrameDirection.DOWNSTREAM)
    await logger._close_call("info_only")
    closes = [w for w in logger.writes if w[0] == "calls" and "ended_at" in w[2]]
    assert len(closes) == 1
