from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from datetime import datetime, date
from fastapi.responses import JSONResponse
from app.core.database import get_db
from app.models.user import User, FingerprintStatus
from app.models.attendance import Attendance, AttendanceStatus
from app.models.events import Event
from pydantic import BaseModel


router = APIRouter(prefix="/attendance", tags=["Attendance"])


# ------------------- UPDATE ATTENDANCE STATUS -------------------
class AttendanceUpdateRequest(BaseModel):
    student_id_no: str
    status: str


@router.post("/update-status")
def update_attendance_status(
    request: AttendanceUpdateRequest,
    db: Session = Depends(get_db),
):
    # Find the user by student ID
    user = db.query(User).filter(User.student_id_no == request.student_id_no).first()
    if not user:
        raise HTTPException(status_code=404, detail="Student not found")

    if user.status != FingerprintStatus.ENROLLED:
        raise HTTPException(status_code=400, detail="Student not enrolled")

    # Find ongoing event for today
    today = date.today()
    now = datetime.now().time()

    ongoing_event = (
        db.query(Event)
        .filter(Event.event_date == today)
        .filter(Event.start_time <= now)
        .filter(Event.end_time >= now)
        .first()
    )

    if not ongoing_event:
        raise HTTPException(status_code=400, detail="No active event")

    # Check if attendance already exists
    attendance = (
        db.query(Attendance)
        .filter(Attendance.user_id == user.id)
        .filter(Attendance.event_id == ongoing_event.id)
        .first()
    )

    if attendance:
        attendance.status = AttendanceStatus.PRESENT
    else:
        attendance = Attendance(
            user_id=user.id,
            event_id=ongoing_event.id,
            status=AttendanceStatus.PRESENT,
            attendance_time=datetime.now(),
        )
        db.add(attendance)

    db.commit()
    db.refresh(attendance)

    return JSONResponse(
        {"student_id_no": user.student_id_no, "status": attendance.status.value}
    )


# ------------------- GET CURRENT ATTENDANCE STATUS -------------------
@router.get("/updates")
def get_attendance_updates(db: Session = Depends(get_db)):
    """Return all attendance for ongoing event"""
    today = date.today()
    now = datetime.now().time()

    # Log the request occasionally for debugging
    if not hasattr(get_attendance_updates, "call_count"):
        get_attendance_updates.call_count = 0
    get_attendance_updates.call_count += 1

    if get_attendance_updates.call_count % 20 == 1:
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] Attendance updates requested (call #{get_attendance_updates.call_count})"
        )

    ongoing_event = (
        db.query(Event)
        .filter(Event.event_date == today)
        .filter(Event.start_time <= now)
        .filter(Event.end_time >= now)
        .first()
    )

    if not ongoing_event:
        if get_attendance_updates.call_count % 20 == 1:
            pass
        return []

    if get_attendance_updates.call_count % 20 == 1:
        pass

    attendance_records = (
        db.query(Attendance, User)
        .join(User, Attendance.user_id == User.id)
        .filter(Attendance.event_id == ongoing_event.id)
        .all()
    )

    result = [
        {
            "student_id_no": user.student_id_no,
            "status": record.status.value,
            "time": (
                record.attendance_time.isoformat() if record.attendance_time else None
            ),
        }
        for record, user in attendance_records
    ]

    if get_attendance_updates.call_count % 20 == 1:
        pass

    return result
