from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from contextlib import asynccontextmanager
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
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Uploads directory
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Serve static files
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Create database tables
Base.metadata.create_all(bind=engine)

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
@app.api_route("/ping", methods=["GET", "POST"], tags=["Health"])
async def ping(request: Request):
    return {
        "status": "ok",
        "message": f"Backend is alive! Method used: {request.method}",
    }
