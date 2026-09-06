import pytest
from sqlalchemy.orm import Session

from app import auth
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


def test_signup_and_login(db):
    user = auth.signup(db, "Alice@Example.com", "correcthorsebattery")
    assert user.email == "alice@example.com"  # normalized to lowercase
    assert user.hashed_password != "correcthorsebattery"  # actually hashed, not stored plain

    logged_in = auth.login(db, "alice@example.com", "correcthorsebattery")
    assert logged_in.id == user.id


def test_signup_rejects_short_password(db):
    with pytest.raises(auth.AuthError):
        auth.signup(db, "bob@example.com", "short")


def test_signup_rejects_duplicate_email(db):
    auth.signup(db, "carol@example.com", "correcthorsebattery")
    with pytest.raises(auth.AuthError):
        auth.signup(db, "carol@example.com", "anotherpassword")


def test_login_rejects_wrong_password(db):
    auth.signup(db, "dave@example.com", "correcthorsebattery")
    with pytest.raises(auth.AuthError):
        auth.login(db, "dave@example.com", "wrongpassword")


def test_login_rejects_unknown_email(db):
    with pytest.raises(auth.AuthError):
        auth.login(db, "nobody@example.com", "whatever123")


def test_jwt_roundtrip(db):
    user = auth.signup(db, "erin@example.com", "correcthorsebattery")
    token = auth.create_access_token(user.id)
    decoded_id = auth.decode_access_token(token)
    assert decoded_id == user.id


def test_jwt_rejects_garbage_token():
    with pytest.raises(auth.AuthError):
        auth.decode_access_token("not-a-real-token")
