from sqlalchemy import Column, Integer, String, Enum, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base
import enum


class UserRole(str, enum.Enum):
    STUDENT = "student"
    ADMIN = "admin"


class Program(str, enum.Enum):
    BSED = "BSED"
    BSBA = "BSBA"
    BSIT = "BSIT"
    BSCRIM = "BSCRIM"
    BPED = "BPED"
    BEED = "BEED"
    BHUMSERV = "BHumServ"


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


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    student_id_no = Column(String(20), unique=True, index=True, nullable=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    middle_initial = Column(String(5), nullable=True)

    program = Column(Enum(Program), nullable=False)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.STUDENT)

    mobile_phone = Column(String(20), unique=True, index=True, nullable=False)
    profile_image = Column(String(255), nullable=True)
    password = Column(String(255), nullable=False)

    finger_id = Column(Integer, unique=True, nullable=True)

    enroll_status = Column(
        Enum(EnrollmentStep),
        default=EnrollmentStep.NOT_ENROLLED,
        nullable=False,
    )

    status = Column(
        Enum(FingerprintStatus),
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

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
