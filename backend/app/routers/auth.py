from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core import ratelimit
from app.core.audit import record_change
from app.core.enums import UserRole
from app.core.database import get_db
from app.core.deps import require_admin, get_current_user
from app.core.security import hash_password, verify_password, create_access_token
from app.models.user import User
from app.schemas.auth import ForgotPassword, PasswordSet, Token, UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    ratelimit.check(request, form_data.username)  # 5 a minute; 10 wrong -> locked 15 min
    user = db.query(User).filter(func.lower(User.email) == form_data.username.strip().lower()).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        ratelimit.failed(form_data.username)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password")
    ratelimit.succeeded(form_data.username)
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")
    token = create_access_token(subject=user.email)
    return Token(access_token=token)


@router.get("/me", response_model=UserOut)
def read_current_user(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/change-password", status_code=403)
def change_password(_user: User = Depends(get_current_user)):
    """Passwords are set by the admin only (client, 2026-09-29)."""
    raise HTTPException(status_code=403, detail="Passwords are set by the admin — use \"Forgot password\" on the login page.")


@router.post("/forgot-password", status_code=204)
def forgot_password(payload: ForgotPassword, request: Request, db: Session = Depends(get_db)):
    """Flags the account for the admin to reset. Always 204, so it never reveals whether an email exists."""
    ratelimit.check(request, f"forgot:{payload.email}")
    user = db.query(User).filter(User.email == payload.email.strip().lower()).first()
    if user is not None and user.is_active:
        user.password_reset_requested_at = datetime.now(timezone.utc)
        record_change(db, "users", user.id, "password_reset_requested", None, "via login page", None)
        db.commit()


# --- user management: admin only ---

@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    return db.query(User).order_by(User.is_active.desc(), User.full_name).all()


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(payload: UserCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Spec §2.4: user/role management — admin-only. The admin sets the first password."""
    email = payload.email.strip().lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="A user with this email already exists")
    user = User(email=email, hashed_password=hash_password(payload.password), full_name=payload.full_name.strip(),
                role=payload.role, can_access_billing=payload.can_access_billing)
    db.add(user)
    db.flush()
    record_change(db, "users", user.id, "created", None, f"{email} as {payload.role.value}", admin.id)
    db.commit()
    db.refresh(user)
    return user


def _other_user(db: Session, user_id: int, admin: User) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Name, role, switch on/off, view-only. The admin can't switch off or demote their own account (no lock-out)."""
    user = _other_user(db, user_id, admin)
    changes = payload.model_dump(exclude_unset=True)
    if user.id == admin.id and (changes.get("is_active") is False or changes.get("read_only")
                                or changes.get("role", UserRole.ADMIN) != UserRole.ADMIN):
        raise HTTPException(status_code=400, detail="You can't switch off, demote or make view-only your own admin account.")
    for field, value in changes.items():
        if getattr(user, field) != value:
            record_change(db, "users", user.id, field, getattr(user, field), value, admin.id)
            setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


@router.post("/users/{user_id}/password", response_model=UserOut)
def set_password(user_id: int, payload: PasswordSet, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """The admin sets a user's password (e.g. after "Forgot password"); clears the request."""
    user = _other_user(db, user_id, admin)
    user.hashed_password = hash_password(payload.new_password)
    user.password_reset_requested_at = None
    record_change(db, "users", user.id, "password", None, "set by admin", admin.id)
    db.commit()
    db.refresh(user)
    return user
