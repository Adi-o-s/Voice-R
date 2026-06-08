"""Pipecat pipeline — Sprint 2 implementation.

Pipecat v1.1.0. No VAD; Deepgram utterance_end drives turn-taking (ADR-004).
TwilioFrameSerializer converts mulaw↔PCM internally, so STT receives linear16 PCM.
Sprint 2 adds 5 LLM tools via llm.register_function() + ToolsSchema.
"""

from __future__ import annotations

import structlog
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.frames.frames import TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.turns.user_stop.speech_timeout_user_turn_stop_strategy import (
    SpeechTimeoutUserTurnStopStrategy,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from starlette.websockets import WebSocket

from src.context_window import SlidingWindowContext
from src.filler import NoDeadAirFiller
from src.llm_failover import FailoverLLMService
from src.logging_tap import ConversationLogger, MetricsTap, UserTranscriptTap
from src.prompts import TOOL_FUNCTION_SCHEMAS, build_system_prompt
from src.settings import settings
from src.tools import (
    book_appointment,
    check_availability,
    escalate_emergency,
    get_business_info,
    transfer_to_human,
)

log = structlog.get_logger(__name__)


async def build_pipeline(
    websocket: WebSocket,
    stream_sid: str,
    call_sid: str,
    caller_phone: str,
) -> tuple[PipelineRunner, PipelineTask, ConversationLogger]:
    """Build Pipecat pipeline for one call. Returns (runner, task, logger).

    Caller: await runner.run(task) to block until call ends.
    """
    serializer = TwilioFrameSerializer(
        stream_sid=stream_sid,
        call_sid=call_sid,
        account_sid=settings.twilio_account_sid,
        auth_token=settings.twilio_auth_token,
    )

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            serializer=serializer,
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=8000,   # mulaw→PCM at 8kHz; STT gets linear16
            audio_out_sample_rate=8000,
            add_wav_header=False,
        ),
    )

    stt = DeepgramSTTService(
        api_key=settings.deepgram_api_key,
        sample_rate=8000,
        # Serializer already converted mulaw→PCM; Deepgram receives linear16 at 8kHz.
        # Turn-taking is driven by SpeechTimeoutUserTurnStopStrategy (see context_agg below),
        # not utterance_end_ms — Pipecat 1.1.0 ignores UtteranceEnd events from Deepgram.
        settings=DeepgramSTTService.Settings(
            model="nova-3",
            interim_results=True,
        ),
    )

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

    tts = ElevenLabsTTSService(
        api_key=settings.elevenlabs_api_key,
        # voice_id and model params are deprecated in Pipecat 1.1.0 — use Settings instead.
        settings=ElevenLabsTTSService.Settings(
            voice=settings.elevenlabs_voice_id,
            model="eleven_flash_v2_5",
        ),
        sample_rate=8000,
    )

    context = LLMContext(
        messages=[{"role": "system", "content": build_system_prompt()}],
        tools=ToolsSchema(standard_tools=TOOL_FUNCTION_SCHEMAS),
    )
    # SpeechTimeoutUserTurnStopStrategy: pure-asyncio turn detection — no ONNX inference.
    # The default LocalSmartTurnAnalyzerV3 runs heavy ONNX inference per 20ms audio chunk
    # which stalls on Render's 0.1 vCPU, so Smart Turn never fires and the 5s fallback
    # timeout commits the turn before Deepgram's final transcript arrives → LLM gets nothing.
    # SpeechTimeoutUserTurnStopStrategy stops the turn 0.6s after the last Deepgram final
    # transcript, with a generous fallback timeout for safety.
    _user_turn_params = LLMUserAggregatorParams(
        user_turn_strategies=UserTurnStrategies(
            stop=[SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.6)],
        ),
        user_turn_stop_timeout=12.0,  # generous fallback if transcript never arrives
    )
    context_agg = LLMContextAggregatorPair(context, user_params=_user_turn_params)

    logger = ConversationLogger(call_sid=call_sid, caller_phone=caller_phone)
    user_tap = UserTranscriptTap(logger=logger)
    metrics_tap = MetricsTap(logger=logger)
    filler = NoDeadAirFiller(delay_s=settings.filler_delay_s)

    # --- Tool handlers (closures capture logger for _call_id) ---------------

    async def _handle_get_business_info(params: FunctionCallParams) -> None:
        result = await get_business_info()
        await params.result_callback(result)

    async def _handle_check_availability(params: FunctionCallParams) -> None:
        result = await check_availability(**params.arguments)
        await params.result_callback(result)

    async def _handle_book_appointment(params: FunctionCallParams) -> None:
        result = await book_appointment(**params.arguments, _call_id=logger._call_id)
        await params.result_callback(result)

    async def _handle_escalate_emergency(params: FunctionCallParams) -> None:
        result = await escalate_emergency(**params.arguments, _call_id=logger._call_id)
        await params.result_callback(result)

    async def _handle_transfer_to_human(params: FunctionCallParams) -> None:
        result = await transfer_to_human(**params.arguments, _call_id=logger._call_id)
        await params.result_callback(result)

    llm.register_function("get_business_info", _handle_get_business_info)
    llm.register_function("check_availability", _handle_check_availability)
    llm.register_function("book_appointment", _handle_book_appointment)
    llm.register_function("escalate_emergency", _handle_escalate_emergency)
    llm.register_function("transfer_to_human", _handle_transfer_to_human)

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_tap,            # captures TranscriptionFrame before user_agg consumes it
            context_agg.user(),
            SlidingWindowContext(max_messages=settings.llm_context_max_messages),
            llm,
            logger,              # captures LLMTextFrame, STT/LLM MetricsFrame, Start/EndFrame
            filler,              # speaks a bridge if the bot is slow → no dead air
            tts,
            metrics_tap,         # feeds TTS TTFB (emitted downstream of logger) back to logger
            transport.output(),
            context_agg.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
            audio_in_sample_rate=8000,
            audio_out_sample_rate=8000,
        ),
        enable_rtvi=False,
    )

    @transport.event_handler("on_client_connected")
    async def _on_connected(transport: FastAPIWebsocketTransport, ws: WebSocket) -> None:
        greeting = await _fetch_greeting()
        await task.queue_frames([TTSSpeakFrame(text=greeting)])
        log.info("greeting_queued", call_sid=call_sid)

    runner = PipelineRunner(handle_sigint=False)
    return runner, task, logger


async def _fetch_greeting() -> str:
    try:
        from src.db import supa

        result = (
            supa()
            .table("businesses")
            .select("greeting")
            .eq("slug", settings.business_slug)
            .single()
            .execute()
        )
        if result.data:
            return result.data["greeting"]
    except Exception:
        pass
    return "Acme Plumbing, this is Mike. How can I help you today?"
