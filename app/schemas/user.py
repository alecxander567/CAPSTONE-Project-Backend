from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
from app.models.user import UserRole


class UserCreate(BaseModel):
    student_id_no: Optional[str] = None
    first_name: str
    last_name: str
    middle_initial: Optional[str] = None
    program: Optional[str] = None
    email: EmailStr
    password: str
    role: UserRole


class UserResponse(BaseModel):
    id: int
    student_id_no: Optional[str]
    first_name: str
    last_name: str
    middle_initial: Optional[str]
    program: Optional[str]
    email: EmailStr
    role: str
    created_at: datetime

    class Config:
        from_attributes = True


class UserLogin(BaseModel):
    student_id_no: str
    password: str
