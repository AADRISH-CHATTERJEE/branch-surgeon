"""Aggregate local API routers."""

from __future__ import annotations

from fastapi import APIRouter

from refactory.api.routes import (
    activity,
    branch_surgeon,
    documentation,
    graph,
    history,
    index,
    organization_rules,
    organizations,
    recommend,
    repository,
    review,
    rules,
    transform,
)

api_router = APIRouter()
api_router.include_router(repository.router)
api_router.include_router(branch_surgeon.router)
api_router.include_router(rules.router)
api_router.include_router(organization_rules.router)
api_router.include_router(organizations.router)
api_router.include_router(history.router)
api_router.include_router(review.router)
api_router.include_router(recommend.router)
api_router.include_router(transform.router, prefix="/transform")
api_router.include_router(transform.router, prefix="/transformations")
api_router.include_router(graph.router)
api_router.include_router(index.router)
api_router.include_router(activity.router)
api_router.include_router(documentation.router)
