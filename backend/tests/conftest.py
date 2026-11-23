"""Shared pytest fixtures.

The test-suite runs against an isolated SQLite database and storage folder so it
never touches the development data in ``storage/sentinel.db``.  Import order
matters: environment variables are configured before any ``backend`` module is
imported, because :class:`backend.config.Settings` is created at import time.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Dict

import pytest # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_DB = PROJECT_ROOT / "storage" / "sentinel_test.db"
TEST_STORAGE = PROJECT_ROOT / "storage" / "_test_storage"

if TEST_DB.exists():
    TEST_DB.unlink()
if TEST_STORAGE.exists():
    shutil.rmtree(TEST_STORAGE, ignore_errors=True)

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["STORAGE_DIR"] = str(TEST_STORAGE)
os.environ["PIPELINE_ENABLED"] = "false"
# The API tests assert the historical demo dataset (4 cameras, sample
# incidents and people).  Live-only mode intentionally seeds none of that, so
# force the demo seed for the test database while leaving development/runtime
# defaults untouched.
os.environ["LIVE_ONLY"] = "false"
os.environ["DEMO_MODE"] = "true"
os.environ["SEED_DEMO_DATA"] = "true"
os.environ["RESET_DATABASE"] = "true"
os.environ["SECRET_KEY"] = "sentinel-test-secret-key"
os.environ["PASSWORD_ITERATIONS"] = "1200"
os.environ["FRONTEND_DIST"] = str(PROJECT_ROOT / "frontend" / "dist")


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient # type: ignore

    from backend.main import app

    with TestClient(app) as test_client:
        yield test_client

    from backend.database import engine

    engine.dispose()
    if TEST_DB.exists():
        TEST_DB.unlink()
    shutil.rmtree(TEST_STORAGE, ignore_errors=True)


def login(client, username: str, password: str) -> str:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def admin_token(client) -> str:
    return login(client, "admin", "admin123")


@pytest.fixture(scope="session")
def operator_token(client) -> str:
    return login(client, "operator", "operator123")


@pytest.fixture(scope="session")
def viewer_token(client) -> str:
    return login(client, "viewer", "viewer123")


@pytest.fixture(scope="session")
def admin_headers(admin_token) -> Dict[str, str]:
    return auth(admin_token)
