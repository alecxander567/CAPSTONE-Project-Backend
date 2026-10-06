from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List

from app.core.database import get_db
from app.models.location import Location
from app.models.user import User
from app.schemas.location import LocationCreate, LocationResponse
from app.core.security import get_current_user


router = APIRouter(prefix="/locations", tags=["Locations"])


def _normalize(name: str) -> str:
    return " ".join(name.strip().split()).lower()


@router.get("/", response_model=List[LocationResponse])
def list_locations(
    active_only: bool = True,
    db: Session = Depends(get_db),
):
    q = db.query(Location)
    if active_only:
        q = q.filter(Location.is_active == True)  # noqa: E712
    return q.order_by(Location.name.asc()).all()


@router.post("/", response_model=LocationResponse, status_code=201)
def create_location(
    payload: LocationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(403, "Only admins can create locations")

    normalized = _normalize(payload.name)
    existing = (
        db.query(Location)
        .filter(func.lower(func.trim(Location.name)) == normalized)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Location '{existing.name}' already exists.",
        )

    loc = Location(name=payload.name.strip())
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return loc