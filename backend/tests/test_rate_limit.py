import pytest
from sqlalchemy.orm import Session

from app import auth, rate_limit
from app.config import settings
from app.db import Base, SessionLocal, engine


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_quota_allows_up_to_limit(db):
    user = auth.signup(db, "quota1@example.com", "correcthorsebattery")
    assert settings.DAILY_MESSAGE_QUOTA == 3  # set in conftest.py for testability
    for expected_count in (1, 2, 3):
        count = rate_limit.check_and_increment_quota(db, user.id)
        assert count == expected_count


def test_quota_blocks_after_limit(db):
    user = auth.signup(db, "quota2@example.com", "correcthorsebattery")
    for _ in range(settings.DAILY_MESSAGE_QUOTA):
        rate_limit.check_and_increment_quota(db, user.id)

    with pytest.raises(rate_limit.QuotaExceededError):
        rate_limit.check_and_increment_quota(db, user.id)


def test_quota_is_per_user(db):
    user_a = auth.signup(db, "quota3a@example.com", "correcthorsebattery")
    user_b = auth.signup(db, "quota3b@example.com", "correcthorsebattery")
    for _ in range(settings.DAILY_MESSAGE_QUOTA):
        rate_limit.check_and_increment_quota(db, user_a.id)

    with pytest.raises(rate_limit.QuotaExceededError):
        rate_limit.check_and_increment_quota(db, user_a.id)

    # user B is unaffected by user A exhausting their quota
    count = rate_limit.check_and_increment_quota(db, user_b.id)
    assert count == 1


def test_remaining_quota_reporting(db):
    user = auth.signup(db, "quota4@example.com", "correcthorsebattery")
    assert rate_limit.remaining_quota(db, user.id) == settings.DAILY_MESSAGE_QUOTA
    rate_limit.check_and_increment_quota(db, user.id)
    assert rate_limit.remaining_quota(db, user.id) == settings.DAILY_MESSAGE_QUOTA - 1
