from datetime import date, time, datetime
from pydantic import BaseModel, field_validator
from typing import Optional
from app.models.events import EventStatus


class EventBase(BaseModel):
    title: str
    description: Optional[str] = None
    event_date: date
    start_time: time
    end_time: time
    location: str


class EventCreate(EventBase):
    @field_validator("event_date")
    @classmethod
    def event_date_must_be_future_or_today(cls, v):
        today = date.today()
        if v < today:
            raise ValueError("Event date cannot be in the past")
        return v

    @field_validator("end_time")
    @classmethod
    def end_time_must_be_after_start_time(cls, v, info):
        if "start_time" in info.data and v <= info.data["start_time"]:
            raise ValueError("End time must be after start time")
        return v


class EventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    event_date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    location: Optional[str] = None

    @field_validator("event_date")
    @classmethod
    def update_event_date_must_be_future_or_today(cls, v):
        if v is not None:
            today = date.today()
            if v < today:
                raise ValueError("Event date cannot be in the past")
        return v

    @field_validator("end_time")
    @classmethod
    def end_time_must_be_after_start_time(cls, v, info):
        if (
            v is not None
            and "start_time" in info.data
            and info.data["start_time"] is not None
        ):
            if v <= info.data["start_time"]:
                raise ValueError("End time must be after start time")
        return v


class EventResponse(EventBase):
    id: int
    created_by: int
    created_at: datetime
    status: EventStatus

    class Config:
        from_attributes = True
