from fastapi import FastAPI
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
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
import asyncio

import logging

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


app = FastAPI(title="ARA Biometric Attendance System", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "https://aras-bt-system.netlify.app/",
        "https://ara-system-app.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Uploads directory
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Serve static files (profile pictures)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

Base.metadata.create_all(bind=engine)

app.include_router(auth.router)
app.include_router(counts.router)
app.include_router(events.router)
app.include_router(notification.router)
app.include_router(fingerprint.router)
app.include_router(attendance.router)
app.websocket("/ws/notifications/")(websocket_endpoint)
app.include_router(device.router)


@app.on_event("startup")
async def start_background_tasks():
    asyncio.create_task(event_notifier_loop())


@app.api_route("/ping", methods=["GET", "POST"], tags=["Health"])
async def ping(request: Request):
    return {
        "status": "ok",
        "message": f"Backend is alive! Method used: {request.method}",
    }
