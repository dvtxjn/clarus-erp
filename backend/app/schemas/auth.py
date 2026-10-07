from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints
from app.core.enums import UserRole


# The login is a username (e.g. "samidha") or an e-mail: the admin sets every password and
# "forgot password" only flags the account for the admin, so nothing is ever mailed to it.
Login = Annotated[str, BeforeValidator(lambda v: v.strip().lower() if isinstance(v, str) else v),
                  StringConstraints(min_length=3, max_length=64, pattern=r"^[a-z0-9][a-z0-9._@+-]*$")]


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str  # the login: username or e-mail
    full_name: str
    role: UserRole
    can_access_billing: bool
    is_active: bool = True
    read_only: bool = False
    password_reset_requested_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None


class UserCreate(BaseModel):
    email: Login
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
    read_only: Optional[bool] = None


class PasswordSet(BaseModel):
    new_password: str = Field(min_length=12)


class ForgotPassword(BaseModel):
    email: str
