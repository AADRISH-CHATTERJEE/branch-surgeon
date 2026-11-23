"""Aggregate API routers."""

from __future__ import annotations

from fastapi import APIRouter

from refactory_backend.api import auth, config, prompts, telemetry, workflows

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(config.router)
api_router.include_router(prompts.router)
api_router.include_router(workflows.router)
api_router.include_router(telemetry.router)
