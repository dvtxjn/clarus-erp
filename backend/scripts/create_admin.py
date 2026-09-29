"""
Create (or reset) an admin login from the environment — production has no default admin.

    ADMIN_EMAIL=you@claruslogistics.in ADMIN_PASSWORD='at least 12 characters' \
        python scripts/create_admin.py

An existing user with that email becomes admin and gets the new password (audit-logged).
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from app import models  # noqa: E402,F401
from app.core.audit import record_change  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.core.enums import UserRole  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.user import User  # noqa: E402

email = os.getenv("ADMIN_EMAIL", "").strip().lower()
password = os.getenv("ADMIN_PASSWORD", "")
name = os.getenv("ADMIN_NAME", "Admin")
if "@" not in email or len(password) < 12 or password == "changeme":
    sys.exit("Set ADMIN_EMAIL and ADMIN_PASSWORD (at least 12 characters).")
with SessionLocal() as db:
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        user = User(email=email, full_name=name, role=UserRole.ADMIN, hashed_password=hash_password(password),
                    can_access_billing=True, is_active=True)
        db.add(user)
        db.flush()
        record_change(db, "users", user.id, "created", None, f"admin {email} (create_admin.py)", None)
    else:
        user.role, user.is_active, user.hashed_password = UserRole.ADMIN, True, hash_password(password)
        record_change(db, "users", user.id, "password/role", None, "reset by create_admin.py", None)
    if os.getenv("DISABLE_DEFAULT_USERS") == "1":
        # data copied from the development Mac still has the test logins — switch them off
        # (never deleted; the production check refuses to start while they're active)
        for u in db.query(User).filter(User.email.in_(("admin@example.com", "importmanager@example.com")),
                                       User.is_active.is_(True)):
            u.is_active = False
            record_change(db, "users", u.id, "is_active", True, False, None)
            print(f"Switched off test login {u.email}")
    db.commit()
    print(f"Admin ready: {email}")
