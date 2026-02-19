# app/services/sms_service.py
import logging
import requests
import os

logger = logging.getLogger(__name__)

TEXTBELT_API_KEY = os.getenv(
    "TEXTBELT_API_KEY", "textbelt"
)  # "textbelt" is the free demo key


def normalize_ph_number(number: str) -> str:
    """Convert 09XXXXXXXXX to +639XXXXXXXXX"""
    number = number.strip().replace(" ", "").replace("-", "")
    if number.startswith("09"):
        return "+63" + number[1:]
    if number.startswith("9") and len(number) == 10:
        return "+63" + number
    return number


def send_sms(phone_number: str, message: str) -> bool:
    phone_number = normalize_ph_number(phone_number)

    payload = {"phone": phone_number, "message": message, "key": TEXTBELT_API_KEY}

    try:
        response = requests.post("https://textbelt.com/text", data=payload)
        result = response.json()

        if result.get("success"):
            logger.info(f"SMS sent to {phone_number}")
            return True
        else:
            logger.error(f"SMS failed for {phone_number}: {result.get('error')}")
            return False

    except Exception as e:
        logger.error(f"SMS exception for {phone_number}: {e}")
        return False
