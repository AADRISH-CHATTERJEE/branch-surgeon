"""`refactory whoami` — show the authenticated backend user."""

from __future__ import annotations

from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.console import console
from refactory.cli.ui.tables import key_value_table


def whoami() -> None:
    """Call GET /auth/me and display the current control-plane user."""
    try:
        container = get_container()
        client = container.require_backend_client()
        user = client.get_current_user()
        console.print(
            key_value_table(
                "Backend User",
                {
                    "email": user.email,
                    "name": user.full_name,
                    "id": user.id,
                    "active": user.is_active,
                    "superuser": user.is_superuser,
                    "backend": client.base_url,
                },
            )
        )
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)
