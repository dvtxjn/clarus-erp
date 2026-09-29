from sqlalchemy import Column, Integer, String
from app.core.database import Base


class Port(Base):
    """Port / ICD code -> display name, so the UI can show 'INMUN1 · Mundra'."""
    __tablename__ = "ports"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
