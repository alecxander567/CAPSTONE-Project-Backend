from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from datetime import datetime, date
from fastapi.responses import JSONResponse
from app.core.database import get_db
from app.models.user import User, FingerprintStatus
from app.models.attendance import Attendance, AttendanceStatus
from app.models.events import Event
from pydantic import BaseModel
import pytz

router = APIRouter(prefix="/attendance", tags=["Attendance"])

ph_tz = pytz.timezone("Asia/Manila")


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
    ph_now = datetime.now(ph_tz)
    today = ph_now.date()
    now = ph_now.time()

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
            attendance_time=datetime.now(ph_tz).replace(tzinfo=None),
        )
        db.add(attendance)

    db.commit()
    db.refresh(attendance)

    return JSONResponse(
        {"student_id_no": user.student_id_no, "status": attendance.status.value}
    )


# ------------------- GET CURRENT ATTENDANCE STATUS -------------------
@router.get("/updates")
def get_attendance_updates(event_id: int | None = None, db: Session = Depends(get_db)):
    """Return all attendance for ongoing event or a specific event"""

    if event_id:
        target_event = db.query(Event).filter(Event.id == event_id).first()
        if not target_event:
            return []
    else:
        ph_now = datetime.now(ph_tz)
        today = ph_now.date()
        now = ph_now.time()

        target_event = (
            db.query(Event)
            .filter(Event.event_date == today)
            .filter(Event.start_time <= now)
            .filter(Event.end_time >= now)
            .first()
        )

        if not target_event:
            return []

    attendance_records = (
        db.query(Attendance, User)
        .join(User, Attendance.user_id == User.id)
        .filter(Attendance.event_id == target_event.id)
        .all()
    )

    return [
        {
            "student_id_no": user.student_id_no,
            "status": record.status.value,
            "year_level": user.year_level,
            "time": (
                record.attendance_time.isoformat() if record.attendance_time else None
            ),
        }
        for record, user in attendance_records
    ]


# ------------------- GET ATTENDANCE COUNT PER EVENT -------------------
@router.get("/per-event")
def get_attendance_per_event(db: Session = Depends(get_db)):
    """Return attendance count for each event, ordered by event date"""
    events = (
        db.query(Event).order_by(Event.event_date.asc(), Event.start_time.asc()).all()
    )

    result = []
    for event in events:
        count = (
            db.query(Attendance)
            .filter(Attendance.event_id == event.id)
            .filter(Attendance.status == AttendanceStatus.PRESENT)
            .count()
        )
        result.append(
            {
                "event": event.title,
                "event_date": event.event_date.strftime("%b %d"),
                "students": count,
            }
        )

    return result


# ------------------- GET ATTENDANCE COUNT PER PROGRAM -------------------
@router.get("/per-program")
def get_attendance_per_program(db: Session = Depends(get_db)):
    """
    Return attendance percentage per program
    (present students ÷ total enrolled students in that program)
    """

    from app.models.programs import Program

    programs = db.query(Program).all()

    result = []

    for program in programs:
        total_students = (
            db.query(User)
            .filter(User.program_id == program.id)
            .filter(User.status == FingerprintStatus.ENROLLED)
            .count()
        )

        # Present students in this program (for ongoing event)
        present_students = (
            db.query(Attendance)
            .join(User, Attendance.user_id == User.id)
            .filter(User.program_id == program.id)
            .filter(Attendance.status == AttendanceStatus.PRESENT)
            .count()
        )

        percentage = (
            round((present_students / total_students) * 100)
            if total_students > 0
            else 0
        )

        result.append(
            {
                "program": program.name,
                "code": program.code,
                "present": present_students,
                "total_students": total_students,
                "percentage": percentage,
            }
        )

    return result


# ------------------- GET ATTENDANCE BY EVENT -------------------
@router.get("/by-event/{event_id}")
def get_attendance_by_event(event_id: int, db: Session = Depends(get_db)):
    """Return attendance records for a specific event"""
    records = (
        db.query(Attendance, User)
        .join(User, Attendance.user_id == User.id)
        .filter(Attendance.event_id == event_id)
        .all()
    )

    return [
        {
            "student_id_no": user.student_id_no,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "program_id": user.program_id,
            "status": record.status.value,
            "attendance_time": (
                record.attendance_time.isoformat() if record.attendance_time else None
            ),
        }
        for record, user in records
    ]


# ------------------- GET STUDENTS WITH 3+ ABSENCES -------------------
@router.get("/at-risk")
def get_at_risk_students(db: Session = Depends(get_db)):
    """Return students who have 3 or more absences across all events"""
    from app.models.programs import Program

    total_events = db.query(Event).count()

    if total_events == 0:
        return []

    users = db.query(User).filter(User.status == FingerprintStatus.ENROLLED).all()

    result = []
    for user in users:
        present_count = (
            db.query(Attendance)
            .filter(Attendance.user_id == user.id)
            .filter(Attendance.status == AttendanceStatus.PRESENT)
            .count()
        )
        absences = total_events - present_count

        if absences >= 3:
            program = db.query(Program).filter(Program.id == user.program_id).first()
            result.append(
                {
                    "student_id_no": user.student_id_no,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "program": program.name if program else "N/A",
                    "program_code": program.code if program else "N/A",
                    "absences": absences,
                    "present": present_count,
                    "total_events": total_events,
                }
            )

    result.sort(key=lambda x: x["absences"], reverse=True)
    return result
