from datetime import datetime, timedelta
from typing import List

from sqlalchemy.orm import Session

from app.models.device import DeviceState

DEFAULT_DEVICE_ID = "esp32-default"
DEVICE_STALE_SECONDS = 15
MODE_STALE_SECONDS = 25


def get_device_state(db: Session, device_id: str = DEFAULT_DEVICE_ID) -> DeviceState:
    state = db.query(DeviceState).filter(DeviceState.device_id == device_id).first()
    if not state:
        state = DeviceState(
            device_id=device_id,
            mode="idle",
            mode_updated_at=datetime.utcnow(),
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
    devices = get_all_device_states(db)
    for d in devices:
        d.mode = mode
        d.mode_updated_at = datetime.utcnow()
    db.commit()


def set_device_mode(db: Session, state: DeviceState, mode: str) -> None:
    state.mode = mode
    state.mode_updated_at = datetime.utcnow()


def set_active_event_on_all_devices(db: Session, event_id: int | None) -> None:
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
    from fastapi import HTTPException

    for state in get_all_device_states(db):
        if state.mode == "idle" or state.mode == requested_mode:
            continue
        if not is_device_online(state):
            continue
        current_label = MODE_LABELS.get(state.mode, state.mode)
        raise HTTPException(
            status_code=409,
            detail=f"{current_label} mode is currently ongoing on {state.device_id}. Please wait until it finishes.",
        )


def heal_stale_device_modes(db: Session) -> int:
    from app.models.user import User, FingerprintStatus, EnrollmentStep

    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=MODE_STALE_SECONDS)
    healed = 0

    for state in get_all_device_states(db):
        if state.mode == "idle":
            continue
        if state.mode_updated_at and state.mode_updated_at >= cutoff:
            continue

        stuck_mode = state.mode
        state.mode = "idle"
        state.mode_updated_at = now
        state.pending_delete_id = None
        state.pending_delete_user_id = None
        state.pending_delete_updated_at = None
        state.recognition_target_id = None
        state.recognition_finger_id = None
        state.recognition_matched = None
        state.recognition_updated_at = None
        healed += 1

        if stuck_mode == "enroll":
            claimed_users = (
                db.query(User)
                .filter(User.claimed_by_device == state.device_id)
                .filter(User.status == FingerprintStatus.PENDING)
                .all()
            )
            for u in claimed_users:
                u.finger_id = None
                u.enroll_status = EnrollmentStep.NOT_ENROLLED
                u.status = FingerprintStatus.NOT_ENROLLED
                u.claimed_by_device = None

    if healed:
        db.commit()
    return healed
