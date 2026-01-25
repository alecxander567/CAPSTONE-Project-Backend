from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.database import engine, Base
from app.models.user import User
from app.routes import auth, counts, events, notification, fingerprint
from app.routes.notification_ws import websocket_endpoint
from app.core.background_task import event_notifier_loop
import asyncio

app = FastAPI(title="ARA Biometric Attendance System", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "ws://localhost:8000",
        "ws://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)

app.include_router(auth.router)
app.include_router(counts.router)
app.include_router(events.router)
app.include_router(notification.router)
app.include_router(fingerprint.router)

app.websocket("/ws/notifications/")(websocket_endpoint)


@app.get("/")
def root():
    return {"message": "Backend is running."}


@app.on_event("startup")
async def start_background_tasks():
    asyncio.create_task(event_notifier_loop())
