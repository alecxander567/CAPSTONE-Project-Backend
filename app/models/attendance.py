import enum
from sqlalchemy import Column, Integer, DateTime, Enum, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class AttendanceStatus(str, enum.Enum):
    PRESENT = "present"
    ABSENT = "absent"


class Attendance(Base):
    __tablename__ = "attendance"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)

    status = Column(
        Enum(AttendanceStatus, native_enum=False),
        nullable=False,
        default=AttendanceStatus.PRESENT,
    )

    attendance_time = Column(DateTime, default=datetime.utcnow)

    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="attendances")
    event = relationship("Event")

    # ── Database-level unique constraint ──────────────────────────────────
    # Prevents duplicate attendance records even under concurrent requests.
    # When two ESP32s send mark-attendance for the same (user, event) at
    # nearly the same time, the first INSERT succeeds and the second hits
    # this constraint and fails cleanly — no silent duplicates.
    __table_args__ = (
        UniqueConstraint("user_id", "event_id", name="uq_attendance_user_event"),
    )
