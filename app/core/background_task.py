# app/core/background_task.py
import asyncio
from datetime import datetime
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.services.notifications import notify_today_events


async def event_notifier_loop():
    """Background task that checks for events every 60 seconds"""

    while True:
        try:
            db: Session = SessionLocal()
            await notify_today_events(db)
        except Exception as e:
            import traceback

            traceback.print_exc()
        finally:
            db.close()

        await asyncio.sleep(60)
