from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable, Iterable

from fastapi import WebSocket

from app.models import HistoryEntry


class Connection:
    def __init__(self, ws: WebSocket, player_id: str, role: str) -> None:
        self.ws = ws
        self.player_id = player_id
        self.role = role
        self.stream_lock = asyncio.Lock()


class ConnectionManager:
    def __init__(
        self,
        *,
        get_stream_cps: Callable[[], int],
        on_keeper_text: Callable[[str], None],
        filter_history: Callable[[list[HistoryEntry], str, str], list[HistoryEntry]],
        filter_state: Callable[[dict[str, Any], str, str], dict[str, Any]],
    ) -> None:
        self.connections: list[Connection] = []
        self.lock = asyncio.Lock()
        self._online: dict[str, int] = {}
        self._get_stream_cps = get_stream_cps
        self._on_keeper_text = on_keeper_text
        self._filter_history = filter_history
        self._filter_state = filter_state

    async def connect(self, ws: WebSocket, player_id: str, role: str) -> Connection:
        conn = Connection(ws, player_id, role)
        async with self.lock:
            self.connections.append(conn)
            self._online[player_id] = self._online.get(player_id, 0) + 1
        return conn

    async def disconnect(self, conn: Connection) -> None:
        async with self.lock:
            if conn in self.connections:
                self.connections.remove(conn)
            if conn.player_id in self._online:
                self._online[conn.player_id] -= 1
                if self._online[conn.player_id] <= 0:
                    self._online.pop(conn.player_id, None)

    async def online_player_ids(self) -> list[str]:
        async with self.lock:
            return list(self._online.keys())

    async def broadcast(self, message: dict[str, Any]) -> None:
        async with self.lock:
            targets = list(self.connections)
        for conn in targets:
            await self._safe_send(conn, message)

    async def broadcast_filtered(self, entries: list[HistoryEntry], session: Any) -> None:
        async with self.lock:
            targets = list(self.connections)
        tasks = [
            asyncio.create_task(self._send_entries(conn, entries, session))
            for conn in targets
        ]
        if tasks:
            await asyncio.gather(*tasks)

    async def _safe_send(self, conn: Connection, message: dict[str, Any]) -> bool:
        try:
            await conn.ws.send_json(message)
            return True
        except Exception:
            await self.disconnect(conn)
            return False

    async def _send_entries(self, conn: Connection, entries: Iterable[HistoryEntry], session: Any) -> None:
        filtered = self._filter_history(list(entries), conn.player_id, conn.role)
        for entry in filtered:
            if entry.actor_type == "keeper" and entry.content:
                text = entry.content.zh or entry.content.en or ""
                self._on_keeper_text(text)
                stream_id = str(uuid.uuid4())
                async with conn.stream_lock:
                    ok = await self._stream_keeper_entry(conn, entry, stream_id)
                    if not ok:
                        return
                    ok = await self._safe_send(
                        conn,
                        {
                            "type": "server.history_append",
                            "payload": {
                                "entry": entry.model_dump(mode="json"),
                                "visible_to": entry.visible_to,
                                "stream_id": stream_id,
                            },
                        },
                    )
                    if not ok:
                        return
                continue
            ok = await self._safe_send(
                conn,
                {
                    "type": "server.history_append",
                    "payload": {
                        "entry": entry.model_dump(mode="json"),
                        "visible_to": entry.visible_to,
                    },
                },
            )
            if not ok:
                return
        await self._safe_send(
            conn,
            {
                "type": "server.state_update",
                "payload": {
                    "state_diff": self._filter_state(
                        session.state.current_state, conn.player_id, conn.role
                    ),
                    "online_player_ids": await self.online_player_ids(),
                    "visible_to": ["all"],
                },
            },
        )

    async def _stream_keeper_entry(self, conn: Connection, entry: HistoryEntry, stream_id: str) -> bool:
        content = entry.content
        if content is None:
            return True
        text = content.zh or content.en or ""
        ok = await self._safe_send(
            conn,
            {
                "type": "server.keeper_stream_start",
                "payload": {
                    "stream_id": stream_id,
                    "actor_type": entry.actor_type,
                    "message_type": entry.message_type,
                },
            },
        )
        if not ok:
            return False
        interval = 0.05
        chunk_size = max(1, int(self._get_stream_cps() * interval))
        for i in range(0, len(text), chunk_size):
            ok = await self._safe_send(
                conn,
                {
                    "type": "server.keeper_stream_delta",
                    "payload": {"stream_id": stream_id, "delta": text[i : i + chunk_size]},
                },
            )
            if not ok:
                return False
            await asyncio.sleep(interval)
        return await self._safe_send(
            conn,
            {"type": "server.keeper_stream_end", "payload": {"stream_id": stream_id}},
        )

    async def broadcast_state(self, session: Any) -> None:
        async with self.lock:
            targets = list(self.connections)
        online_ids = await self.online_player_ids()
        for conn in targets:
            ok = await self._safe_send(
                conn,
                {
                    "type": "server.state_update",
                    "payload": {
                        "state_diff": self._filter_state(
                            session.state.current_state, conn.player_id, conn.role
                        ),
                        "online_player_ids": online_ids,
                        "visible_to": ["all"],
                    },
                },
            )
            if not ok:
                continue
