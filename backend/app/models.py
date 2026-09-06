from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from .db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    usage_records = relationship("DailyUsage", back_populates="user")


class DailyUsage(Base):
    """One row per (user, day). Incremented on every user chat message, checked before allowing one.

    This is the real enforcement mechanism behind "free but not unlimited" -- it's a plain
    counter in the database, not a comment describing an intended limit.
    """
    __tablename__ = "daily_usage"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    day = Column(Date, default=lambda: datetime.now(timezone.utc).date())
    message_count = Column(Integer, default=0)

    user = relationship("User", back_populates="usage_records")
