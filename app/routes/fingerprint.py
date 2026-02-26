from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.user import User, FingerprintStatus, EnrollmentStep
from fastapi.responses import PlainTextResponse
import random
from pydantic import BaseModel
from datetime import datetime, timedelta
from app.models.attendance import Attendance, AttendanceStatus
from app.models.events import Event
from app.models.device import DeviceState
import pytz

router = APIRouter(prefix="/fingerprints", tags=["Fingerprints"])

ph_tz = pytz.timezone("Asia/Manila")

MAX_FINGERPRINTS = 1000


class EnrollmentRequest(BaseModel):
    user_id: int


def log_request(endpoint: str, client_ip: str, extra: str = ""):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {endpoint} | {client_ip} {extra}")


def get_device_state(db: Session) -> DeviceState:
    """Get or create device state."""
    state = db.query(DeviceState).filter(DeviceState.id == 1).first()
    if not state:
        state = DeviceState(
            id=1,
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

    # Reset previous enrollment state
    if user.status != FingerprintStatus.NOT_ENROLLED:
        user.finger_id = None
        user.enroll_status = EnrollmentStep.NOT_ENROLLED
        user.status = FingerprintStatus.NOT_ENROLLED

    # Generate new finger_id
    existing_ids = {u.finger_id for u in db.query(User.finger_id).all() if u.finger_id}

    if len(existing_ids) >= MAX_FINGERPRINTS:
        raise HTTPException(status_code=400, detail="Fingerprint storage is full")

    available_ids = set(range(1, MAX_FINGERPRINTS + 1)) - existing_ids
    finger_id = random.choice(list(available_ids))

    # Set user fields
    user.finger_id = finger_id
    user.enroll_status = EnrollmentStep.PENDING
    user.status = FingerprintStatus.PENDING

    state = get_device_state(db)
    state.mode = "enroll"

    try:
        db.commit()
        db.refresh(user)
        db.refresh(state)
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

    if status in ["success", "error", "delete_success", "delete_error"]:
        state = get_device_state(db)
        state.mode = "idle"

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        return PlainTextResponse("error")

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

    state = get_device_state(db)

    # Device online check
    if not state.last_seen or datetime.utcnow() - state.last_seen > timedelta(
        seconds=10
    ):
        raise HTTPException(
            status_code=400,
            detail="ESP32 device is offline. Cannot unenroll fingerprint.",
        )

    state.pending_delete_id = user.finger_id
    state.mode = "delete"

    try:
        db.commit()
        db.refresh(state)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    return {"message": "Unenrollment started", "finger_id": user.finger_id}


# ------------------- DEVICE CHECK DELETE -------------------
@router.get("/check-delete")
def check_delete(req: Request, db: Session = Depends(get_db)):
    client_ip = req.client.host
    state = get_device_state(db)

    if state.pending_delete_id is not None:
        finger_id = state.pending_delete_id
        log_request("CHECK-DELETE", client_ip, f"| Found finger_id={finger_id}")
        state.pending_delete_id = None
        db.commit()
        return PlainTextResponse(str(finger_id))

    return PlainTextResponse("none")


# ------------------- DEVICE STATUS -------------------
@router.get("/device-status")
def device_status(db: Session = Depends(get_db)):
    state = get_device_state(db)
    connected = False
    if state.last_seen and datetime.utcnow() - state.last_seen < timedelta(seconds=10):
        connected = True
    return {"connected": connected}


# ------------------- START/STOP ATTENDANCE -------------------
@router.post("/start-attendance")
def start_attendance(db: Session = Depends(get_db)):
    state = get_device_state(db)
    state.mode = "attendance"
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    return {"message": "Attendance mode started"}


@router.post("/stop-attendance")
def stop_attendance(db: Session = Depends(get_db)):
    state = get_device_state(db)
    state.mode = "idle"
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    return {"message": "Attendance mode stopped"}


# ------------------- MARK ATTENDANCE -------------------
@router.get("/mark-attendance")
def mark_attendance(
    req: Request,
    finger_id: int,
    db: Session = Depends(get_db),
):
    client_ip = req.client.host
    log_request("MARK-ATTENDANCE", client_ip, f"| finger_id={finger_id}")

    user = db.query(User).filter(User.finger_id == finger_id).first()
    if not user:
        return PlainTextResponse("user_not_found")
    if user.status != FingerprintStatus.ENROLLED:
        return PlainTextResponse("not_enrolled")

    ph_now = datetime.now(ph_tz)
    today = ph_now.date()
    now = ph_now.time()
    events = db.query(Event).filter(Event.event_date == today).all()

    ongoing_event = None
    for event in events:
        if event.start_time <= now <= event.end_time:
            ongoing_event = event
            break

    if not ongoing_event:
        return PlainTextResponse("no_active_event")

    if ongoing_event.program_id is not None:
        if user.program_id != ongoing_event.program_id:
            return PlainTextResponse("wrong_program")

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
def get_device_mode(db: Session = Depends(get_db)):
    state = get_device_state(db)
    return PlainTextResponse(state.mode)


# ------------------- START RECOGNITION TEST -------------------
@router.post("/start-recognition/{user_id}")
def start_recognition(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.status != FingerprintStatus.ENROLLED:
        raise HTTPException(status_code=400, detail="User not enrolled")

    state = get_device_state(db)

    # Check if device is online based on last_seen timestamp
    if not state.last_seen or datetime.utcnow() - state.last_seen > timedelta(
        seconds=10
    ):
        raise HTTPException(status_code=503, detail="ESP32 device offline")

    state.mode = "recognize"
    state.recognition_target_id = user.finger_id
    state.recognition_finger_id = None
    state.recognition_matched = None

    try:
        db.commit()
        db.refresh(state)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "message": "Recognition test started",
        "target_finger_id": state.recognition_target_id,
    }


# ------------------- ESP32 POSTS RECOGNITION RESULT -------------------
@router.get("/recognition-result")
def recognition_result(
    finger_id: int,
    matched: bool,
    db: Session = Depends(get_db),
):
    state = get_device_state(db)

    if not state:
        return PlainTextResponse("error")

    target = state.recognition_target_id
    actual_match = matched and (finger_id == target)

    state.mode = "idle"
    state.recognition_matched = actual_match
    state.recognition_finger_id = target
    state.recognition_target_id = None

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        return PlainTextResponse("error")

    return PlainTextResponse("ok")


# ------------------- FRONTEND POLLS FOR RECOGNITION RESULT -------------------
@router.get("/get-recognition-result")
def get_recognition_result(finger_id: int, db: Session = Depends(get_db)):
    state = get_device_state(db)
    if not state:
        return {"status": "pending"}
    if state.recognition_finger_id == finger_id:
        return {"status": "done", "matched": state.recognition_matched}
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


# ------------------- DEBUG DEVICE STATE -------------------
@router.get("/debug/device-state")
def debug_device_state(db: Session = Depends(get_db)):
    db.expire_all()
    state = get_device_state(db)
    pending_users = (
        db.query(User).filter(User.status == FingerprintStatus.PENDING).all()
    )
    return {
        "device_state": {
            "mode": state.mode,
            "pending_delete_id": state.pending_delete_id,
        },
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
