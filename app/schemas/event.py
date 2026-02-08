from datetime import date, time, datetime
from pydantic import BaseModel
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
    pass


class EventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    event_date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    location: Optional[str] = None


class EventResponse(EventBase):
    id: int
    created_by: int
    created_at: datetime
    status: EventStatus

    class Config:
        from_attributes = True
