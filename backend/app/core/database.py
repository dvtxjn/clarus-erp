"""
Database engine/session setup.

Uses PostgreSQL in production (set DATABASE_URL env var), but falls back to a
local SQLite file for zero-setup local development so the app runs immediately
without a Postgres instance running.
"""
import os

from dotenv import load_dotenv

load_dotenv()
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./erp_dev.db")

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    # The Cloud SQL f1-micro allows ~22 connections in all. SQLAlchemy's default (5 + 10 overflow) per
    # app instance ran it out ("remaining connection slots are reserved", 2026-10-08), so each instance
    # keeps 3 + 2 (+1 for the live-update LISTEN): 2 instances plus a deploy's overlap stay well under.
    engine = create_engine(
        DATABASE_URL,
        pool_size=int(os.getenv("DB_POOL_SIZE", "3")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "2")),
        pool_timeout=30,
        pool_pre_ping=True,  # a connection Cloud SQL dropped is replaced instead of failing a request
        pool_recycle=1800,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency — yields a DB session per request, closes it after."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
