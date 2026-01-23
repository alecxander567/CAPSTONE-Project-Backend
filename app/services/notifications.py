from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.models import Notification, Event, User
import logging

logger = logging.getLogger(__name__)

_sent_notifications = set()


def notify_today_events(db: Session):
    """
    Check for events happening today and create notifications.
    Uses in-memory cache and database constraints to prevent duplicates.

    NOTE: This is now a SYNC function (no async) since we removed WebSocket.
    """
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

        for user in users:
            notification_key = f"event_{event.id}_user_{user.id}"

            if notification_key in _sent_notifications:
                logger.debug(
                    f"Skipping duplicate notification (cached): {notification_key}"
                )
                continue

            existing = (
                db.query(Notification)
                .filter(
                    Notification.user_id == user.id,
                    Notification.event_id == event.id,
                    Notification.type == "event",
                )
                .first()
            )

            if existing:
                _sent_notifications.add(notification_key)
                logger.debug(f"Notification already exists in DB: {notification_key}")
                continue

            notification = Notification(
                user_id=user.id,
                event_id=event.id,
                title="Event Starting Now",
                message=f"The event '{event.title}' is starting at {event.start_time.strftime('%I:%M %p')}!",
                type="event",
                is_read=False,
            )

            try:
                db.add(notification)
                db.commit()
                db.refresh(notification)

                _sent_notifications.add(notification_key)

                logger.info(
                    f"Created notification {notification.id} for user {user.id}, event {event.id}"
                )

            except IntegrityError as e:
                db.rollback()
                _sent_notifications.add(notification_key)
                logger.warning(
                    f"Duplicate notification prevented by DB constraint: {notification_key}"
                )

            except Exception as e:
                db.rollback()
                logger.error(f"Failed to create notification: {e}")


def clear_notification_cache():
    """
    Clear the in-memory notification cache.
    Call this at midnight or when you want to allow notifications to be resent.
    """
    global _sent_notifications
    count = len(_sent_notifications)
    _sent_notifications.clear()
    logger.info(f"Notification cache cleared ({count} entries removed)")
