import firebase_admin
from firebase_admin import credentials, messaging
import logging
import os
import json
import base64

logger = logging.getLogger(__name__)

_initialized = False


def init_firebase():
    global _initialized
    if not _initialized:
        cred_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
        if cred_json:
            cred_dict = json.loads(base64.b64decode(cred_json))
            cred = credentials.Certificate(cred_dict)
        else:
            cred_path = os.getenv(
                "FIREBASE_CREDENTIALS_PATH", "app/core/firebase-adminsdk.json"
            )
            cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
        _initialized = True


def send_push_notification(device_token: str, title: str, body: str) -> bool:
    try:
        init_firebase()
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            token=device_token,
        )
        response = messaging.send(message)
        logger.info(f"Push notification sent: {response}")
        return True
    except Exception as e:
        logger.error(f"Push notification error: {e}")
        return False
