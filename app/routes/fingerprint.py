from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.core.database import get_db
from app.models.user import User, FingerprintStatus, EnrollmentStep
from fastapi.responses import PlainTextResponse
import random
from pydantic import BaseModel
from datetime import datetime, timedelta
from app.models.attendance import Attendance, AttendanceStatus
from app.models.events import Event
from app.models.device import DeviceState
from app.utils.device import (
    get_device_state,
    get_all_device_states,
    set_mode_on_all_devices,
    set_active_event_on_all_devices,
    ensure_all_devices_free,
    is_device_online,
    DEFAULT_DEVICE_ID,
)
import pytz

router = APIRouter(prefix="/fingerprints", tags=["Fingerprints"])

ph_tz = pytz.timezone("Asia/Manila")

# How long a pending_delete can stay unresolved before we consider it stale
# and allow the finger_id to be recycled. 5 minutes is generous for any
# realistic ESP32 round-trip.
PENDING_DELETE_TIMEOUT_SECONDS = 300


class EnrollmentRequest(BaseModel):
    user_id: int


class StartAttendanceRequest(BaseModel):
    event_id: int


def log_request(endpoint: str, client_ip: str, extra: str = ""):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {endpoint} | {client_ip} {extra}")


def _finger_ids_in_flight(db: Session) -> set[int]:
    """
    finger_ids that some device still has an outstanding pending_delete for.
    These must NOT be handed out to a new enrollee, even if the owning
    user's row has already been cleared — otherwise a late delete
    confirmation from a slow/offline device can land on the new owner.
    """
    now = datetime.utcnow()
    stale_cutoff = now - timedelta(seconds=PENDING_DELETE_TIMEOUT_SECONDS)
    in_flight = set()
    for s in get_all_device_states(db):
        if s.pending_delete_id is not None:
            # If the pending_delete has been sitting unresolved for too long,
            # treat it as stale and allow the finger_id to be recycled.
            if s.pending_delete_updated_at and s.pending_delete_updated_at < stale_cutoff:
                continue
            in_flight.add(s.pending_delete_id)
    return in_flight


# ------------------- START ENROLLMENT -------------------
@router.post("/start-enrollment")
def start_enrollment(
    request: EnrollmentRequest,
    req: Request,
    db: Session = Depends(get_db),
):
    client_ip = req.client.host
    log_request("START-ENROLLMENT", client_ip, f"| user_id={request.user_id}")

    user = db.query(User).filter(User.id == request.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    ensure_all_devices_free(db, "enroll")

    # Reset previous enrollment state
    if user.status != FingerprintStatus.NOT_ENROLLED:
        user.finger_id = None
        user.enroll_status = EnrollmentStep.NOT_ENROLLED
        user.status = FingerprintStatus.NOT_ENROLLED

    # Generate new finger_id
    existing_ids = {u.finger_id for u in db.query(User.finger_id).all() if u.finger_id}

    # Don't reuse a finger_id that some device still has a pending
    # delete for — it may still be "in flight" from a slow/offline device
    # even though the previous owner's row has already been cleared.
    existing_ids |= _finger_ids_in_flight(db)

    if len(existing_ids) > 1000:
        raise HTTPException(status_code=400, detail="Fingerprint storage is full")

    finger_id = random.randint(1, 1000)
    while finger_id in existing_ids:
        finger_id = random.randint(1, 1000)

    # Set user fields
    user.finger_id = finger_id
    user.enroll_status = EnrollmentStep.PENDING
    user.status = FingerprintStatus.PENDING

    # Set device mode BEFORE commit so both happen atomically
    set_mode_on_all_devices(db, "enroll")

    try:
        db.commit()
        db.refresh(user)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    return {
        "message": "Enrollment started",
        "finger_id": finger_id,
        "status": user.status.value,
        "step": "pending",
    }


# ------------------- ESP32 POLLS FOR PENDING ENROLLMENT -------------------
@router.get("/check-enrollment")
def check_enrollment(
    req: Request,
    device_id: str = DEFAULT_DEVICE_ID,
    db: Session = Depends(get_db),
):
    client_ip = req.client.host

    # First check PENDING users that haven't been claimed by any device yet
    user = (
        db.query(User)
        .filter(User.status == FingerprintStatus.PENDING)
        .filter(User.enroll_status == EnrollmentStep.PENDING)
        .filter(User.claimed_by_device.is_(None))  # not yet claimed
        .order_by(User.id.asc())
        .first()
    )

    if user:
        # Atomically claim this user for this device so no other device
        # picks up the same finger_id
        user.claimed_by_device = device_id
        try:
            db.commit()
        except Exception:
            db.rollback()
            return PlainTextResponse("none")

        log_request(
            "CHECK-ENROLLMENT", client_ip, f"| Found finger_id={user.finger_id} for device={device_id}"
        )
        return PlainTextResponse(str(user.finger_id))

    # Check users in other enrollment steps (resume) — these are already claimed
    user = (
        db.query(User)
        .filter(User.status == FingerprintStatus.PENDING)
        .filter(
            User.enroll_status.in_(
                [
                    EnrollmentStep.PLACE_FINGER,
                    EnrollmentStep.REMOVE_FINGER,
                    EnrollmentStep.PLACE_AGAIN,
                ]
            )
        )
        .filter(User.claimed_by_device == device_id)  # only resume if claimed by THIS device
        .order_by(User.id.asc())
        .first()
    )

    if user:
        log_request(
            "CHECK-ENROLLMENT", client_ip, f"| Resuming finger_id={user.finger_id} on device={device_id}"
        )
        return PlainTextResponse(str(user.finger_id))

    return PlainTextResponse("none")


# ------------------- ESP32 UPDATES STEPS -------------------
@router.get("/update-enrollment")
def update_enrollment(
    req: Request,
    id: int,
    status: str,
    db: Session = Depends(get_db),
):
    client_ip = req.client.host
    log_request("UPDATE-ENROLLMENT", client_ip, f"| finger_id={id} | status={status}")

    if id == 0:
        return PlainTextResponse("invalid_id")

    user = db.query(User).filter(User.finger_id == id).first()
    if not user:
        return PlainTextResponse("error")

    # Guard against stale/late messages from a device.
    if status in ("place_finger", "remove_finger", "place_again", "success", "error"):
        if user.status != FingerprintStatus.PENDING:
            log_request(
                "UPDATE-ENROLLMENT",
                client_ip,
                f"| finger_id={id} | IGNORED stale enroll callback "
                f"(user status={user.status.value})",
            )
            return PlainTextResponse("stale_ignored")

    status_map = {
        "place_finger": (EnrollmentStep.PLACE_FINGER, FingerprintStatus.PENDING),
        "remove_finger": (EnrollmentStep.REMOVE_FINGER, FingerprintStatus.PENDING),
        "place_again": (EnrollmentStep.PLACE_AGAIN, FingerprintStatus.PENDING),
        "success": (EnrollmentStep.SUCCESS, FingerprintStatus.ENROLLED),
        "error": (EnrollmentStep.ERROR, FingerprintStatus.FAILED),
        "delete_success": (EnrollmentStep.NOT_ENROLLED, FingerprintStatus.NOT_ENROLLED),
        "delete_error": (None, None),
    }

    if status not in status_map:
        return PlainTextResponse("invalid_status")

    enroll_step, fingerprint_status = status_map[status]

    if status == "delete_success":
        # Only apply this if some device actually has a pending
        # delete recorded AGAINST THIS USER.
        matching_state = (
            db.query(DeviceState)
            .filter_by(pending_delete_id=id, pending_delete_user_id=user.id)
            .first()
        )

        if matching_state is None:
            log_request(
                "UPDATE-ENROLLMENT",
                client_ip,
                f"| finger_id={id} | IGNORED stale delete_success "
                f"(no matching pending_delete for user_id={user.id})",
            )
            # Clean up any dangling pending_delete_id pointing at this
            # finger_id so it doesn't keep firing.
            for s in get_all_device_states(db):
                if s.pending_delete_id == id:
                    s.pending_delete_id = None
                    s.pending_delete_user_id = None
                    s.pending_delete_updated_at = None
            db.commit()
            return PlainTextResponse("stale_ignored")

        user.enroll_status = enroll_step
        user.status = fingerprint_status
        user.finger_id = None
        user.claimed_by_device = None

        # Clear the pending delete ONLY on the device that confirmed it
        matching_state.pending_delete_id = None
        matching_state.pending_delete_user_id = None
        matching_state.pending_delete_updated_at = None

    elif status == "delete_error":
        # Clear the pending delete so the device doesn't keep retrying
        # and the finger_id can be reused
        for s in get_all_device_states(db):
            if s.pending_delete_id == id:
                s.pending_delete_id = None
                s.pending_delete_user_id = None
                s.pending_delete_updated_at = None
        log_request(
            "UPDATE-ENROLLMENT",
            client_ip,
            f"| finger_id={id} | delete_error — cleared pending_delete",
        )
    else:
        user.enroll_status = enroll_step
        user.status = fingerprint_status

        # On success or error, clear the claimed_by_device so the user
        # can be re-enrolled later
        if status in ("success", "error"):
            user.claimed_by_device = None

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        return PlainTextResponse("error")

    if status in ["success", "error", "delete_success", "delete_error"]:
        set_mode_on_all_devices(db, "idle")

    return PlainTextResponse("updated")


# ------------------- FRONTEND POLLS FOR STATUS -------------------
@router.get("/get-status")
def get_status(
    req: Request,
    finger_id: int,
    db: Session = Depends(get_db),
):
    client_ip = req.client.host

    if not hasattr(get_status, "call_count"):
        get_status.call_count = 0
    get_status.call_count += 1

    if get_status.call_count % 10 == 1:
        log_request("GET-STATUS", client_ip, f"| finger_id={finger_id}")

    user = db.query(User).filter(User.finger_id == finger_id).first()

    if not user:
        return {"status": "failed", "step": "error", "message": "User not found"}

    step = user.enroll_status.value if user.enroll_status else "pending"

    return {
        "status": user.status.value,
        "step": step,
    }


# ------------------- RESET ENROLLMENT -------------------
@router.post("/reset-enrollment/{user_id}")
def reset_enrollment(user_id: int, req: Request, db: Session = Depends(get_db)):
    client_ip = req.client.host
    log_request("RESET-ENROLLMENT", client_ip, f"| user_id={user_id}")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Also clear any pending_delete entries on devices that reference
    # this user, so a stray reset can't be followed by a stale delete
    # confirmation later.
    for s in get_all_device_states(db):
        if s.pending_delete_user_id == user.id:
            s.pending_delete_id = None
            s.pending_delete_user_id = None
            s.pending_delete_updated_at = None

    user.finger_id = None
    user.enroll_status = EnrollmentStep.NOT_ENROLLED
    user.status = FingerprintStatus.NOT_ENROLLED
    user.claimed_by_device = None

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    return {"message": "Enrollment reset successfully"}


# ------------------- UNENROLL FINGERPRINT -------------------
@router.post("/unenroll-fingerprint/{user_id}")
def unenroll_fingerprint(user_id: int, req: Request, db: Session = Depends(get_db)):
    client_ip = req.client.host
    log_request("UNENROLL-FINGERPRINT", client_ip, f"| user_id={user_id}")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.status != FingerprintStatus.ENROLLED:
        raise HTTPException(status_code=400, detail="User is not enrolled")
    if not user.finger_id:
        raise HTTPException(status_code=400, detail="User has no finger_id")

    # At least one device must be online to accept a delete request
    if not any(is_device_online(s) for s in get_all_device_states(db)):
        raise HTTPException(
            status_code=400,
            detail="No ESP32 device is online. Cannot unenroll fingerprint.",
        )

    ensure_all_devices_free(db, "delete")

    now = datetime.utcnow()
    devices = get_all_device_states(db)
    for d in devices:
        d.pending_delete_id = user.finger_id
        d.pending_delete_user_id = user.id
        d.pending_delete_updated_at = now
        d.mode = "delete"

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    return {"message": "Unenrollment started", "finger_id": user.finger_id}


# ------------------- DEVICE CHECK DELETE -------------------
@router.get("/check-delete")
def check_delete(
    req: Request,
    device_id: str = DEFAULT_DEVICE_ID,
    db: Session = Depends(get_db),
):
    client_ip = req.client.host
    state = get_device_state(db, device_id)

    if state.pending_delete_id is not None:
        # Check if this pending_delete has gone stale (device never confirmed)
        now = datetime.utcnow()
        stale_cutoff = now - timedelta(seconds=PENDING_DELETE_TIMEOUT_SECONDS)
        if state.pending_delete_updated_at and state.pending_delete_updated_at < stale_cutoff:
            # Auto-clear stale pending deletes
            log_request(
                "CHECK-DELETE",
                client_ip,
                f"| device={device_id} | CLEARING stale pending_delete_id={state.pending_delete_id}",
            )
            state.pending_delete_id = None
            state.pending_delete_user_id = None
            state.pending_delete_updated_at = None
            state.mode = "idle"
            db.commit()
            return PlainTextResponse("none")

        finger_id = state.pending_delete_id
        log_request(
            "CHECK-DELETE",
            client_ip,
            f"| device={device_id} | Found finger_id={finger_id}",
        )
        db.commit()
        return PlainTextResponse(str(finger_id))

    return PlainTextResponse("none")


# ------------------- DEVICE STATUS (any device online) -------------------
@router.get("/device-status")
def device_status(db: Session = Depends(get_db)):
    connected = any(is_device_online(s) for s in get_all_device_states(db))
    return {"connected": connected}


# ------------------- START/STOP ATTENDANCE -------------------
@router.post("/start-attendance")
def start_attendance(
    request: StartAttendanceRequest,
    db: Session = Depends(get_db),
):
    event = db.query(Event).filter(Event.id == request.event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    ensure_all_devices_free(db, "attendance")
    set_mode_on_all_devices(db, "attendance")
    set_active_event_on_all_devices(db, request.event_id)
    return {"message": "Attendance mode started", "event_id": request.event_id}


@router.post("/stop-attendance")
def stop_attendance(db: Session = Depends(get_db)):
    set_mode_on_all_devices(db, "idle")
    set_active_event_on_all_devices(db, None)
    return {"message": "Attendance mode stopped"}


# ------------------- MARK ATTENDANCE -------------------
@router.get("/mark-attendance")
def mark_attendance(
    req: Request,
    finger_id: int,
    device_id: str = DEFAULT_DEVICE_ID,
    db: Session = Depends(get_db),
):
    client_ip = req.client.host
    log_request(
        "MARK-ATTENDANCE", client_ip, f"| device={device_id} | finger_id={finger_id}"
    )

    user = db.query(User).filter(User.finger_id == finger_id).first()
    if not user:
        return PlainTextResponse("user_not_found")
    if user.status != FingerprintStatus.ENROLLED:
        return PlainTextResponse("not_enrolled")

    state = get_device_state(db, device_id)
    if not state.active_event_id:
        return PlainTextResponse("no_active_event")

    ongoing_event = db.query(Event).filter(Event.id == state.active_event_id).first()
    if not ongoing_event:
        return PlainTextResponse("no_active_event")

    # Verify the event is actually ongoing by checking time range
    ph_now = datetime.now(ph_tz)
    event_start = datetime.combine(ongoing_event.event_date, ongoing_event.start_time)
    event_end = datetime.combine(ongoing_event.event_date, ongoing_event.end_time)
    # Make timezone-aware for comparison
    ph_tz_local = pytz.timezone("Asia/Manila")
    event_start = ph_tz_local.localize(event_start)
    event_end = ph_tz_local.localize(event_end)
    ph_now_aware = ph_tz_local.localize(ph_now)

    if ph_now_aware < event_start or ph_now_aware > event_end:
        log_request(
            "MARK-ATTENDANCE",
            client_ip,
            f"| device={device_id} | finger_id={finger_id} | event not in progress "
            f"(now={ph_now_aware}, start={event_start}, end={event_end})",
        )
        return PlainTextResponse("event_not_active")

    log_request(
        "MARK-ATTENDANCE",
        client_ip,
        f"| device={device_id} | finger_id={finger_id} | saving to event_id={ongoing_event.id}",
    )

    if ongoing_event.program_id is not None:
        if user.program_id != ongoing_event.program_id:
            return PlainTextResponse("wrong_program")

    new_attendance = Attendance(
        user_id=user.id,
        event_id=ongoing_event.id,
        status=AttendanceStatus.PRESENT,
        attendance_time=datetime.now(ph_tz).replace(tzinfo=None),
    )
    db.add(new_attendance)

    try:
        db.commit()
        db.refresh(new_attendance)
        log_request(
            "MARK-ATTENDANCE",
            client_ip,
            f"| device={device_id} | finger_id={finger_id} | SUCCESS attendance recorded",
        )
        return PlainTextResponse("attendance_marked")
    except IntegrityError:
        db.rollback()
        log_request(
            "MARK-ATTENDANCE",
            client_ip,
            f"| device={device_id} | finger_id={finger_id} | ALREADY MARKED (unique constraint)",
        )
        return PlainTextResponse("already_marked")
    except Exception as e:
        db.rollback()
        log_request(
            "MARK-ATTENDANCE",
            client_ip,
            f"| device={device_id} | finger_id={finger_id} | DATABASE ERROR: {e}",
        )
        return PlainTextResponse("database_error")


# ------------------- DEVICE MODE FOR ESP32 -------------------
@router.get("/device-mode")
def get_device_mode(
    device_id: str = DEFAULT_DEVICE_ID,
    db: Session = Depends(get_db),
):
    state = get_device_state(db, device_id)
    return PlainTextResponse(state.mode)


# ------------------- START RECOGNITION TEST -------------------
@router.post("/start-recognition/{user_id}")
def start_recognition(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.status != FingerprintStatus.ENROLLED:
        raise HTTPException(status_code=400, detail="User not enrolled")

    if not any(is_device_online(s) for s in get_all_device_states(db)):
        raise HTTPException(status_code=503, detail="No ESP32 device online")

    ensure_all_devices_free(db, "recognize")

    devices = get_all_device_states(db)
    for d in devices:
        d.mode = "recognize"
        d.recognition_target_id = user.finger_id
        d.recognition_finger_id = None
        d.recognition_matched = None

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "message": "Recognition test started",
        "target_finger_id": user.finger_id,
    }


# ------------------- ESP32 POSTS RECOGNITION RESULT -------------------
@router.get("/recognition-result")
def recognition_result(
    finger_id: int,
    matched: bool,
    device_id: str = DEFAULT_DEVICE_ID,
    db: Session = Depends(get_db),
):
    state = get_device_state(db, device_id)

    # Use an atomic UPDATE to prevent race conditions between two devices.
    # Only the first device to set recognition_matched will succeed.
    from sqlalchemy import update
    stmt = (
        update(DeviceState)
        .where(DeviceState.device_id == device_id)
        .where(DeviceState.recognition_matched.is_(None))
        .values(
            recognition_matched=matched and (finger_id == state.recognition_target_id),
            recognition_finger_id=state.recognition_target_id,
            recognition_target_id=None,
        )
    )
    result = db.execute(stmt)

    if result.rowcount == 0:
        # Another device already processed this, or state was already set
        return PlainTextResponse("already_processed")

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        return PlainTextResponse("error")

    set_mode_on_all_devices(db, "idle")

    return PlainTextResponse("ok")


# ------------------- FRONTEND POLLS FOR RECOGNITION RESULT -------------------
@router.get("/get-recognition-result")
def get_recognition_result(
    finger_id: int,
    device_id: str = DEFAULT_DEVICE_ID,
    db: Session = Depends(get_db),
):
    state = get_device_state(db, device_id)

    if state.recognition_finger_id == finger_id:
        matched = state.recognition_matched
        state.recognition_finger_id = None
        state.recognition_matched = None
        db.commit()
        return {"status": "done", "matched": matched}

    return {"status": "pending"}


# ------------------- DEBUG ALL ENROLLED -------------------
@router.get("/debug/all-enrolled")
def debug_all_enrolled(db: Session = Depends(get_db)):
    users = db.query(User).filter(User.status == FingerprintStatus.ENROLLED).all()
    return [
        {
            "user_id": u.id,
            "student_id_no": u.student_id_no,
            "name": f"{u.first_name} {u.last_name}",
            "finger_id": u.finger_id,
            "status": u.status.value,
            "enroll_status": u.enroll_status.value if u.enroll_status else None,
        }
        for u in users
    ]


# ------------------- DEBUG DEVICE STATE (all devices) -------------------
@router.get("/debug/device-state")
def debug_device_state(db: Session = Depends(get_db)):
    db.expire_all()
    states = get_all_device_states(db)
    pending_users = (
        db.query(User).filter(User.status == FingerprintStatus.PENDING).all()
    )
    return {
        "devices": [
            {
                "device_id": s.device_id,
                "mode": s.mode,
                "pending_delete_id": s.pending_delete_id,
                "pending_delete_user_id": s.pending_delete_user_id,
                "pending_delete_updated_at": s.pending_delete_updated_at,
                "active_event_id": s.active_event_id,
                "last_seen": s.last_seen,
                "online": is_device_online(s),
            }
            for s in states
        ],
        "pending_enrollments": [
            {
                "user_id": u.id,
                "finger_id": u.finger_id,
                "status": u.status.value,
                "enroll_status": u.enroll_status.value if u.enroll_status else None,
                "claimed_by_device": u.claimed_by_device,
            }
            for u in pending_users
        ],
    }