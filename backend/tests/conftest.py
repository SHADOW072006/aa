"""
Shared pytest configuration for TeleMonitor backend tests.
Isolates test execution from the live database, Telegram collector,
background polling, and discovery tasks.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Set test-safe environment defaults before app/database modules initialise
_TEST_TMP_DIR = Path(tempfile.mkdtemp(prefix="telemonitor_pytest_"))
os.environ.setdefault("TESTING", "1")
os.environ.setdefault("DISABLE_BACKGROUND_TASKS", "1")
os.environ.setdefault("DISCOVERY_ENABLED", "false")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{(_TEST_TMP_DIR / 'test_suite.db').as_posix()}")

import asyncio
import pytest

from app.core.config import settings
from app.db.database import init_db

# Tests must be hermetic against the developer's local backend/.env: token
# protection is enabled per-test via monkeypatch where it is under test.
settings.API_ACCESS_TOKEN = None


@pytest.fixture(autouse=True, scope="session")
def _isolate_test_settings():
    settings.TESTING = True
    settings.DISABLE_BACKGROUND_TASKS = True
    settings.DISCOVERY_ENABLED = False
    asyncio.run(init_db())
    yield

