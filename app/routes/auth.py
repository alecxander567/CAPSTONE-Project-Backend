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
from fastapi import Request, Header
from app.core.security import blacklist_token
from app.models.token_blacklist import TokenBlacklist
import cloudinary
import cloudinary.uploader
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

router = APIRouter(prefix="/auth", tags=["Authentication"])

# ------------------- UPLOADS DIRECTORY -------------------
UPLOAD_DIR = Path("uploads/profile_pictures")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

# 5MB
MAX_FILE_SIZE = 5 * 1024 * 1024

cloudinary.config(
    cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
    api_key=os.environ["CLOUDINARY_API_KEY"],
    api_secret=os.environ["CLOUDINARY_API_SECRET"],
    secure=True,
)

# ------------------- GMAIL SMTP (EMAIL) CONFIG -------------------
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]

# Falls back to your deployed frontend if FRONTEND_URL isn't set in the env.
FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://ara-system-app.vercel.app")


def send_reset_email(to_email: str, reset_link: str):
    """
    Sends the password reset link via Gmail SMTP.

    Requires a Gmail account with 2-Step Verification enabled, and an
    App Password generated at https://myaccount.google.com/apppasswords.
    SMTP_USER and SMTP_PASSWORD must be set in the environment.
    """
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Reset your password"
    msg["From"] = SMTP_USER
    msg["To"] = to_email

    html = f"""
        <p>We received a request to reset your password.</p>
        <p>
            <a href="{reset_link}">Click here to reset your password</a>
        </p>
        <p>This link expires in 15 minutes. If you didn't request this,
        you can safely ignore this email.</p>
    """
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, [to_email], msg.as_string())


# ------------------- REGISTER -------------------
@router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
def register_user(user: UserCreate, db: Session = Depends(get_db)):
    from app.models.programs import Program

    existing_admin = db.query(User).filter(User.role == UserRole.ADMIN).first()

    if existing_admin:
        if user.role == UserRole.ADMIN:
            raise HTTPException(
                status_code=403,
                detail="Administrator account already exists. Only students can register.",
            )
    else:
        if user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=403,
                detail="First registered account must be an administrator.",
            )

    existing_email = db.query(User).filter(User.email == user.email).first()
    if existing_email:
        raise HTTPException(status_code=400, detail="Email already registered")

    if user.student_id_no:
        existing_student = (
            db.query(User).filter(User.student_id_no == user.student_id_no).first()
        )
        if existing_student:
            raise HTTPException(status_code=400, detail="Student ID already registered")

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
def logout(
    request: Request, db: Session = Depends(get_db), authorization: str = Header(None)
):
    """Logout user by blacklisting their token"""
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Invalid authorization header")

        token = authorization.split(" ")[1]
        blacklist_token(token, db)

        return {"message": "Logged out successfully"}
    except Exception as e:
        return {"message": "Logged out successfully"}


# ------------------- FORGOT PASSWORD -------------------
@router.post("/forgot-password")
def forgot_password(data: ForgotPasswordSchema, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email.strip().lower()).first()

    generic_response = {
        "message": "If that email is registered, a reset link has been sent."
    }

    if not user:
        return generic_response

    token = secrets.token_urlsafe(32)
    expires = datetime.utcnow() + timedelta(minutes=15)

    db.query(PasswordReset).filter(PasswordReset.user_id == user.id).delete()

    reset = PasswordReset(user_id=user.id, token=token, expires_at=expires)
    db.add(reset)
    db.commit()

    reset_link = f"{FRONTEND_URL}/reset-password?token={token}"

    try:
        send_reset_email(user.email, reset_link)
    except Exception as e:
        print(f"Failed to send reset email: {e}")

    return generic_response


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

YEAR_LEVEL_MAP = {
    "1": "1st year",
    "2": "2nd year",
    "3": "3rd year",
    "4": "4th year",
    "1ST YEAR": "1st year",
    "2ND YEAR": "2nd year",
    "3RD YEAR": "3rd year",
    "4TH YEAR": "4th year",
}


@router.put("/profile", response_model=UserResponse)
def update_user_profile(
    profile_data: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.models.programs import Program

    if not current_user:
        raise HTTPException(status_code=404, detail="User not found")

    is_admin = current_user.role == UserRole.ADMIN

    if is_admin and (
        profile_data.program is not None or profile_data.year_level is not None
    ):
        raise HTTPException(
            status_code=403,
            detail="Admin users cannot update program or year level",
        )

    if profile_data.student_id_no is not None:
        existing_student = (
            db.query(User)
            .filter(
                User.student_id_no == profile_data.student_id_no,
                User.id != current_user.id,
            )
            .first()
        )
        if existing_student:
            raise HTTPException(status_code=400, detail="Student ID already registered")
        current_user.student_id_no = profile_data.student_id_no

    if profile_data.email is not None:
        cleaned_email = profile_data.email.strip().lower()
        existing_email = (
            db.query(User)
            .filter(User.email == cleaned_email, User.id != current_user.id)
            .first()
        )
        if existing_email:
            raise HTTPException(status_code=400, detail="Email already in use")
        current_user.email = cleaned_email

    if profile_data.first_name is not None:
        current_user.first_name = profile_data.first_name
    if profile_data.last_name is not None:
        current_user.last_name = profile_data.last_name
    if profile_data.middle_initial is not None:
        current_user.middle_initial = profile_data.middle_initial

    if not is_admin:
        if profile_data.program is not None:
            program = (
                db.query(Program).filter(Program.code == profile_data.program).first()
            )
            if not program:
                raise HTTPException(
                    status_code=400,
                    detail=f"Program '{profile_data.program}' not found",
                )
            current_user.program_id = program.id

        if profile_data.year_level is not None:
            normalized_year_level = YEAR_LEVEL_MAP.get(profile_data.year_level.upper())
            if normalized_year_level is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid year level: '{profile_data.year_level}'",
                )
            current_user.year_level = normalized_year_level

    if profile_data.profile_image is not None:
        current_user.profile_image = profile_data.profile_image

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

    if current_user.profile_image and "cloudinary.com" in current_user.profile_image:
        try:
            url_path = current_user.profile_image.split("/upload/")[-1]
            public_id = "/".join(url_path.split("/")[1:])
            public_id = public_id.rsplit(".", 1)[0]
            cloudinary.uploader.destroy(public_id)
        except Exception:
            pass

    result = cloudinary.uploader.upload(
        content,
        folder="profile_pictures",
        resource_type="image",
        transformation=[
            {"width": 400, "height": 400, "crop": "fill", "gravity": "face"}
        ],
    )

    current_user.profile_image = result["secure_url"]
    db.commit()
    db.refresh(current_user)

    return {
        "message": "Profile picture uploaded successfully",
        "profile_image": result["secure_url"],
    }


# ------------------- DELETE PROFILE PICTURE -------------------
@router.delete("/profile/delete-picture")
def delete_profile_picture(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.profile_image:
        raise HTTPException(status_code=404, detail="No profile picture to delete")

    if "cloudinary.com" in current_user.profile_image:
        try:
            url_path = current_user.profile_image.split("/upload/")[-1]
            public_id = "/".join(url_path.split("/")[1:])
            public_id = public_id.rsplit(".", 1)[0]
            cloudinary.uploader.destroy(public_id)
        except Exception:
            pass

    current_user.profile_image = None
    db.commit()

    return {"message": "Profile picture deleted successfully"}


# ------------------- CHECK IF ADMIN ACCOUNT ALREADY EXIST -------------------
@router.get("/admin-exists")
def check_admin_exists(db: Session = Depends(get_db)):
    admin = db.query(User).filter(User.role == UserRole.ADMIN).first()
    return {"exists": bool(admin)}
