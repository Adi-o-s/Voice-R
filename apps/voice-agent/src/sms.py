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


def send_whatsapp(to: str, body: str) -> str:
    """Send a WhatsApp message. Returns the message SID."""
    from_num = settings.twilio_whatsapp_number or "+14155238886"
    sender = from_num if from_num.startswith("whatsapp:") else f"whatsapp:{from_num}"
    recipient = to if to.startswith("whatsapp:") else f"whatsapp:{to}"
    
    msg = twilio_client().messages.create(
        body=body,
        from_=sender,
        to=recipient,
    )
    return msg.sid
