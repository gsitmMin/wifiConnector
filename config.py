from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


@dataclass(frozen=True)
class AppConfig:
    ssid: str
    check_interval: int = 5
    retry_interval: int = 5
    max_retry: int = 10


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
