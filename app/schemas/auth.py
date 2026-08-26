from pydantic import BaseModel, EmailStr, Field


class ForgotPasswordSchema(BaseModel):
    email: EmailStr = Field(..., example="student@example.com")


class ResetPasswordSchema(BaseModel):
    token: str = Field(..., example="your-reset-token")
    new_password: str = Field(..., min_length=6, example="newpassword123")
