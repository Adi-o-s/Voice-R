# voice-agent

FastAPI + Pipecat voice agent. See the [project root README](../../README.md) for the demo flow and architecture.

## Run

```bash
# From project root (one directory up):
make voice         # uvicorn :8000 with reload
make tunnel        # ngrok in another terminal
```

Or directly:

```bash
uv sync
uv run uvicorn src.main:app --reload --port 8000
```

## Test

```bash
uv run pytest
```

## Files

| File | Purpose |
|---|---|
| `src/main.py` | FastAPI app + Twilio webhooks + WS upgrade |
| `src/pipeline.py` | `build_pipeline()` — Pipecat graph composition |
| `src/tools.py` | 5 LLM tool handlers (book/check/escalate/transfer/info) |
| `src/prompts.py` | `SYSTEM_PROMPT` + `TOOL_SCHEMAS` |
| `src/db.py` | Supabase client wrapper |
| `src/sms.py` | Twilio SMS thin wrapper |
| `src/logging_tap.py` | DB-write side-channel processor for Pipecat |
| `src/settings.py` | pydantic-settings env loader |
| `tests/` | pytest |
