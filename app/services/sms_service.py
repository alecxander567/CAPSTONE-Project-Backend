# app/services/sms_service.py
import requests
import logging
import os

logger = logging.getLogger(__name__)

SMS_API_URL = "https://sms-api-ph-gceo.onrender.com/send/sms"
SMS_API_KEY = os.getenv("SMS_API_KEY")


def normalize_ph_number(number: str) -> str:
    """Convert 09XXXXXXXXX to +639XXXXXXXXX"""
    number = number.strip().replace(" ", "").replace("-", "")
    if number.startswith("09"):
        return "+63" + number[1:]
    if number.startswith("9") and len(number) == 10:
        return "+63" + number
    return number  # Already in +639 format


def send_sms(phone_number: str, message: str) -> bool:
    if not SMS_API_KEY:
        logger.error("SMS_API_KEY is not set in environment variables")
        return False

    phone_number = normalize_ph_number(phone_number)

    try:
        response = requests.post(
            SMS_API_URL,
            headers={
                "x-api-key": SMS_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "recipient": phone_number,
                "message": message,
            },
            timeout=30,
        )

        data = response.json()

        if response.status_code == 200 and data.get("success"):
            logger.info(f"SMS sent to {phone_number}")
            return True
        else:
            logger.warning(f"SMS failed for {phone_number}: {data}")
            return False

    except requests.exceptions.Timeout:
        logger.error(f"SMS timeout for {phone_number}")
        return False
    except Exception as e:
        logger.error(f"SMS error for {phone_number}: {e}")
        return False
