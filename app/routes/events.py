from fastapi import APIRouter, Depends, HTTPException, status, Path, Body
from sqlalchemy.orm import Session
from typing import List

from app.core.database import get_db
from app.models.events import Event
from app.models.user import User
from app.schemas.event import EventCreate, EventResponse, EventUpdate
from app.core.security import get_current_user
from app.services.notifications import notify_today_events
from sqlalchemy import extract
from fastapi import Query
from typing import List
from app.schemas.event import EventResponse


router = APIRouter(prefix="/events", tags=["Events"])


# ------------------- ADDING OF EVENTS (ADMIN ONLY) -------------------
@router.post("/", response_model=EventResponse, status_code=201)
def create_event(
    event: EventCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(403, "Only admins can create events")

    new_event = Event(
        title=event.title,
        description=event.description,
        event_date=event.event_date,
        start_time=event.start_time,
        end_time=event.end_time,
        location=event.location,
        created_by=current_user.id,
    )

    db.add(new_event)
    db.commit()
    db.refresh(new_event)

    try:
        notify_today_events(db)
    except Exception as e:
        pass

    return new_event


# ------------------- GET ALL EVENTS -------------------
@router.get("/", response_model=List[EventResponse])
def get_all_events(db: Session = Depends(get_db)):
    events = (
        db.query(Event).order_by(Event.event_date.asc(), Event.start_time.asc()).all()
    )
    return events


# ------------------- COUNT ALL EVENTS -------------------
@router.get("/count")
def get_event_count(db: Session = Depends(get_db)):
    total = db.query(Event).count()
    return {"total_events": total}


# ------------------- UPDATE EVENT (ADMIN ONLY) -------------------
@router.put("/{event_id}", response_model=EventResponse)
def update_event(
    event_id: int = Path(..., description="ID of the event to update"),
    event: EventUpdate = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can edit events",
        )

    existing_event = db.query(Event).filter(Event.id == event_id).first()
    if not existing_event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    update_data = event.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(existing_event, field, value)

    db.commit()
    db.refresh(existing_event)

    try:
        notify_today_events(db)
    except Exception as e:
        pass

    return existing_event


# ------------------- DELETE EVENT (ADMIN ONLY) -------------------
@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can delete events",
        )

    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    db.delete(event)
    db.commit()

    return {"message": "Event deleted successfully"}


# ------------------- GET EVENTS BY MONTH (CALENDAR VIEW) -------------------
@router.get("/calendar", response_model=dict)
def get_events_by_month(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
):
    events = (
        db.query(Event)
        .filter(extract("year", Event.event_date) == year)
        .filter(extract("month", Event.event_date) == month)
        .order_by(Event.event_date.asc(), Event.start_time.asc())
        .all()
    )

    return {
        "year": year,
        "month": month,
        "total_events": len(events),
        "events": [
            EventResponse.from_orm(e) for e in events
        ],  
    }


# ------------------- GET SINGLE EVENT BY ID -------------------
@router.get("/{event_id}", response_model=EventResponse)
def get_event(event_id: int, db: Session = Depends(get_db)):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event
