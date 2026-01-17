import os
from dotenv import load_dotenv
import bcrypt
import jwt
from typing import Dict
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

# Load environment variables
load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")


# ------------------ Password Functions ------------------
def hash_password(password: str) -> str:
    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    password_bytes = plain_password.encode("utf-8")
    hashed_bytes = hashed_password.encode("utf-8")
    return bcrypt.checkpw(password_bytes, hashed_bytes)


# ------------------ JWT Functions ------------------
def create_access_token(data: Dict) -> str:
    to_encode = data.copy()
    token = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return token


def decode_access_token(token: str) -> Dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )


# ------------------ OAuth2 Dependency ------------------
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme)):
    payload = decode_access_token(token)
    user_id = payload.get("user_id")
    role = payload.get("role")
    if user_id is None or role is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )
    return {"user_id": user_id, "role": role}
