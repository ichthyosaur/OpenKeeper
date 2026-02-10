from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

import yaml


@dataclass(frozen=True)
class AppConfig:
    mongo_uri: str
    mongo_db: str
    api_key: Optional[str]
    base_url: Optional[str]
    model: str
    history_count: int


DEFAULT_CONFIG = {
    "mongo_uri": "mongodb://localhost:27017",
    "mongo_db": "openkeeper",
    "api_key": None,
    "base_url": None,
    "model": "gpt-4o-mini",
    "history_count": 100,
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
    )
