from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
import os
import shutil
from pathlib import Path
import uuid

from app.core.database import get_db
from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserResponse, UserLogin, UserProfileUpdate
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
)
from datetime import datetime, timedelta
import secrets
from app.models.password_reset import PasswordReset
from app.schemas.auth import ForgotPasswordSchema, ResetPasswordSchema


router = APIRouter(prefix="/auth", tags=["Authentication"])

# ------------------- UPLOADS DIRECTORY -------------------
UPLOAD_DIR = Path("uploads/profile_pictures")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

# 5MB
MAX_FILE_SIZE = 5 * 1024 * 1024


# ------------------- REGISTER -------------------
@router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
def register_user(user: UserCreate, db: Session = Depends(get_db)):
    from app.models.programs import Program

    # CHECK IF ADMIN EXISTS
    existing_admin = db.query(User).filter(User.role == UserRole.ADMIN).first()

    if existing_admin:
        # If admin already exists → force role to STUDENT
        if user.role == UserRole.ADMIN:
            raise HTTPException(
                status_code=403,
                detail="Administrator account already exists. Only students can register.",
            )
    else:
        # If no admin exists → allow first admin only
        if user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=403,
                detail="First registered account must be an administrator.",
            )

    # MOBILE CHECK
    existing_mobile = (
        db.query(User).filter(User.mobile_phone == user.mobile_phone).first()
    )
    if existing_mobile:
        raise HTTPException(status_code=400, detail="Mobile phone already registered")

    if user.student_id_no:
        existing_student = (
            db.query(User).filter(User.student_id_no == user.student_id_no).first()
        )
        if existing_student:
            raise HTTPException(status_code=400, detail="Student ID already registered")

    # ASSIGN PROGRAM AND YEAR LEVEL
    program_id = user.program_id
    year_level = user.year_level

    if user.role == UserRole.ADMIN:
        osa_program = db.query(Program).filter(Program.code == "OSA").first()
        if not osa_program:
            osa_program = Program(code="OSA", name="OSA Head")
            db.add(osa_program)
            db.commit()
            db.refresh(osa_program)

        program_id = osa_program.id
        year_level = None

    elif user.role == UserRole.STUDENT:
        if not program_id:
            raise HTTPException(
                status_code=400, detail="Program is required for students"
            )
        if not year_level:
            raise HTTPException(
                status_code=400, detail="Year level is required for students"
            )

    new_user = User(
        student_id_no=user.student_id_no,
        first_name=user.first_name,
        last_name=user.last_name,
        middle_initial=user.middle_initial,
        program_id=program_id,
        year_level=year_level,
        mobile_phone=user.mobile_phone,
        password=hash_password(user.password),
        role=user.role,
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return new_user


# ------------------- LOGIN -------------------
@router.post("/login")
def login(login_data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.student_id_no == login_data.student_id_no).first()

    if not user or not verify_password(login_data.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid student ID or password",
        )

    # Create JWT token
    token_data = {"user_id": user.id, "role": user.role.value}
    access_token = create_access_token(token_data)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "student_id_no": user.student_id_no,
        "role": user.role.value,
    }


# ------------------- LOGOUT -------------------
@router.post("/logout")
def logout():
    return {"message": "Logged out successfully"}


# ------------------- FORGOT PASSWORD -------------------
@router.post("/forgot-password")
def forgot_password(data: ForgotPasswordSchema, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.mobile_phone == data.mobile_phone).first()

    if not user:
        raise HTTPException(status_code=404, detail="Phone number not found")

    token = secrets.token_urlsafe(32)
    expires = datetime.utcnow() + timedelta(minutes=15)

    reset = PasswordReset(user_id=user.id, token=token, expires_at=expires)

    db.add(reset)
    db.commit()

    return {"message": "Reset link sent", "token": token}


# ------------------- RESET PASSWORD -------------------
@router.post("/reset-password")
def reset_password(data: ResetPasswordSchema, db: Session = Depends(get_db)):
    reset = (
        db.query(PasswordReset)
        .filter(
            PasswordReset.token == data.token,
            PasswordReset.expires_at > datetime.utcnow(),
        )
        .first()
    )

    if not reset:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    user = db.query(User).get(reset.user_id)
    user.password = hash_password(data.new_password)

    db.delete(reset)
    db.commit()

    return {"message": "Password updated successfully"}


# ------------------- GET CURRENT USER -------------------
@router.get("/profile", response_model=UserResponse)
def get_user_profile(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):

    if not current_user:
        raise HTTPException(status_code=404, detail="User not found")

    return current_user


# ------------------- UPDATE USER PROFILE -------------------
@router.put("/profile", response_model=UserResponse)
def update_user_profile(
    profile_data: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.models.programs import Program

    if not current_user:
        raise HTTPException(status_code=404, detail="User not found")

    if (
        profile_data.mobile_phone
        and profile_data.mobile_phone != current_user.mobile_phone
    ):
        existing_mobile = (
            db.query(User)
            .filter(
                User.mobile_phone == profile_data.mobile_phone,
                User.id != current_user.id,
            )
            .first()
        )
        if existing_mobile:
            raise HTTPException(status_code=400, detail="Mobile phone already in use")

    year_level_map = {"1": "FIRST", "2": "SECOND", "3": "THIRD", "4": "FOURTH"}

    # Update only the fields that are provided
    if profile_data.first_name is not None:
        current_user.first_name = profile_data.first_name
    if profile_data.last_name is not None:
        current_user.last_name = profile_data.last_name
    if profile_data.middle_initial is not None:
        current_user.middle_initial = profile_data.middle_initial
    if profile_data.mobile_phone is not None:
        current_user.mobile_phone = profile_data.mobile_phone

    if profile_data.program is not None:
        program = db.query(Program).filter(Program.code == profile_data.program).first()
        if not program:
            raise HTTPException(
                status_code=400, detail=f"Program '{profile_data.program}' not found"
            )
        current_user.program_id = program.id

    if profile_data.profile_image is not None:
        current_user.profile_image = profile_data.profile_image
    if profile_data.year_level is not None:
        current_user.year_level = year_level_map.get(profile_data.year_level)

    db.commit()
    db.refresh(current_user)

    return current_user


# ------------------- UPLOAD PROFILE PICTURE -------------------
@router.post("/profile/upload-picture")
async def upload_profile_picture(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a profile picture for the current user"""

    # Validate file extension
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type not allowed. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE / (1024*1024)}MB",
        )

    await file.seek(0)

    if current_user.profile_image:
        old_file_path = Path(current_user.profile_image)
        if old_file_path.exists():
            old_file_path.unlink()

    # Generate unique filename
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = UPLOAD_DIR / unique_filename

    with file_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    current_user.profile_image = str(file_path)
    db.commit()
    db.refresh(current_user)

    return {
        "message": "Profile picture uploaded successfully",
        "profile_image": str(file_path),
    }


# ------------------- DELETE PROFILE PICTURE -------------------
@router.delete("/profile/delete-picture")
def delete_profile_picture(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete the current user's profile picture"""

    if not current_user.profile_image:
        raise HTTPException(status_code=404, detail="No profile picture to delete")

    # Delete file from filesystem
    file_path = Path(current_user.profile_image)
    if file_path.exists():
        file_path.unlink()

    current_user.profile_image = None
    db.commit()

    return {"message": "Profile picture deleted successfully"}


# ------------------- CHECK IF ADMIN ACCOUNT ALREADY EXIST -------------------
@router.get("/admin-exists")
def check_admin_exists(db: Session = Depends(get_db)):
    admin = db.query(User).filter(User.role == UserRole.ADMIN).first()
    return {"exists": bool(admin)}
