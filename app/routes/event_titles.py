from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List

from app.core.database import get_db
from app.models.event_title import EventTitle
from app.models.user import User
from app.schemas.event_title import EventTitleCreate, EventTitleResponse
from app.core.security import get_current_user


router = APIRouter(prefix="/event-titles", tags=["Event Titles"])


def _normalize(name: str) -> str:
    return " ".join(name.strip().split()).lower()


@router.get("/", response_model=List[EventTitleResponse])
def list_titles(
    active_only: bool = True,
    db: Session = Depends(get_db),
):
    q = db.query(EventTitle)
    if active_only:
        q = q.filter(EventTitle.is_active == True)  # noqa: E712
    return q.order_by(EventTitle.name.asc()).all()


@router.post("/", response_model=EventTitleResponse, status_code=201)
def create_title(
    payload: EventTitleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(403, "Only admins can create event titles")

    normalized = _normalize(payload.name)
    existing = (
        db.query(EventTitle)
        .filter(func.lower(func.trim(EventTitle.name)) == normalized)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Title '{existing.name}' already exists.",
        )

    title = EventTitle(name=payload.name.strip())
    db.add(title)
    db.commit()
    db.refresh(title)
    return title