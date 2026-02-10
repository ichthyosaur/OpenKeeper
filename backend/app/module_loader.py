from __future__ import annotations

import json
from pathlib import Path
from typing import Union

from app.models import Module


def load_module(path: Union[str, Path]) -> Module:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Module(**data)
