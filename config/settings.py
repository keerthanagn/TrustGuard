"""Configuration loading: YAML defaults -> environment variables -> runtime overrides."""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is in requirements
    load_dotenv = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "default.yaml"


def _coerce(value: str, like: Any) -> Any:
    """Convert an environment string to the type of the default value."""
    if isinstance(like, bool):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(like, int):
        return int(value)
    if isinstance(like, float):
        return float(value)
    return value


def _deep_update(base: dict, overrides: dict) -> dict:
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
    return base


@dataclass
class Settings:
    raw: dict = field(default_factory=dict)

    def __getattr__(self, name: str) -> dict:
        raw = self.__dict__.get("raw", {})
        if name in raw:
            return raw[name]
        raise AttributeError(name)

    def path(self, key: str) -> Path:
        p = Path(self.raw["paths"][key])
        return p if p.is_absolute() else PROJECT_ROOT / p

    def with_overrides(self, overrides: dict | None) -> "Settings":
        """Return a copy with runtime overrides applied (used per request by UI/API)."""
        if not overrides:
            return self
        return Settings(raw=_deep_update(copy.deepcopy(self.raw), overrides))

    def to_dict(self) -> dict:
        return copy.deepcopy(self.raw)


def load_settings(config_path: Path | None = None) -> Settings:
    if load_dotenv is not None:
        load_dotenv(PROJECT_ROOT / ".env", override=False)
    with open(config_path or DEFAULT_CONFIG, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    # Calibrated thresholds (produced by evaluation/calibrate.py on the dev set) override defaults.
    calibrated = PROJECT_ROOT / "config" / "calibrated.yaml"
    if config_path is None and calibrated.exists():
        with open(calibrated, "r", encoding="utf-8") as fh:
            overlay = yaml.safe_load(fh) or {}
        _deep_update(raw, overlay)
    for section, values in raw.items():
        if not isinstance(values, dict):
            continue
        for key, default in values.items():
            env_name = f"TRUSTGUARD_{section}_{key}".upper()
            if env_name in os.environ:
                values[key] = _coerce(os.environ[env_name], default)
    return Settings(raw=raw)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
