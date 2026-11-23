"""Configuration control-plane endpoint tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_config_requires_auth(client: TestClient) -> None:
    assert client.get("/config").status_code == 401


def test_get_config_cli_shape(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/config", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) >= {
        "prompt_version",
        "workflow_version",
        "ai_provider",
        "model",
        "feature_flags",
        "limits",
    }
    assert body["prompt_version"]
    assert body["workflow_version"]
    assert body["ai_provider"] == "openai"
    assert body["model"] == "gpt-4o-mini"
    assert isinstance(body["feature_flags"], dict)
    assert isinstance(body["limits"], dict)
    assert "max_tokens" in body["limits"]
    # Config distribution only — no source payloads
    assert "source_code" not in body
    assert "files" not in body
    assert "organization" not in body


def test_get_config_bundle_full(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/config/bundle", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["organization"]["id"] == "org_default"
    assert body["repository"]["id"] == "repo_default"
    assert "never" in " ".join(body.get("notes", [])).lower()
    assert body["feature_flags"]["use_remote_prompts"] is True


def test_list_prompts_versioned(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/prompts", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    versions = {item["version"] for item in body["items"]}
    assert "1.0.0" in versions
    assert "2.0.0" in versions
    assert body["default_version"] == "2.0.0"


def test_list_workflows_versioned(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/workflows", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["default_name"] == "review"
    assert any(item["is_default"] for item in body["items"])


def test_prompt_version_query(client: TestClient, auth_headers: dict[str, str]) -> None:
    v1 = client.get("/prompts/review?version=1.0.0", headers=auth_headers)
    v2 = client.get("/prompts/review?version=2.0.0", headers=auth_headers)
    assert v1.status_code == 200
    assert v2.status_code == 200
    assert v1.json()["version"] == "1.0.0"
    assert v2.json()["version"] == "2.0.0"
    assert v1.json()["template"] != v2.json()["template"]


def test_organization_and_repository(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    org = client.get("/organizations/org_default", headers=auth_headers)
    assert org.status_code == 200
    assert org.json()["slug"] == "default"
    assert org.json()["settings"]["coding_standards"]["require_type_hints"] is True

    repo = client.get("/repositories/repo_default", headers=auth_headers)
    assert repo.status_code == 200
    assert repo.json()["organization_id"] == "org_default"
    assert "files" not in repo.json()
    assert "source_code" not in repo.json()
    assert "blob" not in repo.json()


def test_organization_not_found(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/organizations/missing", headers=auth_headers)
    assert response.status_code == 404


def test_openapi_includes_config_paths(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    assert "/config" in paths
    assert "/config/bundle" in paths
    assert "/prompts" in paths
    assert "/workflows" in paths
    assert "/organizations/{organization_id}" in paths
    assert "/repositories/{repository_id}" in paths
    config_desc = paths["/config"]["get"].get("description", "")
    assert "source code" in config_desc.lower()
