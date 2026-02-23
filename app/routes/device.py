from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from app.core.database import get_db
from app.models.device import DeviceState
from app.utils.device import get_device_state

router = APIRouter()


# ------------------- ESP32 HEARTBEAT -------------------
@router.get("/device/heartbeat")
def device_heartbeat(db: Session = Depends(get_db)):
    state = get_device_state(db)

    state.last_seen = datetime.utcnow()
    db.commit()

    return {"status": "received"}


# ------------------- DEVICE STATUS -------------------
@router.get("/device/status")
def device_status(db: Session = Depends(get_db)):
    state = get_device_state(db)

    if not state.last_seen:
        return {"connected": False}

    if datetime.utcnow() - state.last_seen < timedelta(seconds=10):
        return {"connected": True}

    return {"connected": False}
