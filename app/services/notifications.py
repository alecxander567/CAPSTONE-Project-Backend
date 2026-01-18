# app/services/notifications.py
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models import Notification, Event, User
from app.routes.notification_ws import manager


async def notify_today_events(db: Session):
    now = datetime.now()
    today = now.date()

    events_today = db.query(Event).filter(Event.event_date == today).all()

    if not events_today:
        return

    users = db.query(User).all()

    for event in events_today:
        event_datetime = datetime.combine(event.event_date, event.start_time)
        current_datetime = datetime.now()

        time_diff = (event_datetime - current_datetime).total_seconds()

        if not (-120 <= time_diff <= 120):
            continue

        notifications_sent = 0
        for user in users:
            exists = (
                db.query(Notification)
                .filter(
                    Notification.user_id == user.id,
                    Notification.event_id == event.id,
                    Notification.type == "event",
                )
                .first()
            )
            if exists:
                continue

            notification = Notification(
                user_id=user.id,
                event_id=event.id,
                title="Event Starting Now",
                message=f"The event '{event.title}' is starting at {event.start_time.strftime('%I:%M %p')}!",
                type="event",
                timestamp=datetime.utcnow(),
            )

            db.add(notification)
            db.commit()
            db.refresh(notification)

            notification_data = {
                "id": notification.id,
                "user_id": notification.user_id,
                "title": notification.title,
                "message": notification.message,
                "type": notification.type,
                "is_read": notification.is_read,
                "timestamp": notification.timestamp.isoformat(),
                "event_id": notification.event_id,
            }

            await manager.send_notification(notification_data)
            notifications_sent += 1
