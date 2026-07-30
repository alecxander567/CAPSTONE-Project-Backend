from sqlalchemy import Column, Integer, String, Enum, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base
import enum
from sqlalchemy import ForeignKey


class UserRole(str, enum.Enum):
    STUDENT = "student"
    ADMIN = "admin"


class FingerprintStatus(str, enum.Enum):
    NOT_ENROLLED = "not_enrolled"
    PENDING = "pending"
    ENROLLED = "enrolled"
    FAILED = "failed"


class EnrollmentStep(str, enum.Enum):
    NOT_ENROLLED = "not_enrolled"
    PENDING = "pending"
    PLACE_FINGER = "place_finger"
    REMOVE_FINGER = "remove_finger"
    PLACE_AGAIN = "place_again"
    SUCCESS = "success"
    ERROR = "error"


class YearLevel(str, enum.Enum):
    FIRST = "1st year"
    SECOND = "2nd year"
    THIRD = "3rd year"
    FOURTH = "4th year"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    student_id_no = Column(String(20), unique=True, index=True, nullable=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    middle_initial = Column(String(5), nullable=True)

    program_id = Column(Integer, ForeignKey("programs.id"), nullable=True)
    program = relationship("Program", back_populates="users")
    role = Column(
        Enum(
            UserRole, native_enum=False, values_callable=lambda x: [e.value for e in x]
        ),
        nullable=False,
        default=UserRole.STUDENT,
    )

    year_level = Column(Enum(YearLevel, native_enum=False), nullable=True)

    mobile_phone = Column(String(20), unique=True, index=True, nullable=False)
    device_token = Column(String(255), nullable=True)
    profile_image = Column(String(255), nullable=True)
    password = Column(String(255), nullable=False)

    finger_id = Column(Integer, unique=True, nullable=True)

    # Tracks which ESP32 device claimed this user for an enrollment session.
    # Prevents two devices from simultaneously enrolling the same user.
    # Cleared when enrollment completes (success/error/reset).
    claimed_by_device = Column(String(50), nullable=True)

    enroll_status = Column(
        Enum(
            EnrollmentStep,
            native_enum=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=EnrollmentStep.NOT_ENROLLED,
        nullable=False,
    )

    status = Column(
        Enum(
            FingerprintStatus,
            native_enum=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=FingerprintStatus.NOT_ENROLLED,
        nullable=False,
    )

    password_resets = relationship("PasswordReset", back_populates="user")
    notifications = relationship(
        "Notification", back_populates="user", cascade="all, delete"
    )
    fingerprints = relationship(
        "Fingerprint", back_populates="user", cascade="all, delete-orphan"
    )

    attendances = relationship(
        "Attendance", back_populates="user", cascade="all, delete-orphan"
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )