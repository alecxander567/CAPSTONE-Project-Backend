from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.user import User, FingerprintStatus, EnrollmentStep
import httpx
import asyncio
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

    # generate finger_id here
    finger_id = random.randint(1, 127)

    user.finger_id = finger_id
    user.enroll_status = EnrollmentStep.PENDING
    user.status = FingerprintStatus.PENDING

    db.commit()

    return {
        "message": "Enrollment started",
        "finger_id": finger_id,
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
        return "none"

    return str(user.finger_id)


# ------------------- UPDATES ENROLLMENT STEPS -------------------
@router.get("/update-enrollment")
def update_enrollment(
    id: int,
    status: EnrollmentStep,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.finger_id == id).first()
    if not user:
        return "error"

    user.enroll_status = status

    if status == EnrollmentStep.SUCCESS:
        user.status = FingerprintStatus.ENROLLED
    elif status == EnrollmentStep.ERROR:
        user.status = FingerprintStatus.FAILED

    db.commit()
    return "updated"


# ------------------- LEGACY ENDPOINT -------------------
@router.get("/get-status")
def get_status(
    finger_id: int,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.finger_id == finger_id).first()
    if not user:
        return "none"

    return user.enroll_status.value
