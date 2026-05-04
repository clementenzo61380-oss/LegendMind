"""Garde-fous config liés au déploiement (ex. Railway)."""

from __future__ import annotations

import pytest

from config import _reject_localhost_db_on_railway, load_config


def test_reject_localhost_when_railway(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="localhost"):
        _reject_localhost_db_on_railway("postgresql://u:p@localhost:5432/db")


def test_allow_localhost_without_railway(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    _reject_localhost_db_on_railway("postgresql://u:p@localhost:5432/db")


def test_load_config_fails_fast_localhost_on_railway(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("COC_EMAIL", "e")
    monkeypatch.setenv("COC_PASSWORD", "p")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:5432/db")
    with pytest.raises(RuntimeError, match="Railway"):
        load_config()
