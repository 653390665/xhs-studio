"""Source-runtime entrypoint security regressions."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

import launcher
import main as entry
from backend.app.main import _validate_secret_key, _validated_cors_origins


def test_cors_wildcard_is_rejected():
    assert _validated_cors_origins("http://127.0.0.1:5173, http://localhost:5173") == [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]
    with pytest.raises(RuntimeError):
        _validated_cors_origins("*")


def test_insecure_secret_key_is_rejected():
    with pytest.raises(RuntimeError):
        _validate_secret_key(SimpleNamespace(secret_key="dev-only-change-me"))
    with pytest.raises(RuntimeError):
        _validate_secret_key(SimpleNamespace(secret_key=""))
    _validate_secret_key(SimpleNamespace(secret_key="x" * 48))


def test_node_available_uses_path_lookup(monkeypatch):
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "C:/node/node.exe" if name == "node" else None)
    assert launcher.node_available() is True

    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)
    assert launcher.node_available() is False


def test_prepare_runtime_reuses_launcher_secret(monkeypatch, tmp_path):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("XHS_USER_SETTINGS_FILE", raising=False)
    # Isolate from the developer's real .env, which may contain SECRET_KEY.
    monkeypatch.setattr(entry, "ROOT", tmp_path)

    seen = {}

    def fake_ensure_dirs(path):
        seen["dir"] = path

    monkeypatch.setattr("launcher.data_dir", lambda: tmp_path)
    monkeypatch.setattr("launcher.ensure_dirs", fake_ensure_dirs)
    monkeypatch.setattr("launcher.load_or_create_secret", lambda path: "persisted-test-secret")
    monkeypatch.setattr("launcher.load_user_settings", lambda path: {})
    monkeypatch.setattr("launcher.apply_user_settings", lambda settings: None)

    entry.prepare_runtime()

    assert os.environ["SECRET_KEY"] == "persisted-test-secret"
    assert os.environ["XHS_USER_SETTINGS_FILE"] == str(tmp_path / "settings.json")
    assert seen["dir"] == tmp_path


def test_resolve_host_defaults_to_loopback():
    assert entry.resolve_host(None) == "127.0.0.1"
    assert entry.resolve_host("0.0.0.0") == "0.0.0.0"


def test_main_keeps_loopback_even_when_yaml_says_lan(monkeypatch):
    from backend.app.core import config as config_module

    calls = {}

    monkeypatch.setattr(entry, "prepare_runtime", lambda: None)
    monkeypatch.setattr(
        config_module,
        "get_settings",
        lambda: SimpleNamespace(server_port=8000, server_host="0.0.0.0"),
    )

    def fake_run(app, *, host, port, reload):
        calls.update(app=app, host=host, port=port, reload=reload)

    monkeypatch.setattr("uvicorn.run", fake_run)

    assert entry.main([]) == 0
    assert calls["app"] == "backend.app.main:app"
    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 8000
