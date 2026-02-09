from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.user import User, FingerprintStatus, EnrollmentStep
from fastapi.responses import PlainTextResponse
import random
from pydantic import BaseModel

router = APIRouter(prefix="/fingerprints", tags=["Fingerprints"])


# Pydantic model
class EnrollmentRequest(BaseModel):
    user_id: int


# ------------------- START ENROLLMENT OF FINGERPRINT -------------------
@router.post("/start-enrollment")
def start_enrollment(
    request: EnrollmentRequest,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == request.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.enroll_status not in [EnrollmentStep.SUCCESS, EnrollmentStep.ERROR, None]:
        print(f"User {user.id} already has pending enrollment")

    # Generate new finger_id (avoid collisions)
    existing_ids = {u.finger_id for u in db.query(User.finger_id).all() if u.finger_id}
    finger_id = random.randint(1, 127)
    while finger_id in existing_ids:
        finger_id = random.randint(1, 127)

    user.finger_id = finger_id
    user.enroll_status = EnrollmentStep.PENDING
    user.status = FingerprintStatus.PENDING

    db.commit()
    db.refresh(user)

    return {
        "message": "Enrollment started",
        "finger_id": finger_id,
        "status": user.status.value,
    }


# ------------------- ESP32 POLLS FOR PENDING ENROLLMENT -------------------
@router.get("/check-enrollment")
def check_enrollment(db: Session = Depends(get_db)):

    user = (
        db.query(User)
        .filter(User.enroll_status == EnrollmentStep.PENDING)
        .order_by(User.id.asc())
        .first()
    )

    if not user:
        return PlainTextResponse("none")

    return PlainTextResponse(str(user.finger_id))


# ------------------- ESP32 UPDATES ENROLLMENT STEPS -------------------
@router.get("/update-enrollment")
def update_enrollment(
    id: int,
    status: str,
    db: Session = Depends(get_db),
):

    if id == 0:
        return PlainTextResponse("invalid_id")

    user = db.query(User).filter(User.finger_id == id).first()

    if not user:
        return PlainTextResponse("error")

    # Map ESP32 string to backend enum
    status_map = {
        "pending": (EnrollmentStep.PENDING, FingerprintStatus.PENDING),
        "place_finger": (EnrollmentStep.PLACE_FINGER, FingerprintStatus.PENDING),
        "remove_finger": (EnrollmentStep.REMOVE_FINGER, FingerprintStatus.PENDING),
        "place_again": (EnrollmentStep.PLACE_AGAIN, FingerprintStatus.PENDING),
        "success": (EnrollmentStep.SUCCESS, FingerprintStatus.ENROLLED),
        "error": (EnrollmentStep.ERROR, FingerprintStatus.FAILED),
    }

    if status not in status_map:
        return PlainTextResponse("invalid_status")

    enroll_step, fingerprint_status = status_map[status]
    user.enroll_status = enroll_step
    user.status = fingerprint_status

    db.commit()
    db.refresh(user)

    return PlainTextResponse("updated")


# ------------------- FRONTEND POLLS FOR STATUS UPDATES -------------------
@router.get("/get-status")
def get_status(
    finger_id: int,
    db: Session = Depends(get_db),
):

    user = db.query(User).filter(User.finger_id == finger_id).first()

    if not user:
        return {"status": "failed", "step": "error", "message": "User not found"}

    result = {
        "status": user.status.value,
        "step": user.enroll_status.value,
    }

    return result
