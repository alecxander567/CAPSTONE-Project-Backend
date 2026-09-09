from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.device import DeviceState

DEFAULT_DEVICE_ID = "esp32-default"
DEVICE_STALE_SECONDS = 15
MODE_STALE_SECONDS = 25
RECOGNIZE_STALE_SECONDS = 45


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
            target_device_id=None,
        )
        db.add(state)
        db.commit()
        db.refresh(state)
    return state


def get_all_device_states(db: Session) -> List[DeviceState]:
    return db.query(DeviceState).all()


def get_online_devices(db: Session) -> List[DeviceState]:
    """Get all online devices"""
    states = get_all_device_states(db)
    return [s for s in states if is_device_online(s)]


def get_offline_devices(db: Session) -> List[DeviceState]:
    """Get all offline devices"""
    states = get_all_device_states(db)
    return [s for s in states if not is_device_online(s)]


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


def set_system_target_device(db: Session, device_id: str) -> None:
    """Set the system-wide target device for operations"""
    # Clear previous target devices
    devices = get_all_device_states(db)
    for d in devices:
        d.target_device_id = None

    # Set the new target device
    state = get_device_state(db, device_id)
    state.target_device_id = device_id
    db.commit()


def clear_system_target_device(db: Session) -> None:
    """Clear the system-wide target device"""
    devices = get_all_device_states(db)
    for d in devices:
        d.target_device_id = None
    db.commit()


def get_system_target_device(db: Session) -> Optional[str]:
    """Get the system-wide target device"""
    devices = get_all_device_states(db)
    target_devices = [d.device_id for d in devices if d.target_device_id is not None]
    return target_devices[0] if target_devices else None


MODE_LABELS = {
    "enroll": "Enrollment",
    "delete": "Fingerprint deletion",
    "attendance": "Attendance",
    "recognize": "Recognition test",
}


def ensure_all_devices_free(
    db: Session, requested_mode: str, target_device: Optional[str] = None
) -> None:
    """
    Check if devices are free for operation.
    If target_device is specified, only check that specific device.
    """
    from fastapi import HTTPException

    devices = get_all_device_states(db)

    for state in devices:
        # If target_device is specified, only check that device
        if target_device and state.device_id != target_device:
            continue

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
    recognize_cutoff = now - timedelta(seconds=RECOGNIZE_STALE_SECONDS)
    healed = 0
    healed_recognize_devices: List[str] = []

    for state in get_all_device_states(db):
        if state.mode == "idle":
            continue

        # DO NOT reset devices in attendance mode
        if state.mode == "attendance":
            continue

        if state.mode == "recognize":
            # Recognition has its own (shorter) staleness window, based on
            # whichever timestamp is most recent: when the result last
            # updated, or when the mode was last set. This prevents a
            # device from being stuck in "recognize" indefinitely if the
            # frontend stopped polling before consuming the result.
            ref_time = state.recognition_updated_at or state.mode_updated_at
            if ref_time and ref_time >= recognize_cutoff:
                continue
        else:
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
        state.target_device_id = None
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
                u.target_device = None

        if stuck_mode == "recognize":
            healed_recognize_devices.append(state.device_id)

    if healed:
        db.commit()

    # Invalidate any lingering WS recognition sessions for devices we just
    # healed out of recognize mode, so a late ESP32 result gets ignored
    # as stale instead of resurrecting the old session.
    if healed_recognize_devices:
        from app.routes.fingerprint import ws_manager

        for device_id in healed_recognize_devices:
            ws_manager.invalidate_recognition_session(device_id)

    return healed
