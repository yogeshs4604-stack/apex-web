from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .config import settings
from .models import DailyUsage


class QuotaExceededError(Exception):
    def __init__(self, limit: int):
        super().__init__(
            f"Daily message limit reached ({limit}/day on the free tier). Try again tomorrow."
        )
        self.limit = limit


def _today():
    return datetime.now(timezone.utc).date()


def check_and_increment_quota(db: Session, user_id: int) -> int:
    """Atomically-enough (single-process SQLite/Postgres row) check-then-increment.

    Returns the new message count for today. Raises QuotaExceededError if the
    user already hit the daily cap -- this is a real, enforced ceiling, not
    an aspirational comment.
    """
    today = _today()
    record = (
        db.query(DailyUsage)
        .filter(DailyUsage.user_id == user_id, DailyUsage.day == today)
        .first()
    )
    if record is None:
        record = DailyUsage(user_id=user_id, day=today, message_count=0)
        db.add(record)
        db.flush()

    if record.message_count >= settings.DAILY_MESSAGE_QUOTA:
        raise QuotaExceededError(settings.DAILY_MESSAGE_QUOTA)

    record.message_count += 1
    db.commit()
    return record.message_count


def remaining_quota(db: Session, user_id: int) -> int:
    today = _today()
    record = (
        db.query(DailyUsage)
        .filter(DailyUsage.user_id == user_id, DailyUsage.day == today)
        .first()
    )
    used = record.message_count if record else 0
    return max(0, settings.DAILY_MESSAGE_QUOTA - used)
