from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.events import Event
from app.schemas.event import EventCreate, EventResponse
from app.core.security import get_current_user
from app.models.user import User

router = APIRouter(prefix="/events", tags=["Events"])


# ------------------- ADDING OF EVENTS (ADMIN ONLY) -------------------
@router.post("/", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
def create_event(
    event: EventCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    # Role check
    if current_user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can create events",
        )

    new_event = Event(
        title=event.title,
        description=event.description,
        event_date=event.event_date,
        start_time=event.start_time,
        end_time=event.end_time,
        location=event.location,
        created_by=current_user["user_id"],  
    )

    db.add(new_event)
    db.commit()
    db.refresh(new_event)

    return new_event


# ------------------- GET ALL EVENTS -------------------
from typing import List


@router.get("/", response_model=List[EventResponse])
def get_all_events(db: Session = Depends(get_db)):
    events = (
        db.query(Event).order_by(Event.event_date.asc(), Event.start_time.asc()).all()
    )
    return events


# ------------------- UPDATE EVENT (ADMIN ONLY) -------------------
from fastapi import Path, Body
from app.schemas.event import EventUpdate


@router.put("/{event_id}", response_model=EventResponse)
def update_event(
    event_id: int = Path(..., description="ID of the event to update"),
    event: EventUpdate = Body(...), 
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    # Role check
    if current_user["role"] != "admin":
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

    return existing_event


# ------------------- DELETE EVENT (ADMIN ONLY) -------------------
@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    # Role check
    if current_user["role"] != "admin":
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
