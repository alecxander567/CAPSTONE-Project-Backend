from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime

from app.core.database import get_db
from app.utils.device import (
    get_device_state,
    get_all_device_states,
    is_device_online,
    DEFAULT_DEVICE_ID,
)

router = APIRouter()


# ------------------- ESP32 HEARTBEAT -------------------
@router.get("/device/heartbeat")
def device_heartbeat(
    device_id: str = DEFAULT_DEVICE_ID,
    db: Session = Depends(get_db),
):
    state = get_device_state(db, device_id)

    state.last_seen = datetime.utcnow()
    db.commit()

    return {"status": "received", "device_id": device_id}


# ------------------- SINGLE DEVICE STATUS -------------------
@router.get("/device/status")
def device_status(
    device_id: str = DEFAULT_DEVICE_ID,
    db: Session = Depends(get_db),
):
    state = get_device_state(db, device_id)
    return {"device_id": device_id, "connected": is_device_online(state)}


# ------------------- ALL DEVICES STATUS (for dashboard) -------------------
@router.get("/device/status-all")
def device_status_all(db: Session = Depends(get_db)):
    states = get_all_device_states(db)
    return [
        {
            "device_id": s.device_id,
            "connected": is_device_online(s),
            "mode": s.mode,
            "last_seen": s.last_seen,
        }
        for s in states
    ]
