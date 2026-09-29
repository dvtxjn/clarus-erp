from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base
from app.core.enums import UserRole


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(SAEnum(UserRole), nullable=False, default=UserRole.IMPORT_MANAGER)

    # Spec §2.4: "Proforma & Billing module access is permission-gated ...
    # assigned per user" — kept independently toggleable rather than
    # hardcoded to the Accountant role, per the spec's explicit note.
    can_access_billing = Column(Boolean, default=False, nullable=False)

    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Port scoping (spec §2.4): if a user has no rows here, they see all ports.
    # If they have rows, visibility is restricted to just those ports.
    port_access = relationship("UserPortAccess", back_populates="user", cascade="all, delete-orphan")


class UserPortAccess(Base):
    """
    One row per (user, port) they're scoped to. Absence of any rows for a
    user means "no port restriction" (sees all ports) — see Shipment
    visibility logic in routers/shipments.py.
    """
    __tablename__ = "user_port_access"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    port = Column(String, nullable=False, index=True)

    user = relationship("User", back_populates="port_access")
