from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, ConfigDict, Field
from app.core.enums import UserRole


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    full_name: str
    role: UserRole
    can_access_billing: bool
    is_active: bool = True
    password_reset_requested_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12)
    full_name: str = Field(min_length=1)
    role: UserRole = UserRole.IMPORT_MANAGER
    can_access_billing: bool = False


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12)


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=1)
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class PasswordSet(BaseModel):
    new_password: str = Field(min_length=12)


class ForgotPassword(BaseModel):
    email: str
