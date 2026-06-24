import asyncio
from sqlalchemy.exc import SQLAlchemyError
from app.core.database import SessionLocal
from app.services.notifications import notify_today_events
import logging

logger = logging.getLogger(__name__)


async def event_notifier_loop():
    """
    Background task that checks for events every 30 seconds.
    """
    logger.info("Event notifier loop started")

    consecutive_failures = 0
    max_failures = 5

    while True:
        db = None
        try:
            db = SessionLocal()
            notify_today_events(db)
            logger.debug("Event notification check completed")
            consecutive_failures = 0

        except SQLAlchemyError as e:
            consecutive_failures += 1
            logger.error(
                f"Database error in event_notifier_loop (attempt {consecutive_failures}): {e}"
            )
            if db:
                try:
                    db.rollback()
                except Exception as rollback_err:
                    logger.warning(f"Rollback failed: {rollback_err}")

            if consecutive_failures >= max_failures:
                logger.critical(
                    f"Too many database failures ({consecutive_failures}), backing off..."
                )
                await asyncio.sleep(60)
            else:
                await asyncio.sleep(10)

        except Exception as e:
            logger.error(f"Unexpected error in event_notifier_loop: {e}", exc_info=True)
            await asyncio.sleep(30)

        finally:
            if db:
                try:
                    db.close()
                except Exception as e:
                    logger.warning(f"Error closing database session: {e}")

        await asyncio.sleep(30)
