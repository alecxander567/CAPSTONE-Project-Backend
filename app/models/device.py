from sqlalchemy import Column, Integer, String
from app.core.database import Base


class DeviceState(Base):
    __tablename__ = "device_state"

    id = Column(Integer, primary_key=True, index=True)
    mode = Column(String(50), default="idle")  
    pending_delete_id = Column(Integer, nullable=True)
