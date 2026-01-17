from sqlalchemy import Column, Integer, String, Text, Date, Time, DateTime, ForeignKey
from sqlalchemy.sql import func

from app.core.database import Base


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)

    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    event_date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)

    location = Column(String(255), nullable=False)

    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
