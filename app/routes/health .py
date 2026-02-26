from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.core.database import get_db

router = APIRouter()


# ------------------- HELPS TO KEEP DATABASE AWAKE -------------------
@router.get("/keep-alive-db")
def keep_alive_db(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "Neon database is awake"}
