from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.user import User, FingerprintStatus
import httpx
import asyncio

router = APIRouter(prefix="/fingerprints", tags=["Fingerprints"])

ESP32_URL = "http://192.168.1.100" 


# ------------------- TRIGGER CONNECTION FROM ESP32 AND ENROLL FINGERPRINT -------------------
@router.post("/enroll/{user_id}")
async def trigger_fingerprint_enrollment(
    user_id: int,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if user.status == FingerprintStatus.ENROLLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User already has a fingerprint enrolled",
        )

    user.status = FingerprintStatus.PENDING
    db.commit()

    try:
        async with httpx.AsyncClient() as client:
            await client.post(f"{ESP32_URL}/enroll", timeout=2.0)
    except Exception as e:
        print(f"Error connecting to ESP32: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cannot connect to fingerprint sensor",
        )

    return {
        "message": "Fingerprint enrollment started",
        "user_id": user.id,
        "fingerprint_status": user.status,
    }


# ------------------- GET FINGERPRINT STATUS -------------------
@router.get("/enrollment-status/{user_id}")
async def get_enrollment_status(
    user_id: int,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{ESP32_URL}/status", timeout=2.0)
            esp_status = response.json()

            if esp_status["status"] == "success":
                user.status = FingerprintStatus.ENROLLED
                db.commit()
            elif esp_status["status"] == "failed":
                user.status = FingerprintStatus.FAILED
                db.commit()

            return {
                "status": esp_status["status"],
                "step": esp_status["step"],
                "message": esp_status.get("message", ""),
            }
    except Exception as e:
        print(f"Error getting ESP32 status: {e}")
        return {
            "status": "failed",
            "step": "connection_error",
            "message": "Cannot connect to sensor",
        }
