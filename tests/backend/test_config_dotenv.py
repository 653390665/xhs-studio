"""Settings precedence: real env vars > local .env > YAML defaults."""

from __future__ import annotations

import backend.app.core.config as config_module
from backend.app.core.config import Settings, get_settings


def _use_env_file(monkeypatch, tmp_path, content: str):
    env_file = tmp_path / ".env"
    env_file.write_text(content, encoding="utf-8")
    monkeypatch.setattr(config_module, "_ENV_FILE", env_file)
    monkeypatch.setitem(Settings.model_config, "env_file", str(env_file))
    monkeypatch.setattr(
        config_module,
        "_load_yaml_config",
        lambda: {"xhs_data_provider": "pc", "redfox_api_key": ""},
    )
    monkeypatch.delenv("XHS_DATA_PROVIDER", raising=False)
    monkeypatch.delenv("REDFOX_API_KEY", raising=False)
    get_settings.cache_clear()


def test_dotenv_overrides_yaml_default(monkeypatch, tmp_path):
    _use_env_file(
        monkeypatch,
        tmp_path,
        "# local overrides\nXHS_DATA_PROVIDER=redfox\nREDFOX_API_KEY=ak_from_dotenv\n",
    )

    settings = get_settings()

    assert settings.xhs_data_provider == "redfox"
    assert settings.redfox_api_key == "ak_from_dotenv"


def test_real_env_var_beats_dotenv(monkeypatch, tmp_path):
    _use_env_file(monkeypatch, tmp_path, "XHS_DATA_PROVIDER=redfox\n")
    monkeypatch.setenv("XHS_DATA_PROVIDER", "pc")

    settings = get_settings()

    assert settings.xhs_data_provider == "pc"


def test_missing_dotenv_falls_back_to_yaml(monkeypatch, tmp_path):
    monkeypatch.setattr(config_module, "_ENV_FILE", tmp_path / ".env.absent")
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setattr(
        config_module,
        "_load_yaml_config",
        lambda: {"xhs_data_provider": "pc", "redfox_api_key": ""},
    )
    monkeypatch.delenv("XHS_DATA_PROVIDER", raising=False)
    get_settings.cache_clear()

    assert get_settings().xhs_data_provider == "pc"


def _legacy_db(tmp_path):
    legacy = tmp_path / "backend" / "app" / "storage" / "spider_xhs.db"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy")
    return legacy


def test_explicit_database_path_does_not_fall_back_to_legacy(monkeypatch, tmp_path):
    """The packaged launcher points at %LOCALAPPDATA%; a stale source DB in the
    current directory must not hijack that choice."""
    monkeypatch.chdir(tmp_path)
    _legacy_db(tmp_path)
    monkeypatch.setattr(config_module, "_ENV_FILE", tmp_path / ".env.absent")
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.delenv("DATABASE_SQLITE_PATH", raising=False)
    chosen = tmp_path / "fresh" / "spider_xhs.db"

    settings = Settings(database_sqlite_path=str(chosen))

    assert settings.database_url == f"sqlite:///{chosen}"


def test_historical_default_still_falls_back_to_legacy(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _legacy_db(tmp_path)
    monkeypatch.setattr(config_module, "_ENV_FILE", tmp_path / ".env.absent")
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.delenv("DATABASE_SQLITE_PATH", raising=False)

    settings = Settings(database_sqlite_path="./data/spider_xhs.db")

    assert settings.database_url == "sqlite:///./backend/app/storage/spider_xhs.db"
