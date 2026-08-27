from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from contextlib import asynccontextmanager
from sqlalchemy import text
from app.core.database import engine, Base, get_db_context
from app.routes import (
    auth,
    counts,
    events,
    notification,
    fingerprint,
    attendance,
    device,
)
from app.core.background_task import event_notifier_loop
from app.utils.device import heal_stale_device_modes
from app.routes.health import router as health
import asyncio
import logging

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


async def device_watchdog_loop():
    while True:
        try:
            with get_db_context() as db:
                healed = heal_stale_device_modes(db)
                if healed:
                    logging.warning(f"Watchdog: reset {healed} stuck device(s) to idle")
        except Exception as e:
            logging.error(f"Watchdog error: {e}")
        await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)

    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS claimed_by_device VARCHAR(50)"
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE device_state ADD COLUMN IF NOT EXISTS pending_delete_updated_at TIMESTAMP"
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE device_state ADD COLUMN IF NOT EXISTS mode_updated_at TIMESTAMP"
                )
            )
            conn.commit()
    except Exception as e:
        logging.warning(
            f"Could not add new columns (expected if they already exist): {e}"
        )

    notifier_task = asyncio.create_task(event_notifier_loop())
    watchdog_task = asyncio.create_task(device_watchdog_loop())
    try:
        yield
    finally:
        notifier_task.cancel()
        watchdog_task.cancel()
        for t in (notifier_task, watchdog_task):
            try:
                await t
            except asyncio.CancelledError:
                logging.info("Background task cancelled cleanly")


app = FastAPI(
    title="ARA Biometric Attendance System", version="1.0.0", lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://ara-system-app.vercel.app",
        "https://ara-system-app-git-main-alecxander567s-projects.vercel.app",
        "http://localhost:5173",
    ],
    allow_origin_regex=r"https://ara-system-[a-z0-9]+-alecxander567s-projects\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

app.include_router(auth.router)
app.include_router(counts.router)
app.include_router(events.router)
app.include_router(notification.router)
app.include_router(fingerprint.router)
app.include_router(attendance.router)
app.include_router(device.router)
app.include_router(health)


@app.api_route("/ping", methods=["GET", "POST", "HEAD"], tags=["Health"])
async def ping(request: Request):
    return {
        "status": "ok",
        "message": f"Backend is alive! Method used: {request.method}",
    }
