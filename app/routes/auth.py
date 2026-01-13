from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserResponse, UserLogin
from app.core.security import hash_password, verify_password
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
        role=UserRole.STUDENT,
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

    return {
        "message": f"Welcome {user.first_name} {user.last_name}",
        "student_id_no": user.student_id_no,
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
