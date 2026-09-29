"""
Live updates, Google-Sheets style (client, 2026-09-29): everyone sees other people's
edits within about a second, and which cell each person is on.

  - Every flush that changes a shipment queues a small event {t:"s", id, port, v, del, by}.
    Postgres: sent with pg_notify inside the same transaction, so it goes out only if
    the transaction commits (and reaches every app instance via LISTEN).
    SQLite (dev): published in-process after the commit.
  - Presence {t:"p", uid, name, sid, f}: which shipment / column a person is on.
  - Browsers hold one stream (GET /realtime/stream, server-sent events) and re-fetch
    the rows that changed (so port scoping and the row's shape stay the API's job).
"""
from __future__ import annotations

import asyncio
import json
import logging
import select
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.core.database import DATABASE_URL, engine

log = logging.getLogger("realtime")
CHANNEL = "erp_changes"
IS_PG = engine.dialect.name == "postgresql"


@dataclass(eq=False)
class Subscriber:
    user_id: int
    ports: Optional[list[str]]  # None = every port
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=500))

    def wants(self, msg: dict) -> bool:
        return self.ports is None or msg.get("t") == "resync" or msg.get("port") in self.ports


class Hub:
    """Fan-out to the streams connected to this app instance."""

    def __init__(self) -> None:
        self.subs: set[Subscriber] = set()
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def subscribe(self, user_id: int, ports: Optional[list[str]]) -> Subscriber:
        sub = Subscriber(user_id, ports)
        self.subs.add(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        self.subs.discard(sub)

    def _publish(self, msg: dict) -> None:
        for sub in list(self.subs):
            if not sub.wants(msg):
                continue
            try:
                sub.queue.put_nowait(msg)
            except asyncio.QueueFull:  # a stuck browser: tell it to reload everything
                sub.queue = asyncio.Queue(maxsize=500)
                sub.queue.put_nowait({"t": "resync"})

    def publish(self, msg: dict) -> None:
        """Safe from any thread."""
        if self.loop is not None and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self._publish, msg)


hub = Hub()


def send(db_or_conn, msg: dict) -> None:
    """Broadcast now (presence). Postgres: NOTIFY on its own autocommit connection."""
    if IS_PG:
        with engine.connect() as c:
            c.execute(text("SELECT pg_notify(:ch, :p)"), {"ch": CHANNEL, "p": json.dumps(msg)})
            c.commit()
    else:
        hub.publish(msg)


# --- collect shipment changes per transaction ---

def _by(session: Session) -> Optional[str]:
    u = session.info.get("user")
    return u[1] if u else None


@event.listens_for(Session, "after_flush")
def _after_flush(session: Session, _ctx) -> None:
    from app.models.shipment import Shipment

    msgs = []
    for obj in list(session.new) + list(session.dirty):
        if isinstance(obj, Shipment) and (obj in session.new or session.is_modified(obj, include_collections=False)):
            msgs.append({"t": "s", "id": obj.id, "port": obj.port, "v": obj.version,
                         "del": obj.deleted_at is not None, "by": _by(session)})
    if not msgs:
        return
    if IS_PG:
        conn = session.connection()
        for m in msgs:  # delivered by Postgres only when this transaction commits
            conn.execute(text("SELECT pg_notify(:ch, :p)"), {"ch": CHANNEL, "p": json.dumps(m)})
    else:
        session.info.setdefault("rt_pending", []).extend(msgs)


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    for m in session.info.pop("rt_pending", []):
        hub.publish(m)


@event.listens_for(Session, "after_rollback")
def _after_rollback(session: Session) -> None:
    session.info.pop("rt_pending", None)


# --- Postgres LISTEN thread (one per app instance) ---

_listener: Optional[threading.Thread] = None


def _listen_forever() -> None:
    import psycopg2
    import psycopg2.extensions

    dsn = DATABASE_URL.replace("+psycopg2", "")
    while True:
        try:
            conn = psycopg2.connect(dsn)
            conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
            conn.cursor().execute(f"LISTEN {CHANNEL}")
            hub.publish({"t": "resync"})  # (re)connected: anything may have been missed
            while True:
                if select.select([conn], [], [], 10) == ([], [], []):
                    continue
                conn.poll()
                while conn.notifies:
                    n = conn.notifies.pop(0)
                    try:
                        hub.publish(json.loads(n.payload))
                    except ValueError:
                        pass
        except Exception:  # database restart etc.: retry
            log.exception("realtime listener lost its connection; retrying")
            time.sleep(2)


def start(loop: asyncio.AbstractEventLoop) -> None:
    global _listener
    hub.loop = loop
    if IS_PG and _listener is None:
        _listener = threading.Thread(target=_listen_forever, name="realtime-listen", daemon=True)
        _listener.start()
