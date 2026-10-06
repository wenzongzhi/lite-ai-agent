"""Immutable startup settings with environment > TOML > default precedence."""

import base64
import math
import os
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


class ConfigError(ValueError):
    """A configuration error that never includes secret values."""


@dataclass(frozen=True)
class WeChatSettings:
    token: str = field(default="", repr=False)
    encoding_aes_key: str = field(default="", repr=False)
    app_id: str = ""
    app_secret: str = field(default="", repr=False)


@dataclass(frozen=True)
class DoubaoSettings:
    api_key: str = field(default="", repr=False)
    model: str = ""
    base_url: str = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
    http_timeout_seconds: float = 120.0


@dataclass(frozen=True)
class ServerSettings:
    host: str = "127.0.0.1"
    port: int = 8000
    fast_reply_timeout_seconds: float = 3.5


@dataclass(frozen=True)
class FeatureSettings:
    ai_answer_enabled: bool = True
    ai_agent_enabled: bool = True
    allow_user_agent_self_enable: bool = True
    agent_enable_phrase: str = "开启豆包agent功能"
    agent_disable_phrase: str = "关闭豆包agent功能"


@dataclass(frozen=True)
class AgentSettings:
    max_steps: int = 6
    tool_timeout_seconds: float = 15.0
    recent_message_limit: int = 12
    memory_summary_enabled: bool = True
    memory_search_enabled: bool = True
    max_tool_result_bytes: int = 8000


@dataclass(frozen=True)
class DatabaseSettings:
    path: str = "./data/agent.db"


@dataclass(frozen=True)
class WebSearchSettings:
    enabled: bool = False
    provider: str = "brave"
    api_key: str = field(default="", repr=False)
    max_results: int = 5


@dataclass(frozen=True)
class CalendarSettings:
    enabled: bool = False
    provider: str = "google"
    credentials_file: str = ""
    timezone: str = "Asia/Shanghai"


@dataclass(frozen=True)
class Settings:
    wechat: WeChatSettings = field(default_factory=WeChatSettings)
    doubao: DoubaoSettings = field(default_factory=DoubaoSettings)
    server: ServerSettings = field(default_factory=ServerSettings)
    features: FeatureSettings = field(default_factory=FeatureSettings)
    agent: AgentSettings = field(default_factory=AgentSettings)
    database: DatabaseSettings = field(default_factory=DatabaseSettings)
    web_search: WebSearchSettings = field(default_factory=WebSearchSettings)
    calendar: CalendarSettings = field(default_factory=CalendarSettings)


ENV_FIELDS = {
    "wechat.token": "WECHAT_TOKEN",
    "wechat.encoding_aes_key": "WECHAT_ENCODING_AES_KEY",
    "wechat.app_id": "WECHAT_APP_ID",
    "wechat.app_secret": "WECHAT_APP_SECRET",
    "doubao.api_key": "DOUBAO_API_KEY",
    "doubao.model": "DOUBAO_MODEL",
    "doubao.base_url": "DOUBAO_BASE_URL",
    "doubao.http_timeout_seconds": "DOUBAO_HTTP_TIMEOUT_SECONDS",
    "server.host": "SERVER_HOST",
    "server.port": "SERVER_PORT",
    "server.fast_reply_timeout_seconds": "FAST_REPLY_TIMEOUT_SECONDS",
    "database.path": "AGENT_DB_PATH",
    "web_search.api_key": "BRAVE_SEARCH_API_KEY",
}
for _section, _cls in (("features", FeatureSettings), ("agent", AgentSettings),
                       ("web_search", WebSearchSettings), ("calendar", CalendarSettings)):
    for _field in fields(_cls):
        ENV_FIELDS.setdefault(f"{_section}.{_field.name}", f"{_section}_{_field.name}".upper())


def normalize_encoding_aes_key(key: str) -> str:
    """Normalize and validate the 32-byte WeChat AES key in one place."""
    key = key.strip()
    key += "=" * ((-len(key)) % 4)
    try:
        decoded = base64.b64decode(key, validate=True)
    except (ValueError, base64.binascii.Error):
        raise ConfigError("Invalid wechat.encoding_aes_key") from None
    if len(decoded) != 32:
        raise ConfigError("Invalid wechat.encoding_aes_key")
    return key


def _convert(value, expected, name: str, from_env: bool):
    try:
        if expected is bool:
            if from_env and value.lower() in ("true", "1", "yes", "false", "0", "no"):
                return value.lower() in ("true", "1", "yes")
            if type(value) is bool:
                return value
        elif expected is int:
            if from_env:
                return int(value)
            if type(value) is int:
                return value
        elif expected is float:
            if from_env or type(value) in (int, float):
                number = float(value)
                if math.isfinite(number):
                    return number
        elif expected is str and isinstance(value, str):
            return value.strip()
    except (ValueError, OverflowError):
        pass
    raise ConfigError(f"Invalid type or value for {name}")


def load_settings(path=None, environ: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if environ is None else environ
    config_path = Path(path or env.get("WECHAT_AGENT_CONFIG", "config.toml"))
    raw = {}
    try:
        if config_path.exists():
            with config_path.open("rb") as stream:
                raw = tomllib.load(stream)
        elif path is not None or "WECHAT_AGENT_CONFIG" in env:
            raise ConfigError("Configuration file not found")
    except (OSError, tomllib.TOMLDecodeError):
        raise ConfigError("Unable to read TOML configuration") from None
    sections = {}
    for section_field in fields(Settings):
        name = section_field.name
        cls = section_field.default_factory
        defaults = cls()
        section = raw.get(name, {})
        if not isinstance(section, dict):
            raise ConfigError(f"Invalid configuration section: {name}")
        if set(section) - {item.name for item in fields(cls)}:
            raise ConfigError(f"Unknown configuration field in {name}")
        values = {}
        for item in fields(cls):
            key = f"{name}.{item.name}"
            env_name = ENV_FIELDS[key]
            value = env.get(env_name, section.get(item.name, getattr(defaults, item.name)))
            values[item.name] = _convert(value, type(getattr(defaults, item.name)), key, env_name in env)
        sections[name] = cls(**values)
    settings = Settings(**sections)
    for key in ("wechat.token", "wechat.encoding_aes_key", "wechat.app_id", "doubao.api_key", "doubao.model"):
        section, name = key.split(".")
        if not getattr(getattr(settings, section), name):
            raise ConfigError(f"Missing required field: {key}")
    settings = replace(settings, wechat=replace(settings.wechat, encoding_aes_key=normalize_encoding_aes_key(settings.wechat.encoding_aes_key)))
    ranges = {
        "server.port": (1, 65535), "server.fast_reply_timeout_seconds": (0, 120),
        "doubao.http_timeout_seconds": (0, 3600), "agent.max_steps": (1, 32),
        "agent.tool_timeout_seconds": (0, 300), "agent.recent_message_limit": (0, 100),
        "agent.max_tool_result_bytes": (256, 65536), "web_search.max_results": (1, 20),
    }
    for key, (lower, upper) in ranges.items():
        section, name = key.split(".")
        value = getattr(getattr(settings, section), name)
        if value > upper or value < lower or (key.endswith("seconds") and value <= 0):
            raise ConfigError(f"Out of range: {key}")
    if not settings.database.path or not settings.server.host:
        raise ConfigError("database.path and server.host must be non-empty")
    phrases = (settings.features.agent_enable_phrase, settings.features.agent_disable_phrase)
    if not all(phrases) or phrases[0] == phrases[1] or "结果" in phrases:
        raise ConfigError("Agent phrases must be distinct, non-empty, and different from the result command")
    try:
        url = urlsplit(settings.doubao.base_url)
    except ValueError:
        raise ConfigError("Invalid doubao.base_url") from None
    if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ConfigError("Invalid doubao.base_url")
    if settings.web_search.provider not in ("brave", "disabled"):
        raise ConfigError("Unsupported web_search.provider")
    if settings.web_search.enabled and settings.web_search.provider == "brave" and not settings.web_search.api_key:
        raise ConfigError("Missing required field: web_search.api_key")
    if settings.calendar.provider not in ("google", "disabled"):
        raise ConfigError("Unsupported calendar.provider")
    return settings
