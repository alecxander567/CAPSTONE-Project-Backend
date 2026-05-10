# app/models/token_blacklist.py
from sqlalchemy import Column, Integer, String, DateTime
from app.core.database import Base
from datetime import datetime


class TokenBlacklist(Base):
    __tablename__ = "token_blacklist"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String, unique=True, index=True, nullable=False)
    blacklisted_at = Column(DateTime, default=datetime.utcnow)
