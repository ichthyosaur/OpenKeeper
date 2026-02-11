from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

import yaml


@dataclass
class AppConfig:
    mongo_uri: str
    mongo_db: str
    api_key: Optional[str]
    base_url: Optional[str]
    model: str
    history_count: int
    max_followups: int
    stream_cps: int
    temperature: float
    llm_parse_retries: int


DEFAULT_CONFIG = {
    "mongo_uri": "mongodb://localhost:27017",
    "mongo_db": "openkeeper",
    "api_key": None,
    "base_url": None,
    "model": "gpt-4o-mini",
    "history_count": 100,
    "max_followups": 2,
    "stream_cps": 50,
    "temperature": 0.7,
    "llm_parse_retries": 3,
}

ENV_KEY_MAP = {
    "OPENKEEPER_API_KEY": "api_key",
    "OPENKEEPER_BASE_URL": "base_url",
    "OPENKEEPER_MODEL": "model",
    "API_KEY": "api_key",
    "BASE_URL": "base_url",
    "MODEL": "model",
}


def _load_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    env: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            env[key] = value
    return env


def _apply_env(data: dict[str, Any], env: dict[str, str]) -> None:
    for env_key, config_key in ENV_KEY_MAP.items():
        value = env.get(env_key)
        if value is None:
            continue
        value = value.strip()
        if value == "":
            continue
        data[config_key] = value


def load_config(path: Union[str, Path]) -> AppConfig:
    data: dict[str, Any] = dict(DEFAULT_CONFIG)
    cfg_path = Path(path)
    if cfg_path.exists():
        with cfg_path.open("r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        if not isinstance(loaded, dict):
            raise ValueError("config.yaml must be a mapping")
        data.update(loaded)
    dotenv_paths = [
        cfg_path.parent.parent / ".env",
        cfg_path.parent / ".env",
    ]
    for dotenv_path in dotenv_paths:
        _apply_env(data, _load_dotenv(dotenv_path))
    _apply_env(data, os.environ)
    return AppConfig(
        mongo_uri=str(data.get("mongo_uri")),
        mongo_db=str(data.get("mongo_db")),
        api_key=data.get("api_key"),
        base_url=data.get("base_url"),
        model=str(data.get("model")),
        history_count=int(data.get("history_count")),
        max_followups=int(data.get("max_followups")),
        stream_cps=int(data.get("stream_cps")),
        temperature=float(data.get("temperature")),
        llm_parse_retries=max(0, int(data.get("llm_parse_retries"))),
    )
