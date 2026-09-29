"""Live stream (server-sent events) + presence. See app/core/realtime.py."""
import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core import realtime
from app.core.database import SessionLocal, get_db
from app.core.deps import get_current_user, get_user_allowed_ports
from app.core.security import decode_access_token
from app.models.shipment import Shipment
from app.models.user import User

router = APIRouter(prefix="/realtime", tags=["live updates"])

PING_SECONDS = 15


def _user_for_stream(authorization: Optional[str]) -> tuple[int, str, Optional[list[str]]]:
    """Authenticate with a short-lived session: a stream stays open for hours and must
    not hold a database connection."""
    token = (authorization or "").removeprefix("Bearer ").strip()
    email = decode_access_token(token) if token else None
    if not email:
        raise HTTPException(status_code=401, detail="Could not validate credentials")
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).first()
        if user is None or not user.is_active:
            raise HTTPException(status_code=401, detail="Could not validate credentials")
        return user.id, user.full_name, get_user_allowed_ports(user)


@router.get("/stream")
async def stream(request: Request, authorization: Optional[str] = Header(None)):
    """One per open tab. Events (JSON in `data:`):
    {"t":"s","id","port","v","del","by"} a shipment changed · {"t":"p",...} presence ·
    {"t":"resync"} reload everything (reconnects, overflow)."""
    user_id, name, ports = _user_for_stream(authorization)
    sub = realtime.hub.subscribe(user_id, ports)

    async def events():
        try:
            yield f"data: {json.dumps({'t': 'hello', 'uid': user_id, 'name': name})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(sub.queue.get(), PING_SECONDS)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # keeps proxies from closing an idle stream
                    continue
                yield f"data: {json.dumps(msg)}\n\n"
        finally:
            realtime.hub.unsubscribe(sub)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class PresenceIn(BaseModel):
    shipment_id: Optional[int] = None  # None = left the tracker / no cell selected
    field: Optional[str] = Field(default=None, max_length=64)
    editing: bool = False
    tab: Optional[str] = Field(default=None, max_length=40)  # tells apart two tabs of the same person


@router.post("/presence", status_code=204)
def presence(payload: PresenceIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Where this person is: sent on every cell change and every ~10 s while the
    tracker is open. Others drop a person after ~25 s without news."""
    port = None
    if payload.shipment_id is not None:
        s = db.get(Shipment, payload.shipment_id)
        if s is None:
            return
        allowed = get_user_allowed_ports(user)
        if allowed is not None and s.port not in allowed:
            return
        port = s.port
    realtime.send(db, {"t": "p", "uid": user.id, "name": user.full_name, "sid": payload.shipment_id,
                       "f": payload.field, "edit": payload.editing, "tab": payload.tab, "port": port})
