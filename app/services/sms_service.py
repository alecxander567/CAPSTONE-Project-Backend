# app/services/sms_service.py
import logging
import os
from twilio.rest import Client

logger = logging.getLogger(__name__)

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")


def normalize_ph_number(number: str) -> str:
    """Convert 09XXXXXXXXX to +639XXXXXXXXX"""
    number = number.strip().replace(" ", "").replace("-", "")
    if number.startswith("09"):
        return "+63" + number[1:]
    if number.startswith("9") and len(number) == 10:
        return "+63" + number
    return number  


def send_sms(phone_number: str, message: str) -> bool:
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER]):
        logger.error("Twilio credentials are not set in environment variables")
        return False

    phone_number = normalize_ph_number(phone_number)

    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

        msg = client.messages.create(
            body=message,
            from_=TWILIO_PHONE_NUMBER,
            to=phone_number,
        )

        logger.info(f"SMS sent to {phone_number} — SID: {msg.sid}")
        return True

    except Exception as e:
        logger.error(f"SMS error for {phone_number}: {e}")
        return False
