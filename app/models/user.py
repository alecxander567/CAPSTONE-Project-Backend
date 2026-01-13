from sqlalchemy import Column, Integer, String, Enum, DateTime
from sqlalchemy.sql import func
from app.core.database import Base
import enum
from sqlalchemy.orm import relationship


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
    BSHS = "BHumServ"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    student_id_no = Column(String(20), unique=True, index=True, nullable=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    middle_initial = Column(String(5), nullable=True)

    program = Column(Enum(Program), nullable=False)

    role = Column(Enum(UserRole), nullable=False, default=UserRole.STUDENT)

    email = Column(String(255), unique=True, index=True, nullable=False)
    password = Column(String(255), nullable=False)

    password_resets = relationship("PasswordReset", back_populates="user")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
