"""Sprint 1 smoke tests — verify imports and pipeline builds without crashing."""

from __future__ import annotations

import pytest


def test_imports() -> None:
    """All pipeline modules import cleanly."""
    from src.pipeline import build_pipeline  # noqa: F401
    from src.logging_tap import ConversationLogger  # noqa: F401
    from src.prompts import SYSTEM_PROMPT, TOOL_SCHEMAS  # noqa: F401


def test_system_prompt_non_empty() -> None:
    from src.prompts import SYSTEM_PROMPT

    assert len(SYSTEM_PROMPT) > 100
    assert "Mike" in SYSTEM_PROMPT
    assert "plumbing" in SYSTEM_PROMPT.lower()


def test_tool_schemas_structure() -> None:
    from src.prompts import TOOL_SCHEMAS

    assert isinstance(TOOL_SCHEMAS, list)
    for schema in TOOL_SCHEMAS:
        assert "type" in schema or "function" in schema


def test_settings_loads() -> None:
    """Settings loads from .env without raising."""
    from src.settings import settings

    assert settings.groq_model  # non-empty


@pytest.mark.asyncio
async def test_conversation_logger_init() -> None:
    from src.logging_tap import ConversationLogger

    logger = ConversationLogger(call_sid="CA_test", caller_phone="+10000000000")
    assert logger.call_sid == "CA_test"
    assert logger._call_id is None
    assert logger._turn_index == 0
