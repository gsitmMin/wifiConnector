from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


@dataclass(frozen=True)
class TgateConfig:
    enabled: bool = False
    window_title: str = "Tgate Smart Agent"
    username: str = ""
    password: str = ""
    username_env: str = "TGATE_USERNAME"
    password_env: str = "TGATE_PASSWORD"
    submit: bool = True


@dataclass(frozen=True)
class AppConfig:
    ssid: str
    check_interval: int = 5
    retry_interval: int = 5
    max_retry: int = 10
    tgate: TgateConfig = field(default_factory=TgateConfig)


def load_config(path: Path = CONFIG_PATH) -> AppConfig:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        raw_config = json.load(file)

    return AppConfig(
        ssid=_get_required_str(raw_config, "ssid"),
        check_interval=_get_positive_int(raw_config, "check_interval", 5),
        retry_interval=_get_positive_int(raw_config, "retry_interval", 5),
        max_retry=_get_positive_int(raw_config, "max_retry", 10),
        tgate=_load_tgate_config(raw_config.get("tgate", {})),
    )


def _get_required_str(config: dict[str, Any], key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{key}' must be a non-empty string")
    return value.strip()


def _get_positive_int(config: dict[str, Any], key: str, default: int) -> int:
    value = config.get(key, default)
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"'{key}' must be a positive integer")
    return value


def _load_tgate_config(raw_value: Any) -> TgateConfig:
    if raw_value in (None, {}):
        return TgateConfig()
    if not isinstance(raw_value, dict):
        raise ValueError("'tgate' must be an object")

    enabled = _get_bool(raw_value, "enabled", False)
    window_title = _get_str(raw_value, "window_title", "Tgate Smart Agent")
    username_env = _get_str(raw_value, "username_env", "TGATE_USERNAME")
    password_env = _get_str(raw_value, "password_env", "TGATE_PASSWORD")
    username = _get_optional_secret(raw_value, "username", username_env)
    password = _get_optional_secret(raw_value, "password", password_env)
    submit = _get_bool(raw_value, "submit", True)

    if enabled:
        if not window_title:
            raise ValueError("'tgate.window_title' must be a non-empty string")
        if not username:
            raise ValueError("'tgate.username' or its environment variable must be set when Tgate is enabled")
        if not password:
            raise ValueError("'tgate.password' or its environment variable must be set when Tgate is enabled")

    return TgateConfig(
        enabled=enabled,
        window_title=window_title,
        username=username,
        password=password,
        username_env=username_env,
        password_env=password_env,
        submit=submit,
    )


def _get_bool(config: dict[str, Any], key: str, default: bool) -> bool:
    value = config.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"'{key}' must be a boolean")
    return value


def _get_str(config: dict[str, Any], key: str, default: str) -> str:
    value = config.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"'{key}' must be a string")
    return value.strip()


def _get_optional_secret(config: dict[str, Any], key: str, env_key: str) -> str:
    value = config.get(key)
    if value is not None:
        if not isinstance(value, str):
            raise ValueError(f"'{key}' must be a string")
        return value.strip()

    env_value = os.environ.get(env_key)
    if env_value is not None:
        return env_value.strip()

    if env_key and not _looks_like_env_name(env_key):
        return env_key.strip()

    return ""


def _looks_like_env_name(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value))
