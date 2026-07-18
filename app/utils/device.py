from datetime import datetime, timedelta
from typing import List

from sqlalchemy.orm import Session

from app.models.device import DeviceState

# Used when a device hits an endpoint without a device_id (e.g. old firmware
# that hasn't been reflashed yet, or the dashboard-only debug endpoints).
DEFAULT_DEVICE_ID = "esp32-default"

DEVICE_STALE_SECONDS = 15  # a bit above HEARTBEAT_MS (10s) with margin


def get_device_state(db: Session, device_id: str = DEFAULT_DEVICE_ID) -> DeviceState:
    """Get or create the state row for one specific physical device."""
    state = db.query(DeviceState).filter(DeviceState.device_id == device_id).first()
    if not state:
        state = DeviceState(
            device_id=device_id,
            mode="idle",
            pending_delete_id=None,
            recognition_target_id=None,
            recognition_finger_id=None,
            recognition_matched=None,
            last_seen=None,
        )
        db.add(state)
        db.commit()
        db.refresh(state)
    return state


def get_all_device_states(db: Session) -> List[DeviceState]:
    return db.query(DeviceState).all()


def is_device_online(state: DeviceState) -> bool:
    return bool(
        state.last_seen
        and datetime.utcnow() - state.last_seen
        <= timedelta(seconds=DEVICE_STALE_SECONDS)
    )


def set_mode_on_all_devices(db: Session, mode: str) -> None:
    """
    Enroll / delete / attendance / recognize are exclusive, system-wide
    operations — every known device should reflect the same mode, since
    the dashboard has one Start/Stop control for the whole fleet, not
    per-device controls.
    """
    devices = get_all_device_states(db)
    for d in devices:
        d.mode = mode
    db.commit()


def set_active_event_on_all_devices(db: Session, event_id: int | None) -> None:
    """
    Attendance mode is exclusive and system-wide (see set_mode_on_all_devices),
    so every device shares the same active event — whichever event the
    dashboard's Start Attendance button was pressed for.
    """
    devices = get_all_device_states(db)
    for d in devices:
        d.active_event_id = event_id
    db.commit()


MODE_LABELS = {
    "enroll": "Enrollment",
    "delete": "Fingerprint deletion",
    "attendance": "Attendance",
    "recognize": "Recognition test",
}


def ensure_all_devices_free(db: Session, requested_mode: str) -> None:
    """
    Raise 409 if ANY known, non-stale device is busy running a different mode.
    Stale (offline) devices are ignored so a dead device can't permanently
    lock out the rest of the fleet.
    """
    from fastapi import HTTPException

    for state in get_all_device_states(db):
        if state.mode == "idle" or state.mode == requested_mode:
            continue
        if not is_device_online(state):
            continue  # stale/offline — ignore, allow override
        current_label = MODE_LABELS.get(state.mode, state.mode)
        raise HTTPException(
            status_code=409,
            detail=f"{current_label} mode is currently ongoing on {state.device_id}. Please wait until it finishes.",
        )
