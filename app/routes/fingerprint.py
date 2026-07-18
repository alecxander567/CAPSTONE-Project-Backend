from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.user import User, FingerprintStatus, EnrollmentStep
from fastapi.responses import PlainTextResponse
import random
from pydantic import BaseModel
from datetime import datetime
from app.models.attendance import Attendance, AttendanceStatus
from app.models.events import Event
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


class EnrollmentRequest(BaseModel):
    user_id: int


class StartAttendanceRequest(BaseModel):
    event_id: int


def log_request(endpoint: str, client_ip: str, extra: str = ""):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {endpoint} | {client_ip} {extra}")


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

    if len(existing_ids) > 1000:
        raise HTTPException(status_code=400, detail="Fingerprint storage is full")

    finger_id = random.randint(1, 1000)
    while finger_id in existing_ids:
        finger_id = random.randint(1, 1000)

    # Set user fields
    user.finger_id = finger_id
    user.enroll_status = EnrollmentStep.PENDING
    user.status = FingerprintStatus.PENDING

    try:
        db.commit()
        db.refresh(user)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    set_mode_on_all_devices(db, "enroll")

    return {
        "message": "Enrollment started",
        "finger_id": finger_id,
        "status": user.status.value,
        "step": "pending",
    }


# ------------------- ESP32 POLLS FOR PENDING ENROLLMENT -------------------
@router.get("/check-enrollment")
def check_enrollment(req: Request, db: Session = Depends(get_db)):
    client_ip = req.client.host

    # First check PENDING users
    user = (
        db.query(User)
        .filter(User.status == FingerprintStatus.PENDING)
        .filter(User.enroll_status == EnrollmentStep.PENDING)
        .order_by(User.id.asc())
        .first()
    )

    if user:
        log_request(
            "CHECK-ENROLLMENT", client_ip, f"| Found finger_id={user.finger_id}"
        )
        return PlainTextResponse(str(user.finger_id))

    # Check users in other enrollment steps
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
        .order_by(User.id.asc())
        .first()
    )

    if user:
        log_request(
            "CHECK-ENROLLMENT", client_ip, f"| Resuming finger_id={user.finger_id}"
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
        user.enroll_status = enroll_step
        user.status = fingerprint_status
        user.finger_id = None
    elif status == "delete_error":
        pass
    else:
        user.enroll_status = enroll_step
        user.status = fingerprint_status

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

    user.finger_id = None
    user.enroll_status = EnrollmentStep.NOT_ENROLLED
    user.status = FingerprintStatus.NOT_ENROLLED

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

    devices = get_all_device_states(db)
    for d in devices:
        d.pending_delete_id = user.finger_id
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
        finger_id = state.pending_delete_id
        log_request(
            "CHECK-DELETE",
            client_ip,
            f"| device={device_id} | Found finger_id={finger_id}",
        )
        state.pending_delete_id = None
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

    log_request(
        "MARK-ATTENDANCE",
        client_ip,
        f"| device={device_id} | finger_id={finger_id} | saving to event_id={ongoing_event.id}",
    )

    if ongoing_event.program_id is not None:
        if user.program_id != ongoing_event.program_id:
            return PlainTextResponse("wrong_program")

    # NOTE: this check-then-insert is not atomic. Under simultaneous scans of the
    # SAME student on two devices within the same request window, both could pass
    # this check before either commits. If that becomes an issue in practice, add
    # a unique constraint on (user_id, event_id) in the Attendance table so the
    # second insert fails cleanly instead of creating a duplicate row.
    existing = (
        db.query(Attendance)
        .filter(Attendance.user_id == user.id)
        .filter(Attendance.event_id == ongoing_event.id)
        .first()
    )
    if existing:
        return PlainTextResponse("already_marked")

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
    except Exception as e:
        db.rollback()
        return PlainTextResponse("database_error")

    return PlainTextResponse("attendance_marked")


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

    # Prevent processing if already have a result
    if state.recognition_matched is not None:
        return PlainTextResponse("already_processed")

    target = state.recognition_target_id

    # matched=true means the sensor found a fingerprint; check if it's the right one
    actual_match = matched and (finger_id == target)

    state.recognition_matched = actual_match
    state.recognition_finger_id = target
    state.recognition_target_id = None

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        return PlainTextResponse("error")

    # Recognition is exclusive across the fleet — release everyone back to idle
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

    # Check if this is the result we're waiting for
    if state.recognition_finger_id == finger_id:
        matched = state.recognition_matched

        # Clear the state immediately after reading
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
            }
            for u in pending_users
        ],
    }
