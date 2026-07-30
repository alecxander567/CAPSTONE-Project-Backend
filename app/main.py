from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from contextlib import asynccontextmanager
from sqlalchemy import text
from app.core.database import engine, Base
from app.routes import (
    auth,
    counts,
    events,
    notification,
    fingerprint,
    attendance,
    device,
)
from app.routes.notification_ws import websocket_endpoint
from app.core.background_task import event_notifier_loop
from app.routes.health import router as health
import asyncio
import logging

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    notifier_task = asyncio.create_task(event_notifier_loop())
    try:
        yield
    finally:
        notifier_task.cancel()
        try:
            await notifier_task
        except asyncio.CancelledError:
            logging.info("Notifier loop cancelled cleanly")


app = FastAPI(
    title="ARA Biometric Attendance System", version="1.0.0", lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://ara-system-app.vercel.app",
        "https://ara-system-51e92eids-alecxander567s-projects.vercel.app",
        "http://localhost:5173",
        "https://ara-system-app-git-main-alecxander567s-projects.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Uploads directory
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Serve static files
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Create database tables
Base.metadata.create_all(bind=engine)

# ── Add new columns if missing (for existing tables) ──────────────────────
# The create_all above only CREATES new tables, it doesn't ALTER existing
# ones.  Raw SQL below adds the columns introduced in this PR safely.
try:
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS claimed_by_device VARCHAR(50)"))
        conn.execute(text("ALTER TABLE device_state ADD COLUMN IF NOT EXISTS pending_delete_updated_at TIMESTAMP"))
        conn.commit()
except Exception as e:
    logging.warning(f"Could not add new columns (expected if they already exist): {e}")
# ─────────────────────────────────────────────────────────────────────────

# Include routers
app.include_router(auth.router)
app.include_router(counts.router)
app.include_router(events.router)
app.include_router(notification.router)
app.include_router(fingerprint.router)
app.include_router(attendance.router)
app.websocket("/ws/notifications/")(websocket_endpoint)
app.include_router(device.router)
app.include_router(health)


# Health check endpoint
@app.api_route("/ping", methods=["GET", "POST", "HEAD"], tags=["Health"])
async def ping(request: Request):
    return {
        "status": "ok",
        "message": f"Backend is alive! Method used: {request.method}",
    }
