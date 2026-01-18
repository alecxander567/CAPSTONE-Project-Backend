# app/routes/notification.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from app.core.database import get_db
from app.models import Notification, Event, User
from app.routes.notification_ws import manager
from app.core.security import get_current_user

router = APIRouter(prefix="/notifications", tags=["Notifications"])


# ------------------- GETS CURRENT USER NOTIFICATION -------------------
@router.get("/")
def get_notifications(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:

        notifications = (
            db.query(Notification)
            .filter(Notification.user_id == current_user.id)
            .order_by(Notification.id.desc())
            .all()
        )

        result = []
        for n in notifications:
            result.append(
                {
                    "id": n.id,
                    "user_id": n.user_id,
                    "event_id": n.event_id,
                    "title": n.title,
                    "message": n.message,
                    "type": n.type,
                    "is_read": n.is_read,
                    "timestamp": n.timestamp.isoformat() if n.timestamp else None,
                }
            )

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------- MARK NOTIFICATION AS READ -------------------
@router.patch("/{notification_id}/read")
def mark_notification_as_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notification = (
        db.query(Notification)
        .filter(
            Notification.id == notification_id, Notification.user_id == current_user.id
        )
        .first()
    )

    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    notification.is_read = True
    db.commit()

    return {"status": "success", "id": notification_id}


# ------------------- DELETE NOTIFICATION -------------------
@router.delete("/{notification_id}")
def delete_notification(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notification = (
        db.query(Notification)
        .filter(
            Notification.id == notification_id, Notification.user_id == current_user.id
        )
        .first()
    )

    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    db.delete(notification)
    db.commit()

    return {"status": "deleted", "id": notification_id}


# ------------------- DELETE ALL NOTIFICATIONS -------------------
@router.delete("/")
def delete_all_notifications(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    try:
        count = (
            db.query(Notification)
            .filter(Notification.user_id == current_user.id)
            .delete()
        )
        db.commit()
        return {"status": "success", "deleted_count": count}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
