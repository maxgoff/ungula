"""
Pytest configuration and fixtures for Ungula tests.
"""

import os
import tempfile
from pathlib import Path
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from ungula.config import Settings, UngulaConfig
from ungula.storage import SQLiteStorage


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def ungula_home(temp_dir: Path) -> Generator[Path, None, None]:
    """Set up a temporary Ungula home directory."""
    home = temp_dir / ".ungula"
    home.mkdir()

    # Create subdirectories
    (home / "workspace").mkdir()
    (home / "workspace" / "memory").mkdir()
    (home / "data").mkdir()
    (home / "logs").mkdir()
    (home / "skills").mkdir()
    (home / "nodes").mkdir()

    # Set environment variable
    old_home = os.environ.get("UNGULA_HOME")
    os.environ["UNGULA_HOME"] = str(home)

    yield home

    # Restore environment
    if old_home:
        os.environ["UNGULA_HOME"] = old_home
    else:
        del os.environ["UNGULA_HOME"]


@pytest.fixture
def config(ungula_home: Path) -> UngulaConfig:
    """Create a test configuration."""
    return UngulaConfig()


@pytest.fixture
def settings(ungula_home: Path) -> Settings:
    """Create test settings."""
    return Settings(home=ungula_home)


@pytest_asyncio.fixture
async def storage(temp_dir: Path) -> AsyncGenerator[SQLiteStorage, None]:
    """Create a test SQLite storage instance."""
    db_path = temp_dir / "test.db"
    storage = SQLiteStorage(db_path)
    await storage.initialize()
    yield storage
    await storage.close()


@pytest.fixture
def test_client(ungula_home: Path) -> Generator[TestClient, None, None]:
    """Create a test client for the FastAPI app."""
    from ungula.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture
def auth_headers(test_client: TestClient) -> dict[str, str]:
    """Register a test user and return auth headers with a valid JWT."""
    response = test_client.post(
        "/api/auth/register",
        json={"email": "test@example.com", "password": "testpassword123"},
    )
    assert response.status_code == 201, f"Register failed: {response.text}"
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
