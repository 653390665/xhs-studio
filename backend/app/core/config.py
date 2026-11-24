from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:  # pragma: no cover - handled by dependency installation
    BaseSettings = object
    SettingsConfigDict = dict


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
# Local dotenv file, resolved from the project root so it works regardless of cwd.
_ENV_FILE = PROJECT_ROOT / ".env"


def _load_yaml_config() -> Dict[str, Any]:
    """Load YAML configuration files and flatten into env-var-style keys.

    Loading order (later values override earlier ones):
      1. config/default.yaml (always loaded if it exists)
      2. File specified by CONFIG_FILE environment variable
    """
    try:
        import yaml
    except ImportError:
        return {}

    project_root = PROJECT_ROOT
    flat: Dict[str, Any] = {}

    # Mapping from nested YAML paths to Settings field names
    yaml_key_map = {
        "server.host": "server_host",
        "server.port": "server_port",
        "server.cors_origins": "backend_cors_origins",
        "database.type": "database_type",
        "database.sqlite_path": "database_sqlite_path",
        "database.mysql_host": "database_mysql_host",
        "database.mysql_port": "database_mysql_port",
        "database.mysql_user": "database_mysql_user",
        "database.mysql_password": "database_mysql_password",
        "database.mysql_database": "database_mysql_database",
        "security.secret_key": "secret_key",
        "security.fernet_key": "fernet_key",
        "scheduler.enabled": "scheduler_enabled",
        "scheduler.interval_seconds": "scheduler_interval_seconds",
        "frontend.serve_static": "frontend_serve_static",
        "frontend.build_dir": "frontend_build_dir",
        "xhs_provider.data_provider": "xhs_data_provider",
        "xhs_provider.redfox_api_key": "redfox_api_key",
        "xhs_provider.redfox_api_base_url": "redfox_api_base_url",
        "xhs_provider.redfox_timeout_seconds": "redfox_timeout_seconds",
        "xhs_provider.redfox_daily_call_limit": "redfox_daily_call_limit",
        "xhs_provider.redfox_profile_cache_ttl_seconds": "redfox_profile_cache_ttl_seconds",
        "xhs_provider.redfox_page_size": "redfox_page_size",
        "xhs_provider.redfox_search_exact_match": "redfox_search_exact_match",
        "xhs_provider.redfox_comments_enabled": "redfox_comments_enabled",
        "xhs_provider.redfox_comment_batch_size": "redfox_comment_batch_size",
        "xhs_provider.paths.search_notes": "redfox_path_search_notes",
        "xhs_provider.paths.user_info": "redfox_path_user_info",
        "xhs_provider.paths.note_detail": "redfox_path_note_detail",
        "xhs_provider.paths.user_notes": "redfox_path_user_notes",
        "xhs_provider.paths.comment_submit": "redfox_path_comment_submit",
        "xhs_provider.paths.comment_result": "redfox_path_comment_result",
        "xhs_provider.paths.viral_insights": "redfox_path_viral_insights",
        "xhs_provider.paths.low_fan_ranking": "redfox_path_low_fan_ranking",
        "xhs_provider.paths.rank_daily": "redfox_path_rank_daily",
        "xhs_provider.paths.rank_weekly": "redfox_path_rank_weekly",
        "xhs_provider.paths.search_users": "redfox_path_search_users",
        "xhs_provider.paths.balance": "redfox_path_balance",
        "xhs_provider.paths.consume_flows": "redfox_path_consume_flows",
        "xhs_provider.paths.sensitive_words": "redfox_path_sensitive_words",
        "xhs_provider.paths.hot_accounts": "redfox_path_hot_accounts",
        "xhs_provider.paths.hot_list": "redfox_path_hot_list",
        "hot_search.enabled": "free_hot_search_enabled",
        "hot_search.base_url": "free_hot_search_base_url",
        "hot_search.path": "free_hot_search_path",
        "hot_search.timeout_seconds": "free_hot_search_timeout_seconds",
    }

    def _flatten(data: Any, prefix: str = "") -> None:
        if isinstance(data, dict):
            for key, value in data.items():
                full_key = f"{prefix}.{key}" if prefix else key
                if full_key in yaml_key_map:
                    flat[yaml_key_map[full_key]] = value
                _flatten(value, full_key)

    # 1. Load config/default.yaml
    default_yaml = project_root / "config" / "default.yaml"
    if default_yaml.exists():
        with open(default_yaml, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if data:
                _flatten(data)

    # 2. Load CONFIG_FILE override
    config_file = os.environ.get("CONFIG_FILE")
    if config_file:
        config_path = Path(config_file)
        if not config_path.is_absolute():
            config_path = project_root / config_path
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data:
                    _flatten(data)

    return flat


class Settings(BaseSettings):
    app_name: str = "XHS Studio"
    api_title: str = "XHS Studio API"
    environment: str = "development"

    # Database
    database_url: str = ""
    database_type: str = "sqlite"
    database_sqlite_path: str = "./data/spider_xhs.db"
    database_mysql_host: str = "localhost"
    database_mysql_port: int = 3306
    database_mysql_user: str = "spider_xhs"
    database_mysql_password: str = "change_me"
    database_mysql_database: str = "spider_xhs"

    # Security: must be provided via SECRET_KEY / FERNET_KEY.
    secret_key: str = ""
    fernet_key: str = ""

    # Server: loopback by default; containers must opt in explicitly.
    server_host: str = "127.0.0.1"
    server_port: int = 8000

    # CORS
    backend_cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    # Scheduler
    scheduler_enabled: bool = False
    scheduler_interval_seconds: int = 60

    # Asset storage
    asset_storage_type: str = "local"

    # Frontend static serving
    frontend_serve_static: bool = False
    frontend_build_dir: str = "./frontend/dist"

    # XHS data provider
    # "pc"     -> Spider_XHS PC SDK using the account's login cookies (default, free)
    # "redfox" -> RedFox Hub read-only data provider (paid, no login required)
    xhs_data_provider: str = "pc"
    redfox_api_key: str = ""
    redfox_api_base_url: str = "https://redfox.hk"
    redfox_timeout_seconds: float = 30.0
    # Hard safety cap; 0 disables the cap. Counts RedFox API calls per calendar day.
    redfox_daily_call_limit: int = 500
    # Author profile cache TTL to avoid paying twice for the same author.
    redfox_profile_cache_ttl_seconds: int = 86400
    redfox_page_size: int = 20
    redfox_search_exact_match: bool = False
    # Comment retrieval on RedFox is an async task (results visible later), so it
    # is opt-in and off by default. The PC provider handles live comment previews.
    redfox_comments_enabled: bool = False
    redfox_comment_batch_size: int = 20
    # Endpoint paths, overridable in case RedFox changes them.
    redfox_path_search_notes: str = "/story/api/xhsUser/searchArticle"
    redfox_path_user_info: str = "/story/api/xhsUser/queryAccountDetail"
    redfox_path_note_detail: str = "/story/api/xhsUser/queryWorkDetail"
    redfox_path_user_notes: str = "/story/api/xhsUser/queryWorkList"
    redfox_path_comment_submit: str = "/story/api/xhs/commentSubmit"
    redfox_path_comment_result: str = "/story/api/xhs/commentResult"
    # Read-only ranking / insight endpoints (used by the trends API).
    redfox_path_viral_insights: str = "/story/api/xhs/search/search"
    redfox_path_low_fan_ranking: str = "/story/api/cozeSkill/getLowPowderExplosiveArticle"
    redfox_path_rank_daily: str = "/story/api/cozeSkill/getXhsCozeSkillDataOne"
    redfox_path_rank_weekly: str = "/story/api/cozeSkill/getXhsCozeSkillDataSeven"
    redfox_path_search_users: str = "/story/api/xhsUser/searchUser"
    # Account / tooling endpoints (free or per-call).
    redfox_path_balance: str = "/story/web/points/api-key/balance"
    redfox_path_consume_flows: str = "/story/web/points/api-key/consume-flows"
    redfox_path_sensitive_words: str = "/story/api/cozeSkill/sensitiveWordSearch"
    redfox_path_hot_accounts: str = "/story/api/xhsData/query"
    redfox_path_hot_list: str = "/story/api/hotSpot/getListByPlatform"
    # Free hot-search fallback (60s API) used when RedFox is unavailable.
    free_hot_search_enabled: bool = True
    free_hot_search_base_url: str = "https://60s.viki.moe"
    free_hot_search_path: str = "/v2/rednote"
    free_hot_search_timeout_seconds: int = 10

    if hasattr(BaseSettings, "model_config"):
        model_config = SettingsConfigDict(env_file=str(_ENV_FILE), env_file_encoding="utf-8", extra="ignore")

    def model_post_init(self, __context: Any) -> None:
        # Build database_url from component fields if not explicitly set
        if not self.database_url:
            if self.database_type == "mysql":
                object.__setattr__(
                    self,
                    "database_url",
                    f"mysql+pymysql://{self.database_mysql_user}:{self.database_mysql_password}"
                    f"@{self.database_mysql_host}:{self.database_mysql_port}/{self.database_mysql_database}"
                    "?charset=utf8mb4",
                )
            else:
                # Backward compatibility for the historical default only. If the
                # caller explicitly points at another database (packaged launcher,
                # tests, deployments), never silently switch to a legacy file that
                # happens to exist in the current working directory.
                sqlite_path = self.database_sqlite_path
                legacy_default = "./backend/app/storage/spider_xhs.db"
                if sqlite_path == "./data/spider_xhs.db":
                    old_db = Path(legacy_default)
                    if not Path(sqlite_path).exists() and old_db.exists():
                        sqlite_path = legacy_default
                object.__setattr__(
                    self,
                    "database_url",
                    f"sqlite:///{sqlite_path}",
                )

    @property
    def storage_dir(self) -> Path:
        # The packaged launcher points this at a writable per-user directory.
        return Path(os.getenv("XHS_STORAGE_DIR") or "backend/app/storage")


def _dotenv_keys() -> set[str]:
    """Keys declared in a local ``.env`` file (upper-cased).

    pydantic-settings reads ``.env`` for us, but ``Settings(**yaml_values)`` init
    kwargs outrank env files, so the YAML defaults would silently win. Collecting
    the names lets us drop those YAML keys and honour the documented override.
    """
    keys: set[str] = set()
    path = Path(_ENV_FILE)
    if not path.is_file():
        return keys
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key = line.split("=", 1)[0].strip()
            if key.startswith("export "):
                key = key[len("export ") :].strip()
            if key:
                keys.add(key.upper())
    except OSError:
        return keys
    return keys


def user_settings_file() -> Path:
    """Where the settings UI writes its own settings (RedFox key, scheduler).

    Same resolution rule as ``api/system.py``: env var wins, otherwise the
    packaged default ``./data/user_settings.json``. Kept in one place so the
    reader here and the writer there can never disagree about the file.
    """
    configured = os.getenv("XHS_USER_SETTINGS_FILE")
    return Path(configured) if configured else Path("./data/user_settings.json")


def _user_settings_path() -> Path:
    # Kept for callers that grew used to the private name.
    return user_settings_file()


def _user_settings_values() -> Dict[str, Any]:
    """Values saved from the settings UI, flattened to Settings field names.

    Only keys this module knows how to map are read. Everything else in that
    file (``redfox_api_key`` is one) is handled by ``api/system.py`` through
    environment variables, and must not leak into ``Settings(**kwargs)``.
    """
    path = _user_settings_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    mapping = {
        "scheduler_enabled": "scheduler_enabled",
        "scheduler_interval_seconds": "scheduler_interval_seconds",
    }
    out: Dict[str, Any] = {}
    for key, field in mapping.items():
        if key in data and data[key] is not None:
            out[field] = data[key]
    return out


@lru_cache
def get_settings() -> Settings:
    yaml_values = _load_yaml_config()
    # Environment variables (and the local .env file) must win over YAML
    # defaults: pydantic-settings gives init kwargs priority over both env vars
    # and env files, so drop any YAML key the operator is overriding
    # (e.g. REDFOX_API_KEY, XHS_DATA_PROVIDER).
    overrides = set(os.environ) | _dotenv_keys()
    for key in list(yaml_values):
        if key.upper() in overrides:
            yaml_values.pop(key)

    # The settings UI writes ``user_settings.json``. Until now nothing read it
    # except the RedFox key path (which pokes ``os.environ`` and clears this
    # cache). That meant 「在界面打开调度器」 was impossible: the file said one
    # thing, ``get_settings()`` said another, and a restart silently reverted.
    #
    # Precedence: env > user_settings > YAML. A field named in the environment
    # is left alone here too, otherwise the UI would quietly outrank an
    # operator's explicit deployment config.
    for key, value in _user_settings_values().items():
        if key.upper() in overrides:
            continue
        yaml_values[key] = value
    return Settings(**yaml_values)
