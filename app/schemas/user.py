from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from app.models.user import UserRole, YearLevel
from pydantic import BaseModel, field_validator


class UserCreate(BaseModel):
    student_id_no: Optional[str] = None
    first_name: str
    last_name: str
    middle_initial: Optional[str] = None
    program_id: Optional[int] = None
    year_level: Optional[YearLevel] = None
    mobile_phone: str
    password: str
    role: UserRole = UserRole.STUDENT


class UserResponse(BaseModel):
    id: int
    student_id_no: Optional[str]
    first_name: str
    last_name: str
    middle_initial: Optional[str]
    program: Optional[str] = None
    year_level: Optional[YearLevel]
    mobile_phone: str
    profile_image: Optional[str]
    role: str
    fingerprint_status: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    @field_validator("program", mode="before")
    @classmethod
    def extract_program_code(cls, v):  
        if hasattr(v, "code"): 
            return v.code
        return v

    class Config:
        from_attributes = True


class UserLogin(BaseModel):
    student_id_no: str
    password: str


class UserProfileUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_initial: Optional[str] = None
    mobile_phone: Optional[str] = None
    program: Optional[str] = None
    year_level: int | None = None  
    profile_image: Optional[str] = None

    class Config:
        from_attributes = True
