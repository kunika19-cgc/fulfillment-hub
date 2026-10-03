"""Every test gets its own empty database file, so tests never touch each other (or a real demo)."""
import pytest


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_DB", str(tmp_path / "test_hub.db"))
