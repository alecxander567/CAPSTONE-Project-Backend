from datetime import date, time, datetime
from zoneinfo import ZoneInfo
from pydantic import BaseModel, field_validator, model_validator
from typing import Optional
from app.models.events import EventStatus


# Match the timezone used by Event.status in the model so "today" means
# the same thing everywhere.
APP_TIMEZONE = ZoneInfo("Asia/Manila")


def _today() -> date:
    """Today's date in the app's configured timezone."""
    return datetime.now(APP_TIMEZONE).date()


class EventBase(BaseModel):
    title: str
    description: Optional[str] = None
    event_date: date
    start_time: time
    end_time: time
    location: str
    program_id: Optional[int] = None


class EventCreate(EventBase):
    @field_validator("event_date")
    @classmethod
    def event_date_must_be_future_or_today(cls, v):
        if v < _today():
            raise ValueError("Event date cannot be in the past")
        return v

    @model_validator(mode="after")
    def end_time_must_be_after_start_time(self):
        if self.end_time <= self.start_time:
            raise ValueError("End time must be after start time")
        return self


class EventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    event_date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    location: Optional[str] = None
    program_id: Optional[int] = None

    @field_validator("event_date")
    @classmethod
    def update_event_date_must_be_future_or_today(cls, v):
        if v is not None and v < _today():
            raise ValueError("Event date cannot be in the past")
        return v

    @model_validator(mode="after")
    def end_time_must_be_after_start_time(self):
        # Only enforce when BOTH are present in the same payload. Partial
        # updates are validated in the route against the existing record.
        if self.start_time is not None and self.end_time is not None:
            if self.end_time <= self.start_time:
                raise ValueError("End time must be after start time")
        return self


class EventResponse(EventBase):
    id: int
    created_by: int
    created_at: datetime
    status: EventStatus

    class Config:
        from_attributes = True