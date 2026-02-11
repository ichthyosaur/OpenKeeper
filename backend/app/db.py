from __future__ import annotations

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, AsyncIterator, Optional, Union

from motor.motor_asyncio import AsyncIOMotorClient

from app.config import AppConfig


class MongoStore:
    def __init__(self, config: AppConfig) -> None:
        self.client = AsyncIOMotorClient(config.mongo_uri, serverSelectionTimeoutMS=2000)
        self.db = self.client[config.mongo_db]
        self.sessions = self.db["sessions"]
        self.history = self.db["history"]
        self.snapshots = self.db["snapshots"]
        self.players = self.db["players"]
        self.saves = self.db["saves"]

    async def ping(self) -> None:
        await self.client.admin.command("ping")


class MemoryCursor:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self._items = items

    def sort(self, key: str, direction: int) -> "MemoryCursor":
        reverse = direction < 0
        self._items.sort(key=lambda item: item.get(key), reverse=reverse)
        return self

    def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        async def iterator() -> AsyncIterator[dict[str, Any]]:
            for item in self._items:
                yield item

        return iterator()


class MemoryCollection:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    async def find_one(self, query: dict[str, Any]) -> Optional[dict[str, Any]]:
        for item in self.items:
            if all(item.get(k) == v for k, v in query.items()):
                return item
        return None

    async def insert_one(self, doc: dict[str, Any]) -> None:
        self.items.append(doc)

    async def update_one(self, query: dict[str, Any], update: dict[str, Any], upsert: bool = False) -> None:
        target = await self.find_one(query)
        if target is None:
            if not upsert:
                return
            target = dict(query)
            self.items.append(target)
        if "$set" in update:
            target.update(update["$set"])

    def find(self, query: dict[str, Any]) -> MemoryCursor:
        filtered = [item for item in self.items if all(item.get(k) == v for k, v in query.items())]
        return MemoryCursor(filtered)

    async def delete_many(self, query: dict[str, Any]) -> None:
        self.items = [item for item in self.items if not all(item.get(k) == v for k, v in query.items())]


class MemoryStore:
    def __init__(self, base_path: Optional[Path] = None) -> None:
        if base_path is not None:
            base_path.mkdir(parents=True, exist_ok=True)
        self._base_path = base_path
        self.sessions = MemoryCollection()
        self.history = MemoryCollection()
        self.snapshots = MemoryCollection()
        if base_path is None:
            self.players = MemoryCollection()
            self.saves = MemoryCollection()
        else:
            self.players = FileBackedCollection(base_path / "players.json")
            self.saves = FileBackedCollection(base_path / "saves.json")
        self.is_memory = True


class FileBackedCollection(MemoryCollection):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        if path.exists():
            try:
                self.items = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                self.items = []

    async def insert_one(self, doc: dict[str, Any]) -> None:
        await super().insert_one(doc)
        self._flush()

    async def update_one(self, query: dict[str, Any], update: dict[str, Any], upsert: bool = False) -> None:
        await super().update_one(query, update, upsert=upsert)
        self._flush()

    async def delete_many(self, query: dict[str, Any]) -> None:
        await super().delete_many(query)
        self._flush()

    def _flush(self) -> None:
        self.path.write_text(json.dumps(self.items, ensure_ascii=False, indent=2), encoding="utf-8")
