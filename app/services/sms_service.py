import logging
import os
import re
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

logger = logging.getLogger(__name__)

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")

# Create client once (better performance)
client = None
if all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN]):
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def normalize_ph_number(number: str) -> str:
    """Convert PH local numbers to +639XXXXXXXXX format"""
    if not number:
        return ""

    number = number.strip().replace(" ", "").replace("-", "")

    if number.startswith("09") and len(number) == 11:
        return "+63" + number[1:]

    if number.startswith("9") and len(number) == 10:
        return "+63" + number

    if number.startswith("63") and len(number) == 12:
        return "+" + number

    return number


def is_valid_e164(number: str) -> bool:
    """Check if number follows E.164 format"""
    pattern = r"^\+639\d{9}$"
    return re.match(pattern, number) is not None


def send_sms(phone_number: str, message: str) -> bool:
    if not client or not TWILIO_PHONE_NUMBER:
        logger.error("Twilio credentials not configured properly")
        return False

    phone_number = normalize_ph_number(phone_number)

    # 🚨 Prevent invalid numbers before sending to Twilio
    if not is_valid_e164(phone_number):
        logger.warning(f"Invalid phone format skipped: {phone_number}")
        return False

    try:
        msg = client.messages.create(
            body=message,
            from_=TWILIO_PHONE_NUMBER,
            to=phone_number,
        )

        logger.info(f"SMS sent to {phone_number} — SID: {msg.sid}")
        return True

    except TwilioRestException as e:
        logger.error(
            f"Twilio error for {phone_number} | Code: {e.code} | Message: {e.msg}"
        )
        return False

    except Exception as e:
        logger.error(f"Unexpected SMS error for {phone_number}: {str(e)}")
        return False
