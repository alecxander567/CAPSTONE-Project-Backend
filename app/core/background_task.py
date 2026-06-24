import asyncio
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
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

    # Add a counter for connection failures
    consecutive_failures = 0
    max_failures = 5

    while True:
        db = None
        try:
            # Create a fresh session for each iteration
            db = SessionLocal()

            # Test the connection before using it
            try:
                db.execute("SELECT 1")
            except Exception as e:
                logger.warning(f"Connection test failed: {e}")
                # Close and recreate the session
                db.close()
                db = SessionLocal()

            # Process events
            notify_today_events(db)
            logger.debug("Event notification check completed")

            # Reset failure counter on success
            consecutive_failures = 0

        except SQLAlchemyError as e:
            consecutive_failures += 1
            logger.error(
                f"Database error in event_notifier_loop (attempt {consecutive_failures}): {e}"
            )

            if consecutive_failures >= max_failures:
                logger.critical(
                    f"Too many database failures ({consecutive_failures}), restarting loop..."
                )
                await asyncio.sleep(60)  # Longer delay before retry
            else:
                await asyncio.sleep(10)  # Short delay on error

        except Exception as e:
            logger.error(f"Unexpected error in event_notifier_loop: {e}", exc_info=True)
            await asyncio.sleep(30)

        finally:
            # Safely close the session if it exists
            if db:
                try:
                    db.close()
                except Exception as e:
                    logger.warning(f"Error closing database session: {e}")
                    # Don't re-raise, continue the loop

        # Normal sleep between iterations
        await asyncio.sleep(30)
