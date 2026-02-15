from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.user import User, FingerprintStatus, EnrollmentStep
from fastapi.responses import PlainTextResponse
import random
from pydantic import BaseModel
from datetime import datetime
from app.models.attendance import Attendance, AttendanceStatus
from app.models.events import Event
from datetime import datetime, date

router = APIRouter(prefix="/fingerprints", tags=["Fingerprints"])

device_mode = "idle"
pending_delete_id = None


class EnrollmentRequest(BaseModel):
    user_id: int


def log_request(endpoint: str, client_ip: str, extra: str = ""):
    timestamp = datetime.now().strftime("%H:%M:%S")


# ------------------- START ENROLLMENT -------------------
@router.post("/start-enrollment")
def start_enrollment(
    request: EnrollmentRequest,
    req: Request,
    db: Session = Depends(get_db),
):
    global device_mode

    client_ip = req.client.host
    log_request("START-ENROLLMENT", client_ip, f"| user_id={request.user_id}")

    user = db.query(User).filter(User.id == request.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Clean up any previous failed/completed enrollments
    if user.status in [FingerprintStatus.ENROLLED, FingerprintStatus.FAILED]:
        user.finger_id = None
        user.enroll_status = EnrollmentStep.NOT_ENROLLED
        user.status = FingerprintStatus.NOT_ENROLLED

    if (
        user.status == FingerprintStatus.PENDING
        and user.enroll_status != EnrollmentStep.NOT_ENROLLED
    ):
        return {
            "message": "Enrollment already in progress",
            "finger_id": user.finger_id,
            "status": user.status.value,
            "step": user.enroll_status.value,
        }

    # Generate new finger_id
    existing_ids = {u.finger_id for u in db.query(User.finger_id).all() if u.finger_id}
    finger_id = random.randint(1, 127)
    while finger_id in existing_ids:
        finger_id = random.randint(1, 127)

    user.finger_id = finger_id
    user.enroll_status = EnrollmentStep.PENDING
    user.status = FingerprintStatus.PENDING

    try:
        db.commit()
        db.refresh(user)

        device_mode = "enroll"

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
    log_request("CHECK-ENROLLMENT", client_ip)

    user = (
        db.query(User)
        .filter(User.status == FingerprintStatus.PENDING)
        .filter(User.enroll_status == EnrollmentStep.PENDING)
        .order_by(User.id.asc())
        .first()
    )

    if user:
        return PlainTextResponse(str(user.finger_id))

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
    global device_mode

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
        db.refresh(user)

        if status in ["success", "error", "delete_success", "delete_error"]:
            device_mode = "idle"

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
        if get_status.call_count % 10 == 1:
            pass
        return {"status": "failed", "step": "error", "message": "User not found"}

    step = user.enroll_status.value if user.enroll_status else "pending"

    result = {
        "status": user.status.value,
        "step": step,
    }

    if get_status.call_count % 10 == 1:
        pass

    return result


# ------------------- RESET ENROLLMENT -------------------
@router.post("/reset-enrollment/{user_id}")
def reset_enrollment(user_id: int, req: Request, db: Session = Depends(get_db)):
    """Reset user's enrollment status to allow re-enrollment"""
    client_ip = req.client.host
    log_request("RESET-ENROLLMENT", client_ip, f"| user_id={user_id}")

    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    old_status = user.status.value if user.status else "none"

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
    """Unenroll a user's fingerprint from the system"""
    global device_mode, pending_delete_id

    client_ip = req.client.host
    log_request("UNENROLL-FINGERPRINT", client_ip, f"| user_id={user_id}")

    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.status != FingerprintStatus.ENROLLED:
        raise HTTPException(status_code=400, detail="User is not enrolled")

    if not user.finger_id:
        raise HTTPException(status_code=400, detail="User has no finger_id")

    # Store the finger_id for ESP32 to delete
    pending_delete_id = user.finger_id

    device_mode = "delete"

    return {
        "message": "Unenrollment started",
        "finger_id": user.finger_id,
    }


# ------------------- ESP32 POLLS FOR PENDING DELETE -------------------
@router.get("/check-delete")
def check_delete(req: Request):
    global pending_delete_id

    client_ip = req.client.host
    log_request("CHECK-DELETE", client_ip)

    if pending_delete_id is not None:
        finger_id = pending_delete_id
        pending_delete_id = None
        return PlainTextResponse(str(finger_id))

    return PlainTextResponse("none")


# ------------------- DEBUG -------------------
@router.get("/debug/{finger_id}")
def debug_enrollment(finger_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.finger_id == finger_id).first()

    if not user:
        return {"error": f"No user with finger_id={finger_id}"}

    return {
        "user_id": user.id,
        "finger_id": user.finger_id,
        "status": user.status.value if user.status else None,
        "enroll_status": user.enroll_status.value if user.enroll_status else None,
    }


# ------------------- START ATTENDANCE -------------------
@router.post("/start-attendance")
def start_attendance():
    global device_mode
    device_mode = "attendance"
    return {"message": "Attendance mode started"}


# ------------------- STOP ATTENDANCE -------------------
@router.post("/stop-attendance")
def stop_attendance():
    global device_mode
    device_mode = "idle"
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

    # Find user by finger_id
    user = db.query(User).filter(User.finger_id == finger_id).first()

    if not user:
        pass
        return PlainTextResponse("user_not_found")

    if user.status != FingerprintStatus.ENROLLED:
        return PlainTextResponse("not_enrolled")

    # Find ongoing event
    today = date.today()
    now = datetime.now().time()

    events = db.query(Event).filter(Event.event_date == today).all()

    ongoing_event = None

    for event in events:
        print(f"      - Event: {event.title} | {event.start_time} to {event.end_time}")
        if event.start_time <= now <= event.end_time:
            ongoing_event = event
            break

    if not ongoing_event:
        return PlainTextResponse("no_active_event")

    # Check for existing attendance
    existing = (
        db.query(Attendance)
        .filter(Attendance.user_id == user.id)
        .filter(Attendance.event_id == ongoing_event.id)
        .first()
    )

    if existing:
        return PlainTextResponse("already_marked")

    # Create new attendance record
    new_attendance = Attendance(
        user_id=user.id,
        event_id=ongoing_event.id,
        status=AttendanceStatus.PRESENT,
        attendance_time=datetime.now(),
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
def get_device_mode():
    """
    ESP32 polls this endpoint to determine the current mode:
    - 'idle': no enrollment in progress
    - 'enroll': an enrollment is in progress
    - 'attendance': attendance mode
    - 'delete': fingerprint deletion in progress
    """
    global device_mode
    return PlainTextResponse(device_mode)
