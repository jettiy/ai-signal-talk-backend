"""
SQLAlchemy ORM 모델
"""
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, Integer, Float, Text, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    nickname = Column(String, unique=True, index=True, nullable=False)
    level = Column(String, default="LEVEL_01")
    is_pro = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    messages = relationship("ChatMessage", back_populates="user")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    nickname = Column(String, nullable=False)
    grade = Column(String, default="LV.01")
    content = Column(Text, nullable=False)
    is_bot = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="messages")


class ProApplication(Base):
    __tablename__ = "pro_applications"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    email = Column(String, nullable=False)
    status = Column(String, default="PENDING")  # PENDING / CONTACTED / COMPLETED
    created_at = Column(DateTime, default=datetime.utcnow)


class AiSignal(Base):
    __tablename__ = "ai_signals"

    id = Column(String, primary_key=True, index=True)
    symbol = Column(String, nullable=False, index=True)
    entry_price = Column(Float, nullable=False)
    target_price = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    confidence = Column(Integer, nullable=False)
    rationale = Column(Text, nullable=False)
    signal_type = Column(String, nullable=False)  # LONG / SHORT
    timeframe = Column(String, default="30M")
    model = Column(String, default="MiMo")
    created_at = Column(DateTime, default=datetime.utcnow)


class MarketCache(Base):
    __tablename__ = "market_cache"

    id = Column(String, primary_key=True, index=True)
    symbol = Column(String, unique=True, nullable=False)
    price = Column(Float, nullable=False)
    change = Column(Float, default=0.0)
    change_pct = Column(Float, default=0.0)
    updated_at = Column(DateTime, default=datetime.utcnow)
