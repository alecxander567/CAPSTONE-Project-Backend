from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.models import Notification, Event, User
import logging
from app.services.firebase_service import send_push_notification
import threading

logger = logging.getLogger(__name__)

_sent_notifications = set()

# Philippine Time (UTC+8)
PH_TZ = timezone(timedelta(hours=8))


def notify_today_events(db: Session):
    now = datetime.now(PH_TZ).replace(tzinfo=None)
    today = now.date()

    events_today = db.query(Event).filter(Event.event_date == today).all()
    if not events_today:
        return

    users = db.query(User).all()

    for event in events_today:
        event_datetime = datetime.combine(event.event_date, event.start_time)
        time_diff = (event_datetime - now).total_seconds()

        # Only notify within 30 mins before event
        if not (-60 < time_diff <= 1800):
            continue

        sent_tokens = set()

        for user in users:
            notification_key = f"event_{event.id}_user_{user.id}"

            if notification_key in _sent_notifications:
                continue

            # Check if notification already exists (DB protection)
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
                continue

            notification = Notification(
                user_id=user.id,
                event_id=event.id,
                title=event.title,
                message=(
                    f"{event.description}\n\n"
                    f"Starts at {event.start_time.strftime('%I:%M %p')}"
                ),
                type="event",
                is_read=False,
            )

            try:
                db.add(notification)
                db.commit()
                db.refresh(notification)

                _sent_notifications.add(notification_key)

                logger.info(
                    f"Notification {notification.id} created for user {user.id}, event {event.id}"
                )

                if user.device_token and user.device_token not in sent_tokens:
                    sent_tokens.add(user.device_token)

                    threading.Thread(
                        target=send_push_notification,
                        args=(
                            user.device_token,
                            f"EVENT REMINDER: {event.title}",
                            f"Starting in 5 minutes at {event.start_time.strftime('%I:%M %p')}\n{event.description}",
                        ),
                        daemon=True,
                    ).start()

            except IntegrityError:
                db.rollback()
                _sent_notifications.add(notification_key)
                logger.warning(
                    f"Duplicate prevented by DB constraint: {notification_key}"
                )

            except Exception as e:
                db.rollback()
                logger.error(f"Failed to create notification: {e}")


def clear_notification_cache():
    global _sent_notifications
    count = len(_sent_notifications)
    _sent_notifications.clear()
    logger.info(f"Notification cache cleared ({count} entries removed)")
