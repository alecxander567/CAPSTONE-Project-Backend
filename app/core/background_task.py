import asyncio
from datetime import datetime
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.services.notifications import notify_today_events
import logging

logger = logging.getLogger(__name__)


async def event_notifier_loop():
    """
    Background task that checks for events every 60 seconds.
    Calls the SYNC notify_today_events function (no await needed).
    """
    logger.info("Event notifier loop started")

    while True:
        try:
            db: Session = SessionLocal()
            try:
                notify_today_events(db)
                logger.debug("Event notification check completed")
            except Exception as e:
                logger.error(f"Error processing events: {e}")
                import traceback

                traceback.print_exc()
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Critical error in event_notifier_loop: {e}")
            import traceback

            traceback.print_exc()

        # Wait 60 seconds before next check
        await asyncio.sleep(60)
