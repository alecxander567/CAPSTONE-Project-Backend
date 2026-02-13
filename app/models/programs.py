from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from app.core.database import Base


class Program(Base):
    __tablename__ = "programs"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(20), unique=True, nullable=False)  
    name = Column(String(100), nullable=False) 

    users = relationship("User", back_populates="program")
