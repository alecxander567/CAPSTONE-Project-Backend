from fastapi import FastAPI
from app.core.database import engine, Base
from app.models.user import User
from app.routes import auth
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="ARA Biometric Attendance System", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)

app.include_router(auth.router)


@app.get("/")
def root():
    return {"message": "Backend is running 🚀"}
