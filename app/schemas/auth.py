from pydantic import BaseModel, Field


class ForgotPasswordSchema(BaseModel):
    mobile_phone: str = Field(..., example="09123456789")


class ResetPasswordSchema(BaseModel):
    token: str = Field(..., example="your-reset-token")
    new_password: str = Field(..., min_length=6, example="newpassword123")
