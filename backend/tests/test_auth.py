"""Authentication endpoint tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_login_success(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        json={"email": "cli@refactory.dev", "password": "refactory-dev"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["expires_in"] > 0


def test_login_rejects_bad_password(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        json={"email": "cli@refactory.dev", "password": "wrong-password"},
    )
    assert response.status_code == 401


def test_login_rejects_unknown_user(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "refactory-dev"},
    )
    assert response.status_code == 401


def test_me_requires_auth(client: TestClient) -> None:
    response = client.get("/auth/me")
    assert response.status_code == 401


def test_me_returns_profile(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/auth/me", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "cli@refactory.dev"
    assert body["is_active"] is True
    assert body["full_name"] == "CLI Developer"


def test_refresh_issues_new_tokens(client: TestClient) -> None:
    login = client.post(
        "/auth/login",
        json={"email": "cli@refactory.dev", "password": "refactory-dev"},
    )
    refresh_token = login.json()["refresh_token"]
    response = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]


def test_refresh_rejects_access_token(client: TestClient) -> None:
    login = client.post(
        "/auth/login",
        json={"email": "cli@refactory.dev", "password": "refactory-dev"},
    )
    access_token = login.json()["access_token"]
    response = client.post("/auth/refresh", json={"refresh_token": access_token})
    assert response.status_code == 401


def test_refresh_rejects_garbage(client: TestClient) -> None:
    response = client.post("/auth/refresh", json={"refresh_token": "not-a-jwt"})
    assert response.status_code == 401
