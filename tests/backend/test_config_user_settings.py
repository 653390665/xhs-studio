"""P0-2：`get_settings()` 必须读界面写的 `user_settings.json`。

在此之前只有 RedFox key 走通了「写文件 → `os.environ[...]` → `cache_clear()`」，
调度器开关没有任何人能改：`config/default.yaml` 里 `scheduler.enabled: false`
是硬的，`get_settings()` 也从不读 `user_settings.json`。所以「在界面打开调度器」
不是加个按钮的事——配置加载链本身缺了一环。

本文件守三件事：
1. 文件里的值能被读到；
2. 环境变量仍然优先（部署时显式配置不能被界面悄悄改掉）；
3. 文件里有别的键（RedFox key 之类）不会被塞进 `Settings(**kwargs)`。
"""

from __future__ import annotations

import json

import backend.app.core.config as config_module
from backend.app.core.config import Settings, get_settings


def _isolate(monkeypatch, tmp_path, *, yaml=None, user_settings=None, env=None):
    """把三项来源都换成临时文件，避免读到真实配置。"""
    monkeypatch.setattr(config_module, "_load_yaml_config", lambda: dict(yaml or {}))
    monkeypatch.setattr(config_module, "_dotenv_keys", lambda: set())

    path = tmp_path / "user_settings.json"
    if user_settings is not None:
        path.write_text(
            json.dumps(user_settings, ensure_ascii=False), encoding="utf-8"
        )
    monkeypatch.setenv("XHS_USER_SETTINGS_FILE", str(path))

    for name in ("SCHEDULER_ENABLED", "SCHEDULER_INTERVAL_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    for name, value in (env or {}).items():
        monkeypatch.setenv(name, value)

    get_settings.cache_clear()
    return path


def test_user_settings_can_enable_the_scheduler(monkeypatch, tmp_path):
    _isolate(
        monkeypatch,
        tmp_path,
        yaml={"scheduler_enabled": False, "scheduler_interval_seconds": 60},
        user_settings={"scheduler_enabled": True, "scheduler_interval_seconds": 30},
    )

    settings = get_settings()

    assert settings.scheduler_enabled is True, (
        "界面写了 user_settings.json，但 get_settings() 没读它——"
        "调度器开关在界面上永远打不开"
    )
    assert settings.scheduler_interval_seconds == 30


def test_environment_still_beats_user_settings(monkeypatch, tmp_path):
    """部署时显式设了 SCHEDULER_ENABLED=false，界面不能把它翻过来。"""
    _isolate(
        monkeypatch,
        tmp_path,
        yaml={"scheduler_enabled": False},
        user_settings={"scheduler_enabled": True},
        env={"SCHEDULER_ENABLED": "false"},
    )

    assert get_settings().scheduler_enabled is False


def test_user_settings_beats_yaml(monkeypatch, tmp_path):
    _isolate(
        monkeypatch,
        tmp_path,
        yaml={"scheduler_enabled": False},
        user_settings={"scheduler_enabled": True},
    )

    assert get_settings().scheduler_enabled is True


def test_missing_file_falls_back_to_yaml(monkeypatch, tmp_path):
    _isolate(
        monkeypatch,
        tmp_path,
        yaml={"scheduler_enabled": False},
        user_settings=None,
    )

    assert get_settings().scheduler_enabled is False


def test_broken_file_is_ignored_not_fatal(monkeypatch, tmp_path):
    """半个 JSON 不能让整个应用起不来。"""
    monkeypatch.setattr(
        config_module, "_load_yaml_config", lambda: {"scheduler_enabled": False}
    )
    monkeypatch.setattr(config_module, "_dotenv_keys", lambda: set())
    bad = tmp_path / "user_settings.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    monkeypatch.setenv("XHS_USER_SETTINGS_FILE", str(bad))
    monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)
    get_settings.cache_clear()

    assert get_settings().scheduler_enabled is False


def test_unknown_keys_in_user_settings_do_not_reach_settings(monkeypatch, tmp_path):
    """`redfox_api_key` 是 system.py 用环境变量走的，不该从这条路径塞进来。"""
    _isolate(
        monkeypatch,
        tmp_path,
        yaml={"redfox_api_key": ""},
        user_settings={
            "scheduler_enabled": True,
            "redfox_api_key": "ak_should_not_be_read_here",
            "some_future_ui_key": "x",
        },
    )

    settings = get_settings()

    assert settings.scheduler_enabled is True
    assert settings.redfox_api_key == "", (
        "user_settings 里的非调度器键被塞进了 Settings(**kwargs)"
    )
