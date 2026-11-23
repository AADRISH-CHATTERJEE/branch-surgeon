"""Pytest fixtures for the Refactory Backend control plane."""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Isolate settings before app import.
os.environ["REFACTORY_DATABASE_URL"] = "sqlite://"
os.environ["REFACTORY_JWT_SECRET"] = "test-secret-key-not-for-production"
os.environ["REFACTORY_SEED_ADMIN_EMAIL"] = "cli@refactory.dev"
os.environ["REFACTORY_SEED_ADMIN_PASSWORD"] = "refactory-dev"
os.environ["REFACTORY_SEED_ADMIN_NAME"] = "CLI Developer"

from refactory_backend.core.config import get_settings
from refactory_backend.core.security import hash_password
from refactory_backend.db.base import Base
from refactory_backend.db.session import get_db, reset_engine
from refactory_backend.main import create_app
from refactory_backend.models.user import User


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    get_settings.cache_clear()
    reset_engine()

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = TestingSessionLocal()

    user = User(
        email="cli@refactory.dev",
        full_name="CLI Developer",
        hashed_password=hash_password("refactory-dev"),
        is_active=True,
        is_superuser=True,
    )
    session.add(user)
    session.commit()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
        reset_engine()
        get_settings.cache_clear()


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    app = create_app()

    def _override_db() -> Generator[Session, None, None]:
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/auth/login",
        json={"email": "cli@refactory.dev", "password": "refactory-dev"},
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
