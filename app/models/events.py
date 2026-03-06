from sqlalchemy import Column, Integer, String, Text, Date, Time, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base
from datetime import datetime, date, timedelta
from enum import Enum


class EventStatus(str, Enum):
    UPCOMING = "upcoming"
    ONGOING = "ongoing"
    DONE = "done"


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)

    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    event_date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)

    location = Column(String(255), nullable=False)

    program_id = Column(Integer, ForeignKey("programs.id"), nullable=True)

    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    notifications = relationship("Notification", back_populates="event")
    program = relationship("Program", foreign_keys=[program_id])

    @property
    def status(self) -> EventStatus:
        now = datetime.now()
        today = date.today()

        if self.event_date < today:
            return EventStatus.DONE

        if self.event_date == today:
            if now.time() > self.end_time:
                return EventStatus.DONE

            event_start_dt = datetime.combine(today, self.start_time)
            early_threshold = (event_start_dt - timedelta(minutes=30)).time()

            if early_threshold <= now.time() <= self.end_time:
                return EventStatus.ONGOING

            return EventStatus.UPCOMING

        return EventStatus.UPCOMING
