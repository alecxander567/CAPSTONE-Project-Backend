from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from app.core.database import Base


class DeviceState(Base):
    __tablename__ = "device_state"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String(50), unique=True, nullable=False, index=True)
    mode = Column(String(50), default="idle")

    pending_delete_id = Column(Integer, nullable=True)
    pending_delete_user_id = Column(
        Integer, nullable=True
    )  # NEW: ties the delete to a specific user

    recognition_finger_id = Column(Integer, nullable=True)
    recognition_matched = Column(Boolean, nullable=True)
    recognition_target_id = Column(Integer, nullable=True)
    last_seen = Column(DateTime, nullable=True)
    active_event_id = Column(Integer, ForeignKey("events.id"), nullable=True)
