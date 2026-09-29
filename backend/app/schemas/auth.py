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


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: UserRole = UserRole.IMPORT_MANAGER
    can_access_billing: bool = False


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12)
