from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import load_config
from app.constants import PROFESSIONS
from app.db import MemoryStore, MongoStore
from app.models import I18NText, PlayerProfile, ActorType, ActionType, MessageType, KeeperOutput
from app.module_loader import load_module
from app.session import SessionManager
from app.visibility import filter_history, filter_state


APP_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = APP_ROOT / "config.yaml"
MODULE_PATH = APP_ROOT / "modules" / "module_zh_example.json"
FRONTEND_DIST = APP_ROOT.parent / "frontend" / "dist"
STATIC_APP = APP_ROOT / "static_app.html"
STATIC_HOST = APP_ROOT / "static_host.html"


app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"] ,
    allow_headers=["*"],
)

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


class Connection:
    def __init__(self, ws: WebSocket, player_id: str, role: str) -> None:
        self.ws = ws
        self.player_id = player_id
        self.role = role


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: list[Connection] = []
        self.lock = asyncio.Lock()
        self._online: dict[str, int] = {}

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
            await conn.ws.send_json(message)

    async def broadcast_filtered(self, entries: list, session: SessionManager) -> None:
        async with self.lock:
            targets = list(self.connections)
        for conn in targets:
            filtered = filter_history(entries, conn.player_id, conn.role)
            for entry in filtered:
                await conn.ws.send_json(
                    {
                        "type": "server.history_append",
                            "payload": {
                                "entry": entry.model_dump(mode="json"),
                                "visible_to": entry.visible_to,
                            },
                        }
                    )
            await conn.ws.send_json(
                {
                    "type": "server.state_update",
                    "payload": {
                        "state_diff": filter_state(
                            session.state.current_state, conn.player_id, conn.role
                        ),
                        "online_player_ids": await self.online_player_ids(),
                        "visible_to": ["all"],
                    },
                }
            )

    async def broadcast_state(self, session: SessionManager) -> None:
        async with self.lock:
            targets = list(self.connections)
        online_ids = await self.online_player_ids()
        for conn in targets:
            await conn.ws.send_json(
                {
                    "type": "server.state_update",
                    "payload": {
                        "state_diff": filter_state(
                            session.state.current_state, conn.player_id, conn.role
                        ),
                        "online_player_ids": online_ids,
                        "visible_to": ["all"],
                    },
                }
            )


config = load_config(CONFIG_PATH)
connections = ConnectionManager()


@app.on_event("startup")
async def startup() -> None:
    module = load_module(MODULE_PATH)
    try:
        store = MongoStore(config)
        await store.ping()
    except Exception:
        store = MemoryStore(APP_ROOT / "data")
    session = SessionManager(store, module, history_count=config.history_count)
    await session.ensure_session()
    await session.hydrate_players()
    app.state.config = config
    app.state.store = store
    app.state.module = module
    app.state.session = session


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def index() -> FileResponse:
    index_file = FRONTEND_DIST / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    if STATIC_APP.exists():
        return FileResponse(STATIC_APP)
    return FileResponse(APP_ROOT / "static_placeholder.html")


@app.get("/player")
async def player_page() -> FileResponse:
    if STATIC_APP.exists():
        return FileResponse(STATIC_APP)
    return FileResponse(APP_ROOT / "static_placeholder.html")


@app.get("/host")
async def host_page() -> FileResponse:
    if STATIC_HOST.exists():
        return FileResponse(STATIC_HOST)
    return FileResponse(APP_ROOT / "static_placeholder.html")


def _load_module_by_name(module_name: str) -> Path:
    modules_dir = APP_ROOT / "modules"
    for path in modules_dir.glob("*.json"):
        if path.stem == module_name:
            return path
    raise FileNotFoundError(module_name)


@app.post("/players")
async def create_player(payload: dict[str, Any]) -> dict[str, Any]:
    profile = PlayerProfile(**payload)
    session = app.state.session
    await session.add_player(profile, role="player")
    return {"ok": True, "player_id": profile.player_id}


@app.get("/players")
async def list_players(
    machine_id: str = Query(default=""),
    include_unbound: bool = Query(default=False),
) -> dict[str, Any]:
    session = app.state.session
    players = list(session.state.current_state.get("players", {}).values())
    if machine_id:
        if include_unbound:
            players = [
                p for p in players if p.get("machine_id") in ("", None, machine_id)
            ]
        else:
            players = [p for p in players if p.get("machine_id") == machine_id]
    return {"players": players}


@app.post("/players/claim")
async def claim_player(payload: dict[str, Any]) -> dict[str, Any]:
    player_id = payload.get("player_id")
    machine_id = payload.get("machine_id")
    if not player_id or not machine_id:
        return {"ok": False, "error": "player_id and machine_id required"}
    session = app.state.session
    player = session.state.current_state.get("players", {}).get(player_id)
    if not player:
        return {"ok": False, "error": "player not found"}
    player["machine_id"] = machine_id
    await session.store.players.update_one(
        {"_id": player_id},
        {"$set": {"machine_id": machine_id}},
        upsert=True,
    )
    return {"ok": True}


@app.get("/history")
async def get_history() -> dict[str, Any]:
    session = app.state.session
    history = await session.get_history()
    return {"history": [h.model_dump(mode="json") for h in history]}


@app.get("/professions")
async def get_professions() -> dict[str, Any]:
    return {"professions": PROFESSIONS}


@app.get("/modules")
async def list_modules() -> dict[str, Any]:
    modules_dir = APP_ROOT / "modules"
    modules = []
    for path in modules_dir.glob("*.json"):
        modules.append({"id": path.stem, "filename": path.name})
    return {"modules": modules}


@app.post("/session/reset")
async def reset_session() -> dict[str, Any]:
    session = app.state.session
    await session.reset_session()
    await connections.broadcast_state(session)
    return {"ok": True, "round_id": session.round_id}


@app.post("/session/start")
async def start_session(payload: dict[str, Any]) -> dict[str, Any]:
    module_name = payload.get("module_name")
    if not module_name:
        return {"ok": False, "error": "module_name required"}
    module_path = _load_module_by_name(module_name)
    module = load_module(module_path)
    store = app.state.store
    previous = app.state.session
    session = SessionManager(
        store,
        module,
        players=list(previous.state.players),
        current_state=dict(previous.state.current_state),
        history_count=app.state.config.history_count,
    )
    session.state.current_state["phase"] = "active"
    await session.ensure_session()
    app.state.module = module
    app.state.session = session
    entry = await session.add_keeper_narration(
        I18NText(zh=module.entry_narration, en=module.entry_narration)
    )
    await connections.broadcast_filtered([entry], session)
    return {"ok": True, "module_name": module.module_name, "round_id": session.round_id}


@app.post("/config/history")
async def update_history_count(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("history_count")
    try:
        count = max(1, int(value))
    except Exception:
        return {"ok": False, "error": "history_count must be int"}
    app.state.config.history_count = count
    app.state.session.history_count = count
    return {"ok": True, "history_count": count}


@app.post("/host/message")
async def host_message(payload: dict[str, Any]) -> dict[str, Any]:
    session = app.state.session
    try:
        output = KeeperOutput(**payload)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    entries = await session.handle_keeper_output(output)
    await connections.broadcast_filtered(entries, session)
    return {"ok": True, "entries": len(entries)}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    conn = None
    try:
        while True:
            message = await ws.receive_text()
            data = json.loads(message)
            msg_type = data.get("type")
            payload = data.get("payload", {})

            if msg_type == "client.join":
                session = app.state.session
                player_id = payload["player_id"]
                role = payload.get("role", "player")
                conn = await connections.connect(ws, player_id, role)
                history = await session.get_history()
                filtered_history = filter_history(history, player_id, role)
                visible_state = filter_state(session.state.current_state, player_id, role)
                await ws.send_json(
                    {
                        "type": "server.session_state",
                        "payload": {
                            "session_id": session.session_id,
                            "module_name": session.module.module_name,
                            "players": [p.model_dump(mode="json") for p in session.state.players],
                            "latest_history": [h.model_dump(mode="json") for h in filtered_history],
                            "visible_state": visible_state,
                            "online_player_ids": await connections.online_player_ids(),
                        },
                    }
                )
                await connections.broadcast_state(session)
                continue

            if conn is None:
                await ws.send_json({"type": "server.error", "payload": {"message": "not joined"}})
                continue

            if msg_type == "client.player_action":
                session = app.state.session
                action_text = I18NText(**payload.get("action_text", {}))
                entries = await session.handle_player_action(conn.player_id, action_text)
                await connections.broadcast_filtered(entries, session)
                continue

            if msg_type == "client.request_history":
                session = app.state.session
                history = await session.get_history()
                filtered = filter_history(history, conn.player_id, conn.role)
                for entry in filtered:
                    await ws.send_json(
                        {
                            "type": "server.history_append",
                            "payload": {
                                "entry": entry.model_dump(mode="json"),
                                "visible_to": entry.visible_to,
                            },
                        }
                    )
                continue

            await ws.send_json({"type": "server.error", "payload": {"message": "unknown type"}})

    except WebSocketDisconnect:
        if conn is not None:
            await connections.disconnect(conn)
            session = app.state.session
            await connections.broadcast_state(session)
