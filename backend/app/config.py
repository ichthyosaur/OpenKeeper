from __future__ import annotations

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


def load_config(path: Union[str, Path]) -> AppConfig:
    data: dict[str, Any] = dict(DEFAULT_CONFIG)
    cfg_path = Path(path)
    if cfg_path.exists():
        with cfg_path.open("r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        if not isinstance(loaded, dict):
            raise ValueError("config.yaml must be a mapping")
        data.update(loaded)
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
