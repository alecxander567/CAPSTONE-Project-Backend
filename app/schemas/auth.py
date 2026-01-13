from pydantic import BaseModel, Field


class ForgotPasswordSchema(BaseModel):
    student_id: str = Field(..., example="2023-0001")


class ResetPasswordSchema(BaseModel):
    token: str = Field(..., example="your-reset-token")
    new_password: str = Field(..., min_length=6, example="newpassword123")
