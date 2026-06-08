"""FastAPI app — Twilio webhooks + WS upgrade for Pipecat."""

from __future__ import annotations

import asyncio
import contextlib
import logging

import structlog
from fastapi import FastAPI, Form, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pipecat.runner.utils import parse_telephony_websocket
from twilio.request_validator import RequestValidator
from twilio.rest import Client as TwilioClient

from src.pipeline import build_pipeline
from src.settings import settings

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(level=getattr(logging, settings.log_level))
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)
log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Voice AI Receptionist", version="0.1.0")
_validator = RequestValidator(settings.twilio_auth_token) if settings.twilio_auth_token else None

# In-memory caller-phone store: call_sid → caller_phone
# Populated by /twilio/voice, consumed by /twilio/stream.
_caller_phones: dict[str, str] = {}


@app.on_event("startup")
async def _prewarm_business_cache() -> None:
    """Pre-load the business row into memory at startup.

    get_business_info() is called on the first LLM turn of every call.
    Without this, the Supabase round-trip (~150ms) happens during the call,
    creating a silent window that triggers barge-in from the caller.
    With the cache warm, the tool returns instantly from memory.
    """
    try:
        from src.tools import _get_business
        _get_business()
        log.info("business_cache_warmed")
    except Exception as exc:
        log.warning("business_cache_prewarm_failed", error=str(exc))


def _hangup_twilio_call(call_sid: str) -> None:
    """Actively end the PSTN leg via Twilio REST.

    Without this, when the pipeline tears down (e.g. both LLM providers fail)
    the WebSocket closes server-side but the caller stays on a silent line
    until Twilio's ~60s timeout. Best-effort: never raise.
    """
    if not (settings.twilio_account_sid and settings.twilio_auth_token):
        return
    if not call_sid or call_sid == "unknown":
        return
    try:
        client = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)
        client.calls(call_sid).update(status="completed")
        log.info("twilio_hangup", call_sid=call_sid)
    except Exception as exc:  # noqa: BLE001 - best effort, must not mask original error
        log.warning("twilio_hangup_failed", call_sid=call_sid, error=str(exc))


async def _verify_twilio(request: Request) -> None:
    """Reject requests not signed by Twilio. Skipped in dev if auth_token missing."""
    if _validator is None:
        return
    sig = request.headers.get("X-Twilio-Signature", "")
    url = str(request.url)
    form = dict(await request.form())
    if not _validator.validate(url, form, sig):
        raise HTTPException(403, "Invalid Twilio signature")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.api_route("/healthz", methods=["GET", "HEAD"])
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/twilio/voice")
async def twilio_voice(request: Request) -> Response:
    """Return TwiML opening a Media Stream back to this server."""
    await _verify_twilio(request)
    form = dict(await request.form())
    call_sid: str = form.get("CallSid", "unknown")
    caller_phone: str = form.get("From", "unknown")

    _caller_phones[call_sid] = caller_phone
    log.info("voice_webhook", call_sid=call_sid, from_=caller_phone)

    base = settings.public_base_url.rstrip("/")
    if not base:
        raise HTTPException(500, "PUBLIC_BASE_URL not configured — run ngrok and update .env")

    ws_url = base.replace("https://", "wss://").replace("http://", "ws://")
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response><Connect>"
        f'<Stream url="{ws_url}/twilio/stream/{call_sid}"/>'
        "</Connect></Response>"
    )
    return Response(content=twiml, media_type="application/xml")


@app.websocket("/twilio/stream/{call_sid}")
async def twilio_stream(websocket: WebSocket, call_sid: str) -> None:
    """Handshake with Twilio, then hand the WS to Pipecat for the call's lifetime."""
    await websocket.accept()
    log.info("ws_accepted", call_sid=call_sid)

    logger = None
    outcome = "info_only"
    try:
        # parse_telephony_websocket reads the 'connected' + 'start' messages,
        # detects "twilio", and extracts stream_id + call_id.
        transport_type, call_data = await parse_telephony_websocket(websocket)
        if transport_type != "twilio":
            log.error("unexpected_transport", type=transport_type)
            await websocket.close()
            return

        stream_sid: str = call_data["stream_id"]
        caller_phone: str = _caller_phones.pop(call_sid, "unknown")
        log.info("stream_started", call_sid=call_sid, stream_sid=stream_sid, from_=caller_phone)

        runner, task, logger = await build_pipeline(
            websocket=websocket,
            stream_sid=stream_sid,
            call_sid=call_sid,
            caller_phone=caller_phone,
        )
        await runner.run(task)

    except WebSocketDisconnect:
        log.info("ws_disconnected", call_sid=call_sid)
    except Exception as exc:
        log.error("ws_error", call_sid=call_sid, error=str(exc))
        outcome = "infra_error"
    finally:
        _caller_phones.pop(call_sid, None)
        # The pipeline can tear down without the caller's PSTN leg being told
        # to end (e.g. both LLM providers down). Actively hang up so the caller
        # never sits on a dead line, then close the WS explicitly.
        _hangup_twilio_call(call_sid)
        with contextlib.suppress(Exception):
            await websocket.close()
        # runner.run() only returns when the call ends — close the DB row here
        # regardless of how the pipeline terminated. On an abrupt hang-up Starlette
        # cancels this handler coroutine, so a plain `await` would be cancelled
        # mid-write. shield() lets the close finish even as the handler unwinds.
        if logger is not None:
            with contextlib.suppress(Exception):
                await asyncio.shield(logger._close_call(outcome))


@app.post("/twilio/status")
async def twilio_status(
    request: Request,
    CallSid: str = Form(...),  # noqa: N803
    CallStatus: str = Form(...),  # noqa: N803
) -> Response:
    """Twilio call-lifecycle webhook — update outcome on completion."""
    await _verify_twilio(request)
    log.info("status_webhook", sid=CallSid, status=CallStatus)
    # outcome update handled inside ConversationLogger.process_frame on EndFrame
    return Response(status_code=204)
