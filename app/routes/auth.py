from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

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
from app.core.mail import send_email


router = APIRouter(prefix="/auth", tags=["Authentication"])


# ------------------- REGISTER -------------------
@router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
def register_user(user: UserCreate, db: Session = Depends(get_db)):
    existing_email = db.query(User).filter(User.email == user.email).first()
    if existing_email:
        raise HTTPException(status_code=400, detail="Email already registered")

    if user.student_id_no:
        existing_student = (
            db.query(User).filter(User.student_id_no == user.student_id_no).first()
        )
        if existing_student:
            raise HTTPException(status_code=400, detail="Student ID already registered")

    new_user = User(
        student_id_no=user.student_id_no,
        first_name=user.first_name,
        last_name=user.last_name,
        middle_initial=user.middle_initial,
        program=user.program,
        email=user.email,
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
    user = db.query(User).filter(User.student_id_no == data.student_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="Student not found")

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

    if not current_user:
        raise HTTPException(status_code=404, detail="User not found")

    if profile_data.email and profile_data.email != current_user.email:
        existing_email = (
            db.query(User)
            .filter(User.email == profile_data.email, User.id != current_user.id)
            .first()
        )
        if existing_email:
            raise HTTPException(status_code=400, detail="Email already in use")

    # Update only the fields that are provided
    if profile_data.first_name is not None:
        current_user.first_name = profile_data.first_name
    if profile_data.last_name is not None:
        current_user.last_name = profile_data.last_name
    if profile_data.middle_initial is not None:
        current_user.middle_initial = profile_data.middle_initial
    if profile_data.email is not None:
        current_user.email = profile_data.email
    if profile_data.program is not None:
        current_user.program = profile_data.program

    db.commit()
    db.refresh(current_user)

    return current_user
