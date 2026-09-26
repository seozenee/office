"""Test configuration: isolated SQLite DB + workspace, offline LLM, fixture search + research snapshot mirror."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="office_test_"))
sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from build_corpus import build  # noqa: E402

_corpus = build(_TMP / "corpus")
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_TMP / 'test.db'}",
    "WORKSPACE_DIR": str(_TMP / "workspace"),
    "LLM_PROVIDER": "offline",
    "INLINE_WORKER": "false",
    "SEARCH_PROVIDER": "fixture",
    "FIXTURE_SEARCH_FILE": _corpus["search"],
    "FETCH_MIRROR_DIR": _corpus["mirror"],
    "AUTH_ENABLED": "true",
    "ADMIN_USERNAME": "ceo",
    "ADMIN_PASSWORD": "test-password",
    "SECRET_KEY": "test-secret-key-123",
    "ANTHROPIC_API_KEY": "",
})


@pytest.fixture(scope="session")
def tmp_root() -> Path:
    return _TMP


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        token = c.post("/api/auth/login", json={"username": "ceo", "password": "test-password"}).json()["token"]
        c.headers["Authorization"] = f"Bearer {token}"
        yield c


@pytest.fixture()
def db(client):
    from app.core.db import SessionLocal

    s = SessionLocal()
    yield s
    s.close()
