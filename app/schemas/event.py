from datetime import date, time, datetime
from zoneinfo import ZoneInfo
from pydantic import BaseModel, field_validator, model_validator
from typing import Optional, List
from app.models.events import EventStatus


APP_TIMEZONE = ZoneInfo("Asia/Manila")


def _today() -> date:
    return datetime.now(APP_TIMEZONE).date()


# ──────────────────────── Event Day ────────────────────────
class EventDayBase(BaseModel):
    day_date: date
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def end_after_start(self):
        if self.end_time <= self.start_time:
            raise ValueError("End time must be after start time")
        return self


class EventDayResponse(EventDayBase):
    id: int

    class Config:
        from_attributes = True


# ──────────────────────── Event ────────────────────────
class EventBase(BaseModel):
    title_id: int
    location_id: int
    description: Optional[str] = None
    start_date: date
    end_date: date
    program_id: Optional[int] = None


class EventCreate(EventBase):
    days: List[EventDayBase]

    @field_validator("start_date")
    @classmethod
    def start_date_future(cls, v):
        if v < _today():
            raise ValueError("Start date cannot be in the past")
        return v

    @model_validator(mode="after")
    def validate_dates_and_days(self):
        if self.end_date < self.start_date:
            raise ValueError("End date must be on or after start date")

        if not self.days:
            raise ValueError("At least one event day is required")

        day_dates = sorted(d.day_date for d in self.days)
        if day_dates[0] != self.start_date:
            raise ValueError("First event day must match start_date")
        if day_dates[-1] != self.end_date:
            raise ValueError("Last event day must match end_date")

        # Every date between start and end must be covered
        from datetime import timedelta
        expected = set()
        cur = self.start_date
        while cur <= self.end_date:
            expected.add(cur)
            cur += timedelta(days=1)

        provided = set(day_dates)
        if expected != provided:
            missing = sorted(expected - provided)
            raise ValueError(
                f"Missing event days for dates: {[d.isoformat() for d in missing]}"
            )

        return self


class EventUpdate(BaseModel):
    title_id: Optional[int] = None
    location_id: Optional[int] = None
    description: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    program_id: Optional[int] = None
    days: Optional[List[EventDayBase]] = None

    @field_validator("start_date")
    @classmethod
    def start_date_future(cls, v):
        if v is not None and v < _today():
            raise ValueError("Start date cannot be in the past")
        return v

    @model_validator(mode="after")
    def validate_combined(self):
        if self.start_date and self.end_date:
            if self.end_date < self.start_date:
                raise ValueError("End date must be on or after start date")
        return self


class EventTitleBrief(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


class LocationBrief(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


class EventResponse(BaseModel):
    id: int
    title_id: int
    location_id: int
    title: str  # convenience — flattened from EventTitle.name
    location: str  # convenience — flattened from Location.name
    description: Optional[str] = None
    start_date: date
    end_date: date
    program_id: Optional[int] = None
    created_by: int
    created_at: datetime
    status: EventStatus
    days: List[EventDayResponse]

    class Config:
        from_attributes = True