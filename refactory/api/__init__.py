"""Local REST API — presentation layer over ServiceContainer.

Sibling to the CLI. Does not replace the control-plane backend
(``backend/refactory_backend``), which remains auth/config-only.
"""

from __future__ import annotations

__all__ = ["create_app"]
