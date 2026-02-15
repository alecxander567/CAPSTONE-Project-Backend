from fastapi import APIRouter
from datetime import datetime, timedelta

router = APIRouter()

last_heartbeat = None


@router.get("/device/heartbeat")
def device_heartbeat():
    global last_heartbeat
    last_heartbeat = datetime.utcnow()
    return {"status": "received"}


@router.get("/device/status")
def device_status():
    global last_heartbeat

    if last_heartbeat is None:
        return {"connected": False}

    # If ESP32 pinged within last 10 seconds → online
    if datetime.utcnow() - last_heartbeat < timedelta(seconds=10):
        return {"connected": True}

    return {"connected": False}
