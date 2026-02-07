"""
Tests for API endpoints.
"""

import pytest
from fastapi.testclient import TestClient


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    def test_health_check(self, test_client: TestClient):
        """Test health check returns healthy status."""
        response = test_client.get("/api/health")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data


class TestRootEndpoint:
    """Tests for root endpoint."""

    def test_root(self, test_client: TestClient):
        """Test root endpoint returns API info."""
        response = test_client.get("/")
        assert response.status_code == 200

        data = response.json()
        assert data["name"] == "Ungula"
        assert "version" in data
        assert "description" in data
        assert "docs_url" in data


class TestConfigEndpoints:
    """Tests for configuration endpoints."""

    def test_get_config(self, test_client: TestClient):
        """Test getting current configuration (secrets should be redacted)."""
        response = test_client.get("/api/config/")
        assert response.status_code == 200

        data = response.json()
        assert "config" in data
        assert "server" in data["config"]
        assert "database" in data["config"]

        # Verify secrets are redacted
        auth_cfg = data["config"].get("auth", {})
        if auth_cfg.get("secret_key"):
            assert auth_cfg["secret_key"] == "***REDACTED***"

    def test_list_workspace_files(self, test_client: TestClient):
        """Test listing workspace files."""
        response = test_client.get("/api/config/workspace")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, dict)
        assert "files" in data
        assert "bootstrap_needed" in data

        # Should have standard workspace files
        filenames = [f["filename"] for f in data["files"]]
        assert "SOUL.md" in filenames
        assert "USER.md" in filenames
        assert "AGENTS.md" in filenames

    def test_get_workspace_file(self, test_client: TestClient):
        """Test getting a workspace file."""
        response = test_client.get("/api/config/workspace/SOUL.md")
        assert response.status_code == 200

        data = response.json()
        assert data["filename"] == "SOUL.md"
        assert "exists" in data

    def test_get_workspace_file_invalid(self, test_client: TestClient):
        """Test getting an invalid workspace file returns 400."""
        response = test_client.get("/api/config/workspace/INVALID.md")
        assert response.status_code == 400

    def test_update_workspace_file(self, test_client: TestClient, auth_headers: dict):
        """Test updating a workspace file."""
        content = "# Test Soul\n\nThis is a test."

        response = test_client.put(
            "/api/config/workspace/SOUL.md", json={"content": content},
            headers=auth_headers,
        )
        assert response.status_code == 200

        data = response.json()
        assert data["filename"] == "SOUL.md"
        assert data["content"] == content
        assert data["exists"] is True

        # Verify content was saved
        get_response = test_client.get("/api/config/workspace/SOUL.md")
        assert get_response.json()["content"] == content

    def test_update_workspace_file_invalid(self, test_client: TestClient, auth_headers: dict):
        """Test updating an invalid workspace file returns 400."""
        response = test_client.put(
            "/api/config/workspace/INVALID.md", json={"content": "test"},
            headers=auth_headers,
        )
        assert response.status_code == 400

    def test_initialize_workspace(self, test_client: TestClient, auth_headers: dict):
        """Test initializing workspace creates template files."""
        response = test_client.post("/api/config/initialize-workspace", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert "message" in data
        assert "files_created" in data
        assert "files_skipped" in data

    def test_reload_config(self, test_client: TestClient, auth_headers: dict):
        """Test reloading configuration."""
        response = test_client.post("/api/config/reload", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert "config" in data
