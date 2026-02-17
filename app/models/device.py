from sqlalchemy import Column, Integer, String, Boolean
from app.core.database import Base


class DeviceState(Base):
    __tablename__ = "device_state"

    id = Column(Integer, primary_key=True, index=True)
    mode = Column(String(50), default="idle")
    pending_delete_id = Column(Integer, nullable=True)
    recognition_finger_id = Column(Integer, nullable=True)
    recognition_matched = Column(Boolean, nullable=True)
    recognition_target_id = Column(Integer, nullable=True) 
