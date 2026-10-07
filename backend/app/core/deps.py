from typing import List, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.core.enums import UserRole
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# reads: anything else changes data
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_current_user(request: Request, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    email = decode_access_token(token)
    if email is None:
        raise credentials_exception
    user = db.query(User).filter(User.email == email).first()
    if user is None or not user.is_active:
        raise credentials_exception
    if user.read_only and request.method not in SAFE_METHODS:
        # a view-only login (the QA bot) can look but never change anything — enforced here, for every route
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This login is view-only.")
    db.info["user"] = (user.id, user.full_name)  # live updates say who changed what
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Spec §2.4: delete and certain admin-only actions require Admin role."""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


def require_billing_access(current_user: User = Depends(get_current_user)) -> User:
    """Invoicing (proformas, final invoices, rates, licences, HSS rules, duty challans,
    the organisation list) is admin-only — not even viewable by anyone else (client,
    2026-09-29). The per-user can_access_billing flag no longer grants anything."""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invoicing is admin-only")
    return current_user


def get_user_allowed_ports(user: User) -> Optional[List[str]]:
    """
    Spec §2.4: shipments visible to everyone by default, restrictable by
    port. Returns None if the user has no port restriction (sees all ports),
    otherwise the list of ports they're scoped to.
    """
    if not user.port_access:
        return None
    return [p.port for p in user.port_access]


def require_icegate_access(current_user: User = Depends(get_current_user)) -> User:
    """The ICEGATE login (the password resets periodically): the admin and import managers — they use ICEGATE
    themselves (client, 2026-09-30)."""
    if current_user.role not in (UserRole.ADMIN, UserRole.IMPORT_MANAGER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin or import manager only")
    return current_user
