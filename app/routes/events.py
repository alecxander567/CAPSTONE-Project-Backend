from fastapi import APIRouter, Depends, HTTPException, status, Path, Body, Query
from sqlalchemy.orm import Session
from sqlalchemy import extract, func
from typing import List
from datetime import timedelta

from app.core.database import get_db
from app.models.events import Event, EventDay
from app.models.event_title import EventTitle
from app.models.location import Location
from app.models.attendance import Attendance
from app.models.user import User
from app.schemas.event import (
    EventCreate,
    EventResponse,
    EventUpdate,
    EventDayResponse,
)
from app.core.security import get_current_user
from app.services.notifications import notify_today_events
from app.schemas.event import _today


router = APIRouter(prefix="/events", tags=["Events"])


def _flatten_event(event: Event) -> dict:
    """Attach flattened title/location names for the response model."""
    return {
        "id": event.id,
        "title_id": event.title_id,
        "location_id": event.location_id,
        "title": event.event_title.name if event.event_title else "",
        "location": event.location_ref.name if event.location_ref else "",
        "description": event.description,
        "start_date": event.start_date,
        "end_date": event.end_date,
        "program_id": event.program_id,
        "created_by": event.created_by,
        "created_at": event.created_at,
        "status": event.status,
        "days": event.days,
    }


# ─────────────────────── ADD EVENT (ADMIN ONLY) ───────────────────────
@router.post("/", response_model=EventResponse, status_code=201)
def create_event(
    event: EventCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(403, "Only admins can create events")

    # Verify referenced title/location exist
    if not db.query(EventTitle).filter(EventTitle.id == event.title_id).first():
        raise HTTPException(400, "Invalid title_id")
    if not db.query(Location).filter(Location.id == event.location_id).first():
        raise HTTPException(400, "Invalid location_id")

    # Duplicate check
    dup = (
        db.query(Event)
        .filter(
            Event.title_id == event.title_id,
            Event.location_id == event.location_id,
            Event.start_date == event.start_date,
        )
        .first()
    )
    if dup:
        raise HTTPException(
            status_code=409,
            detail="An event with the same title, location, and start date already exists.",
        )

    new_event = Event(
        title_id=event.title_id,
        location_id=event.location_id,
        description=event.description,
        start_date=event.start_date,
        end_date=event.end_date,
        program_id=event.program_id,
        created_by=current_user.id,
    )
    db.add(new_event)
    db.flush()  # get new_event.id

    for d in event.days:
        db.add(
            EventDay(
                event_id=new_event.id,
                day_date=d.day_date,
                start_time=d.start_time,
                end_time=d.end_time,
            )
        )

    db.commit()
    db.refresh(new_event)

    try:
        notify_today_events(db)
    except Exception:
        pass

    return _flatten_event(new_event)


# ─────────────────────── GET ALL EVENTS ───────────────────────
@router.get("/", response_model=List[EventResponse])
def get_all_events(db: Session = Depends(get_db)):
    events = (
        db.query(Event)
        .order_by(Event.start_date.asc())
        .all()
    )
    return [_flatten_event(e) for e in events]


# ─────────────────────── COUNT ───────────────────────
@router.get("/count")
def get_event_count(db: Session = Depends(get_db)):
    return {"total_events": db.query(Event).count()}


# ─────────────────────── UPDATE (ADMIN ONLY) ───────────────────────
@router.put("/{event_id}", response_model=EventResponse)
def update_event(
    event_id: int = Path(...),
    event: EventUpdate = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(403, "Only admins can edit events")

    existing = db.query(Event).filter(Event.id == event_id).first()
    if not existing:
        raise HTTPException(404, "Event not found")

    update_data = event.model_dump(exclude_unset=True)
    days_data = update_data.pop("days", None)

    # Cross-field validation on merged values
    merged_start = update_data.get("start_date", existing.start_date)
    merged_end = update_data.get("end_date", existing.end_date)
    if merged_end < merged_start:
        raise HTTPException(422, "End date must be on or after start date")

    # Duplicate check if key fields change
    merged_title = update_data.get("title_id", existing.title_id)
    merged_loc = update_data.get("location_id", existing.location_id)
    if (
        merged_title != existing.title_id
        or merged_loc != existing.location_id
        or merged_start != existing.start_date
    ):
        dup = (
            db.query(Event)
            .filter(
                Event.title_id == merged_title,
                Event.location_id == merged_loc,
                Event.start_date == merged_start,
                Event.id != event_id,
            )
            .first()
        )
        if dup:
            raise HTTPException(
                409,
                "Another event with the same title, location, and start date exists.",
            )

    for k, v in update_data.items():
        setattr(existing, k, v)

    # Replace days if provided
    if days_data is not None:
        # Enforce that days still cover start_date..end_date
        expected = set()
        cur = existing.start_date
        while cur <= existing.end_date:
            expected.add(cur)
            cur += timedelta(days=1)

        incoming_dates = sorted(d["day_date"] for d in days_data)
        if set(incoming_dates) != expected:
            raise HTTPException(
                422,
                "Event days must cover every date between start_date and end_date.",
            )

        db.query(EventDay).filter(EventDay.event_id == event_id).delete()
        for d in days_data:
            db.add(
                EventDay(
                    event_id=event_id,
                    day_date=d["day_date"],
                    start_time=d["start_time"],
                    end_time=d["end_time"],
                )
            )

    db.commit()
    db.refresh(existing)

    try:
        notify_today_events(db)
    except Exception:
        pass

    return _flatten_event(existing)


# ─────────────────────── DELETE (ADMIN ONLY) ───────────────────────
@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(403, "Only admins can delete events")

    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(404, "Event not found")

    db.query(Attendance).filter(Attendance.event_id == event_id).delete()
    db.delete(event)
    db.commit()
    return {"message": "Event deleted successfully"}


# ─────────────────────── CALENDAR VIEW ───────────────────────
@router.get("/calendar", response_model=dict)
def get_events_by_month(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
):
    # Month boundaries
    first_of_month = _today().replace(year=year, month=month, day=1)
    if month == 12:
        next_month = first_of_month.replace(year=year + 1, month=1)
    else:
        next_month = first_of_month.replace(month=month + 1)

    # Multi-day events: include if their range overlaps this month
    events = (
        db.query(Event)
        .filter(Event.start_date < next_month)
        .filter(Event.end_date >= first_of_month)
        .order_by(Event.start_date.asc())
        .all()
    )

    # Expand each event into one entry per day in range (clamped to month)
    expanded = []
    for e in events:
        flat = _flatten_event(e)
        cur = max(e.start_date, first_of_month)
        last = min(e.end_date, next_month - timedelta(days=1))
        while cur <= last:
            day_window = next((d for d in e.days if d.day_date == cur), None)
            expanded.append(
                {
                    **{k: v for k, v in flat.items() if k != "days"},
                    "calendar_date": cur,
                    "day_start_time": (
                        day_window.start_time if day_window else None
                    ),
                    "day_end_time": (
                        day_window.end_time if day_window else None
                    ),
                }
            )
            cur += timedelta(days=1)

    expanded.sort(key=lambda x: x["calendar_date"])

    return {
        "year": year,
        "month": month,
        "total_events": len(events),
        "events": expanded,
    }


# ─────────────────────── GET SINGLE ───────────────────────
@router.get("/{event_id}", response_model=EventResponse)
def get_event(event_id: int, db: Session = Depends(get_db)):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(404, "Event not found")
    return _flatten_event(event)