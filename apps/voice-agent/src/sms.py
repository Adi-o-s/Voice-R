"""Twilio SMS thin wrapper."""

from functools import lru_cache

from twilio.rest import Client

from src.settings import settings


@lru_cache(maxsize=1)
def twilio_client() -> Client:
    return Client(settings.twilio_account_sid, settings.twilio_auth_token)


def send_sms(to: str, body: str) -> str:
    """Send an SMS. Returns the message SID."""
    msg = twilio_client().messages.create(
        body=body,
        from_=settings.twilio_phone_number,
        to=to,
    )
    return msg.sid
