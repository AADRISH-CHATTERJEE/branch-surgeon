"""Authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from refactory_backend.core.deps import AuthServiceDep, CurrentUser
from refactory_backend.schemas.auth import LoginRequest, RefreshRequest, TokenResponse, UserPublic

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Exchange CLI credentials for JWT tokens",
)
def login(body: LoginRequest, auth_service: AuthServiceDep) -> TokenResponse:
    user = auth_service.authenticate(body.email, body.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    return auth_service.issue_tokens(user)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh an access token using a refresh token",
)
def refresh(body: RefreshRequest, auth_service: AuthServiceDep) -> TokenResponse:
    tokens = auth_service.refresh_tokens(body.refresh_token)
    if tokens is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    return tokens


@router.get(
    "/me",
    response_model=UserPublic,
    summary="Return the authenticated CLI user profile",
)
def me(current_user: CurrentUser) -> UserPublic:
    return UserPublic.model_validate(current_user)
