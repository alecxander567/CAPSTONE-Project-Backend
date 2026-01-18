from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    event_id = Column(
        Integer, ForeignKey("events.id", ondelete="SET NULL"), nullable=True
    )

    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)

    type = Column(String(50), nullable=False)

    is_read = Column(Boolean, default=False)

    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="notifications")
    event = relationship("Event", back_populates="notifications")
