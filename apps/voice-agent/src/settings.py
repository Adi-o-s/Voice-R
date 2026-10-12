"""Centralized config loaded from .env via pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""
    twilio_whatsapp_number: str = ""

    deepgram_api_key: str = ""

    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"

    # LLM tuning + failover (Gemini primary, Groq fallback — see ADR-005).
    llm_max_tokens: int = 300
    llm_temperature: float = 0.4
    # STT splits one spoken sentence into several user messages, so a booking
    # call runs 30+ messages; at 20 the caller's name had scrolled out by the
    # time book_appointment ran and the model invented one.
    llm_context_max_messages: int = 60
    llm_failover_max_retries: int = 2
    llm_failover_base_delay_s: float = 0.3

    # No-dead-air filler: speak a bridge phrase if the bot is silent this long
    # after the caller stops. Tune on a live call — lower = more fillers.
    filler_delay_s: float = 0.6

    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""

    supabase_url: str = ""
    supabase_service_role_key: str = ""

    port: int = 8000
    log_level: str = "INFO"
    business_slug: str = "acme-plumbing"
    public_base_url: str = ""


settings = Settings()
