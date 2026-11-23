"""HTTP client for the Refactory control-plane backend."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

import httpx

from refactory.backend.auth import TokenStore
from refactory.backend.exceptions import (
    BackendAuthError,
    BackendNotConfiguredError,
    BackendResponseError,
    BackendUnavailableError,
)
from refactory.backend.models import (
    BackendUser,
    CLIConfig,
    ControlPlaneConfigBundle,
    OrganizationConfig,
    PromptList,
    RepositoryConfig,
    ReviewPrompt,
    ReviewWorkflow,
    TelemetryAck,
    TelemetryPayload,
    TokenPair,
    WorkflowList,
)

if TYPE_CHECKING:
    from loguru import Logger


class BackendClient:
    """Typed client for auth, prompts, workflows, and telemetry."""

    def __init__(
        self,
        base_url: str,
        *,
        token_store: TokenStore | None = None,
        logger: "Logger | None" = None,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        url = (base_url or "").strip().rstrip("/")
        if not url:
            raise BackendNotConfiguredError(
                "Backend URL is not configured. Set REFACTORY_BACKEND_URL."
            )
        self._base_url = url
        self._token_store = token_store or TokenStore()
        self._logger = logger
        self._timeout = timeout
        self._transport = transport

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def token_store(self) -> TokenStore:
        return self._token_store

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def login(self, email: str, password: str) -> TokenPair:
        """Authenticate and persist JWTs locally (password is never stored)."""
        data = self._request(
            "POST",
            "/auth/login",
            json={"email": email, "password": password},
            auth=False,
        )
        tokens = TokenPair.model_validate(data)
        self._token_store.save_tokens(tokens, backend_url=self._base_url)
        self._log("info", "Logged in to {} as {}", self._base_url, email)
        return tokens

    def refresh_token(self) -> TokenPair:
        """Exchange the stored refresh token for a new token pair."""
        auth = self._token_store.load()
        if auth is None:
            raise BackendAuthError("Not logged in. Run `refactory login`.")
        data = self._request(
            "POST",
            "/auth/refresh",
            json={"refresh_token": auth.refresh_token},
            auth=False,
        )
        tokens = TokenPair.model_validate(data)
        self._token_store.save_tokens(tokens, backend_url=self._base_url)
        self._log("info", "Refreshed backend access token")
        return tokens

    def get_current_user(self) -> BackendUser:
        data = self._request("GET", "/auth/me", auth=True)
        return BackendUser.model_validate(data)

    def logout(self) -> bool:
        """Clear local tokens. Does not call the backend."""
        cleared = self._token_store.clear()
        self._log("info", "Cleared local backend credentials")
        return cleared

    # ------------------------------------------------------------------
    # Control-plane resources
    # ------------------------------------------------------------------

    def get_config(
        self,
        *,
        organization_id: str | None = None,
        repository_id: str | None = None,
    ) -> CLIConfig:
        """Download compact CLI control-plane configuration (no source code)."""
        params: list[str] = []
        if organization_id:
            params.append(f"organization_id={organization_id}")
        if repository_id:
            params.append(f"repository_id={repository_id}")
        path = "/config"
        if params:
            path = f"{path}?{'&'.join(params)}"
        data = self._request("GET", path, auth=True)
        return CLIConfig.model_validate(data)

    def get_config_bundle(
        self,
        *,
        organization_id: str | None = None,
        repository_id: str | None = None,
    ) -> ControlPlaneConfigBundle:
        """Download the full organization/repository configuration bundle."""
        params: list[str] = []
        if organization_id:
            params.append(f"organization_id={organization_id}")
        if repository_id:
            params.append(f"repository_id={repository_id}")
        path = "/config/bundle"
        if params:
            path = f"{path}?{'&'.join(params)}"
        data = self._request("GET", path, auth=True)
        return ControlPlaneConfigBundle.model_validate(data)

    def list_prompts(self) -> PromptList:
        data = self._request("GET", "/prompts", auth=True)
        return PromptList.model_validate(data)

    def list_workflows(self) -> WorkflowList:
        data = self._request("GET", "/workflows", auth=True)
        return WorkflowList.model_validate(data)

    def get_organization(self, organization_id: str) -> OrganizationConfig:
        data = self._request("GET", f"/organizations/{organization_id}", auth=True)
        return OrganizationConfig.model_validate(data)

    def get_repository(self, repository_id: str) -> RepositoryConfig:
        data = self._request("GET", f"/repositories/{repository_id}", auth=True)
        return RepositoryConfig.model_validate(data)

    def get_review_prompt(self, version: str | None = None) -> ReviewPrompt:
        path = "/prompts/review"
        if version:
            path = f"{path}?version={version}"
        data = self._request("GET", path, auth=True)
        return ReviewPrompt.model_validate(data)

    def get_review_workflow(self, version: str | None = None) -> ReviewWorkflow:
        path = "/workflows/review"
        if version:
            path = f"{path}?version={version}"
        data = self._request("GET", path, auth=True)
        return ReviewWorkflow.model_validate(data)

    def send_telemetry(self, event: TelemetryPayload) -> TelemetryAck:
        data = self._request(
            "POST",
            "/telemetry",
            json=event.model_dump(exclude_none=True),
            auth=True,
        )
        return TelemetryAck.model_validate(data)

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        auth: bool = True,
        _retried: bool = False,
    ) -> Any:
        headers: dict[str, str] = {"Accept": "application/json"}
        if auth:
            headers["Authorization"] = f"Bearer {self._ensure_access_token()}"

        url = urljoin(self._base_url + "/", path.lstrip("/"))
        try:
            with httpx.Client(
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = client.request(method, url, json=json, headers=headers)
        except httpx.TimeoutException as exc:
            raise BackendUnavailableError(
                f"Backend timed out at {self._base_url}"
            ) from exc
        except httpx.RequestError as exc:
            raise BackendUnavailableError(
                f"Backend unavailable at {self._base_url}: {exc}"
            ) from exc

        if response.status_code == 401 and auth and not _retried:
            self.refresh_token()
            return self._request(method, path, json=json, auth=auth, _retried=True)

        if response.status_code == 401:
            raise BackendAuthError("Authentication failed. Run `refactory login`.")
        if response.status_code == 422:
            detail = self._detail(response)
            raise BackendResponseError(
                f"Invalid request: {detail}",
                status_code=422,
            )
        if response.status_code >= 400:
            detail = self._detail(response)
            if response.status_code in {401, 403}:
                raise BackendAuthError(detail)
            raise BackendResponseError(
                f"Backend error ({response.status_code}): {detail}",
                status_code=response.status_code,
            )

        if response.status_code == 204 or not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise BackendResponseError("Backend returned non-JSON response") from exc

    def _ensure_access_token(self) -> str:
        auth = self._token_store.load()
        if auth is None:
            raise BackendAuthError("Not logged in. Run `refactory login`.")
        # Prefer tokens issued for this client URL.
        if auth.backend_url.rstrip("/") != self._base_url:
            self._log(
                "warning",
                "Stored auth URL {} differs from configured {}; using stored tokens",
                auth.backend_url,
                self._base_url,
            )
        if self._token_store.is_access_expired(auth):
            tokens = self.refresh_token()
            return tokens.access_token
        return auth.access_token

    @staticmethod
    def _detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text or response.reason_phrase
        if isinstance(payload, dict):
            detail = payload.get("detail", payload)
            return str(detail)
        return str(payload)

    def _log(self, level: str, message: str, *args: object) -> None:
        if self._logger is None:
            return
        log = getattr(self._logger, level, None)
        if callable(log):
            log(message, *args)
