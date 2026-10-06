from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Date,
    Time,
    DateTime,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base
from datetime import datetime, time as dtime
import pytz
from enum import Enum


class EventStatus(str, Enum):
    UPCOMING = "upcoming"
    ONGOING = "ongoing"
    DONE = "done"


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)

    title_id = Column(
        Integer, ForeignKey("event_titles.id"), nullable=False, index=True
    )
    location_id = Column(
        Integer, ForeignKey("locations.id"), nullable=False, index=True
    )

    description = Column(Text, nullable=True)

    start_date = Column(Date, nullable=False, index=True)
    end_date = Column(Date, nullable=False, index=True)

    program_id = Column(Integer, ForeignKey("programs.id"), nullable=True)

    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # ── Relationships ──
    event_title = relationship("EventTitle", back_populates="events")
    location_ref = relationship("Location", back_populates="events")
    program = relationship("Program", foreign_keys=[program_id])
    days = relationship(
        "EventDay",
        back_populates="event",
        cascade="all, delete-orphan",
        order_by="EventDay.day_date",
    )
    notifications = relationship("Notification", back_populates="event")

    # ── Prevent duplicate (same title at same location on same start date) ──
    __table_args__ = (
        UniqueConstraint(
            "title_id", "location_id", "start_date", name="uq_event_unique"
        ),
    )

    @property
    def status(self) -> EventStatus:
        ph_tz = pytz.timezone("Asia/Manila")
        now = datetime.now(ph_tz)
        today = now.date()
        now_time = now.time()

        if self.start_date > today:
            return EventStatus.UPCOMING
        if self.end_date < today:
            return EventStatus.DONE

        # We are inside the multi-day range. Look up today's schedule.
        today_window = next(
            (d for d in self.days if d.day_date == today), None
        )

        if today_window is None:
            # No time window today, but still inside range → ONGOING.
            return EventStatus.ONGOING

        if now_time < today_window.start_time:
            return EventStatus.UPCOMING
        if now_time > today_window.end_time:
            return EventStatus.ONGOING
        return EventStatus.ONGOING


class EventDay(Base):
    __tablename__ = "event_days"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(
        Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    day_date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)

    event = relationship("Event", back_populates="days")

    __table_args__ = (
        UniqueConstraint("event_id", "day_date", name="uq_event_day"),
    )