from __future__ import annotations

import asyncio
import socket
import uuid
import json
import yaml
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import load_config
from app.constants import PROFESSIONS
from app.db import MemoryStore, MongoStore
from app.models import (
    I18NText,
    PlayerProfile,
    ActorType,
    ActionType,
    MessageType,
    KeeperOutput,
    HistoryEntry,
    Module,
    SessionPlayer,
)
from app.module_loader import load_module
from app.keeper import KeeperStub
from app.keeper_llm import KeeperLLM
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


def _guess_lan_ip() -> str:
    ip = None
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
    except Exception:
        ip = None
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
    if not ip:
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            ip = "127.0.0.1"
    return ip


class Connection:
    def __init__(self, ws: WebSocket, player_id: str, role: str) -> None:
        self.ws = ws
        self.player_id = player_id
        self.role = role
        self.stream_lock = asyncio.Lock()


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
        tasks = [
            asyncio.create_task(self._send_entries(conn, entries, session))
            for conn in targets
        ]
        if tasks:
            await asyncio.gather(*tasks)

    async def _send_entries(self, conn: Connection, entries: list, session: SessionManager) -> None:
        filtered = filter_history(entries, conn.player_id, conn.role)
        for entry in filtered:
            if entry.actor_type == "keeper" and entry.content:
                app.state.last_keeper_text = entry.content.zh or entry.content.en or ""
                stream_id = str(uuid.uuid4())
                async with conn.stream_lock:
                    await self._stream_keeper_entry(conn, entry, stream_id)
                    await conn.ws.send_json(
                        {
                            "type": "server.history_append",
                            "payload": {
                                "entry": entry.model_dump(mode="json"),
                                "visible_to": entry.visible_to,
                                "stream_id": stream_id,
                            },
                        }
                    )
                continue
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

    async def _stream_keeper_entry(self, conn: Connection, entry, stream_id: str) -> None:
        content = entry.content
        if content is None:
            return
        text = content.zh or content.en or ""
        await conn.ws.send_json(
            {
                "type": "server.keeper_stream_start",
                "payload": {
                    "stream_id": stream_id,
                    "actor_type": entry.actor_type,
                    "message_type": entry.message_type,
                },
            }
        )
        interval = 0.05
        chunk_size = max(1, int(app.state.config.stream_cps * interval))
        for i in range(0, len(text), chunk_size):
            await conn.ws.send_json(
                {
                    "type": "server.keeper_stream_delta",
                    "payload": {"stream_id": stream_id, "delta": text[i : i + chunk_size]},
                }
            )
            await asyncio.sleep(interval)
        await conn.ws.send_json(
            {"type": "server.keeper_stream_end", "payload": {"stream_id": stream_id}}
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


def _persist_config() -> None:
    data = {
        "mongo_uri": app.state.config.mongo_uri,
        "mongo_db": app.state.config.mongo_db,
        "history_count": app.state.config.history_count,
        "max_followups": app.state.config.max_followups,
        "stream_cps": app.state.config.stream_cps,
        "temperature": app.state.config.temperature,
        "llm_parse_retries": app.state.config.llm_parse_retries,
    }
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


def _normalize_player_stats(player: dict[str, Any]) -> dict[str, Any]:
    stats = player.get("stats") or {}
    if "hp_max" not in stats:
        stats["hp_max"] = stats.get("hp", 10)
    if "san_max" not in stats:
        stats["san_max"] = stats.get("san", 60)
    player["stats"] = stats
    return player


def _build_session_players(state: dict[str, Any]) -> list[SessionPlayer]:
    players: list[SessionPlayer] = []
    for pid, pdata in (state.get("players") or {}).items():
        name = pdata.get("name", "Unknown")
        color = pdata.get("color", "#64748b")
        players.append(
            SessionPlayer(player_id=pid, name=name, role="player", color=color)
        )
    return players


@app.on_event("startup")
async def startup() -> None:
    module = load_module(MODULE_PATH)
    try:
        store = MongoStore(config)
        await store.ping()
    except Exception:
        store = MemoryStore(APP_ROOT / "data")
    keeper_llm = KeeperLLM(config, APP_ROOT / "app" / "keeper_prompt_zh.txt")
    app.state.keepers = {"llm": keeper_llm}
    session = SessionManager(
        store,
        module,
        history_count=config.history_count,
        max_followups=config.max_followups,
        keeper=keeper_llm,
        keeper_mode="llm",
    )
    await session.ensure_session()
    await session.hydrate_players()
    app.state.config = config
    app.state.store = store
    app.state.module = module
    app.state.session = session
    app.state.last_keeper_text = ""


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/local_ip")
async def local_ip(request: Request) -> dict[str, Any]:
    ip = _guess_lan_ip()
    host = request.headers.get("host", "").split(":")[0]
    port = request.url.port or 8000
    return {
        "ip": ip,
        "host": host,
        "port": port,
        "urls": {
            "player": f"http://{ip}:{port}/player",
            "host": f"http://{ip}:{port}/host",
            "ws": f"ws://{ip}:{port}/ws",
        },
    }


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


@app.post("/players/delete")
async def delete_player(payload: dict[str, Any]) -> dict[str, Any]:
    player_id = payload.get("player_id")
    if not player_id:
        return {"ok": False, "error": "player_id required"}
    session = app.state.session
    session.state.current_state.get("players", {}).pop(player_id, None)
    session.state.players = [p for p in session.state.players if p.player_id != player_id]
    await session.store.players.delete_many({"_id": player_id})
    await session.store.sessions.update_one(
        {"_id": session.session_id},
        {
            "$set": {
                "players": [p.model_dump() for p in session.state.players],
                "current_state": session.state.current_state,
            }
        },
    )
    await connections.broadcast_state(session)
    return {"ok": True}


@app.get("/history")
async def get_history() -> dict[str, Any]:
    session = app.state.session
    history = await session.get_history()
    return {"history": [h.model_dump(mode="json") for h in history]}


@app.get("/professions")
async def get_professions() -> dict[str, Any]:
    return JSONResponse(
        content={"professions": PROFESSIONS},
        media_type="application/json; charset=utf-8",
    )


@app.get("/modules")
async def list_modules() -> dict[str, Any]:
    modules_dir = APP_ROOT / "modules"
    modules = []
    for path in modules_dir.glob("*.json"):
        modules.append({"id": path.stem, "filename": path.name})
    return {"modules": modules}


@app.get("/module/current")
async def current_module() -> dict[str, Any]:
    module = app.state.module
    return {"module": module.model_dump()}


@app.get("/saves")
async def list_saves() -> dict[str, Any]:
    store = app.state.store
    cursor = store.saves.find({}).sort("updated_at", -1)
    saves: list[dict[str, Any]] = []
    async for doc in cursor:
        saves.append(
            {
                "save_id": doc.get("_id"),
                "name": doc.get("name") or doc.get("_id"),
                "module_name": doc.get("module_name"),
                "created_at": doc.get("created_at"),
                "updated_at": doc.get("updated_at"),
            }
        )
    return {"saves": saves}


@app.post("/saves/save")
async def save_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    save_name = (payload.get("save_name") or payload.get("name") or "").strip()
    if not save_name:
        return {"ok": False, "error": "save_name required"}
    save_id = (payload.get("save_id") or save_name).strip()
    overwrite = bool(payload.get("overwrite"))
    store = app.state.store
    existing = await store.saves.find_one({"_id": save_id})
    if existing and not overwrite:
        return {
            "ok": False,
            "error": "exists",
            "save_id": save_id,
            "name": existing.get("name") or save_name,
        }
    session = app.state.session
    history = await session.get_history()
    current_state = json.loads(json.dumps(session.state.current_state))
    for pid, pdata in (current_state.get("players") or {}).items():
        if isinstance(pdata, dict):
            pdata["player_id"] = pdata.get("player_id") or pid
            _normalize_player_stats(pdata)
    now = datetime.utcnow().isoformat()
    doc = {
        "_id": save_id,
        "name": save_name,
        "module_name": session.module.module_name,
        "created_at": existing.get("created_at") if existing else now,
        "updated_at": now,
        "module": session.module.model_dump(),
        "players": [p.model_dump() for p in session.state.players],
        "current_state": current_state,
        "history": [h.model_dump(mode="json") for h in history],
    }
    await store.saves.update_one({"_id": save_id}, {"$set": doc}, upsert=True)
    return {"ok": True, "save_id": save_id, "name": save_name}


@app.post("/saves/load")
async def load_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    save_id = (payload.get("save_id") or "").strip()
    if not save_id:
        return {"ok": False, "error": "save_id required"}
    store = app.state.store
    doc = await store.saves.find_one({"_id": save_id})
    if not doc:
        return {"ok": False, "error": "save not found"}
    module_data = doc.get("module") or {}
    module = Module(**module_data)

    session = app.state.session
    current_state = doc.get("current_state") or {"players": {}, "npcs": {}, "notes": {}}
    for pid, pdata in (current_state.get("players") or {}).items():
        if isinstance(pdata, dict):
            pdata["player_id"] = pdata.get("player_id") or pid
            _normalize_player_stats(pdata)
    current_state["phase"] = "active"

    saved_players = doc.get("players") or []
    if saved_players:
        session.state.players = [SessionPlayer(**p) for p in saved_players]
    else:
        session.state.players = _build_session_players(current_state)

    session.module = module
    session.state.module_name = module.module_name
    session.state.current_state = current_state
    session.state.active = True
    session.round_id = str(uuid.uuid4())
    session.state.round_id = session.round_id
    app.state.module = module

    await store.sessions.update_one(
        {"_id": session.session_id},
        {
            "$set": {
                "module_name": module.module_name,
                "players": [p.model_dump() for p in session.state.players],
                "current_state": session.state.current_state,
                "round_id": session.round_id,
                "active": True,
                "module_snapshot": module.model_dump(),
            }
        },
    )

    saved_ids = {pid for pid in (current_state.get("players") or {}).keys()}
    existing_players: list[dict[str, Any]] = []
    if hasattr(store.players, "items"):
        existing_players = list(store.players.items)
    else:
        existing_players = [p async for p in store.players.find({})]
    for doc_player in existing_players:
        pid = doc_player.get("player_id") or doc_player.get("_id")
        if pid and pid not in saved_ids:
            await store.players.delete_many({"_id": pid})
    for pid, pdata in (current_state.get("players") or {}).items():
        if isinstance(pdata, dict):
            await store.players.update_one(
                {"_id": pid},
                {"$set": pdata},
                upsert=True,
            )

    raw_history = doc.get("history") or []
    entries: list[HistoryEntry] = []
    for item in raw_history:
        if not isinstance(item, dict):
            continue
        record = dict(item)
        record["session_id"] = session.session_id
        record.setdefault("round_id", session.round_id)
        entries.append(HistoryEntry(**record))
    await store.history.delete_many({"session_id": session.session_id})
    for entry in entries:
        await store.history.insert_one(entry.model_dump())
    session.history_cache = entries

    await connections.broadcast(
        {"type": "server.history_clear", "payload": {"reason": "load_save"}}
    )
    await connections.broadcast(
        {
            "type": "server.module_info",
            "payload": {"module_introduction": module.introduction},
        }
    )
    if entries:
        await connections.broadcast_filtered(entries, session)
    else:
        await connections.broadcast_state(session)
    return {"ok": True, "save_id": save_id}


@app.post("/session/reset")
async def reset_session() -> dict[str, Any]:
    session = app.state.session
    await session.reset_session()
    await connections.broadcast({"type": "server.history_clear", "payload": {"reason": "reset"}})
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
        max_followups=app.state.config.max_followups,
        keeper=previous.keeper,
        keeper_mode=previous.keeper_mode,
    )
    session.state.current_state["phase"] = "active"
    session.state.current_state["theme"] = payload.get("theme") or session.state.current_state.get("theme", "archive")
    await session.ensure_session()
    app.state.module = module
    app.state.session = session
    entry = await session.add_keeper_narration(
        I18NText(zh=module.entry_narration, en=module.entry_narration)
    )
    await connections.broadcast({"type": "server.history_clear", "payload": {"reason": "module_switch"}})
    await connections.broadcast(
        {
            "type": "server.module_info",
            "payload": {"module_introduction": module.introduction},
        }
    )
    await connections.broadcast_filtered([entry], session)
    return {"ok": True, "module_name": module.module_name, "round_id": session.round_id}


@app.post("/session/end")
async def end_session(payload: dict[str, Any]) -> dict[str, Any]:
    ending_id = payload.get("ending_id", "")
    description = payload.get("description", "")
    if isinstance(description, dict):
        description = description.get("zh") or description.get("en") or ""
    session = app.state.session
    entry = await session.end_session(ending_id, description, app.state.last_keeper_text)
    await connections.broadcast_filtered([entry], session)
    await connections.broadcast({"type": "server.history_clear", "payload": {"reason": "host_end"}})
    await connections.broadcast_state(session)
    return {"ok": True}


@app.get("/keeper")
async def get_keeper() -> dict[str, Any]:
    session = app.state.session
    return {"keeper": session.keeper_mode, "model": app.state.config.model}


@app.get("/config")
async def get_config() -> dict[str, Any]:
    config = app.state.config
    return {
        "history_count": config.history_count,
        "max_followups": config.max_followups,
        "stream_cps": config.stream_cps,
        "temperature": config.temperature,
        "llm_parse_retries": config.llm_parse_retries,
        "model": config.model,
    }


@app.post("/keeper/select")
async def select_keeper(payload: dict[str, Any]) -> dict[str, Any]:
    mode = payload.get("keeper", "stub")
    if mode not in app.state.keepers:
        return {"ok": False, "error": "unknown keeper"}
    if mode == "llm" and (not app.state.config.api_key or not app.state.config.base_url):
        return {"ok": False, "error": "missing api_key/base_url"}
    session = app.state.session
    session.keeper = app.state.keepers[mode]
    session.keeper_mode = mode
    return {"ok": True, "keeper": mode}


@app.post("/config/history")
async def update_history_count(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("history_count")
    try:
        count = max(1, int(value))
    except Exception:
        return {"ok": False, "error": "history_count must be int"}
    app.state.config.history_count = count
    app.state.session.history_count = count
    _persist_config()
    return {"ok": True, "history_count": count}


@app.post("/config/followups")
async def update_max_followups(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("max_followups")
    try:
        count = max(0, int(value))
    except Exception:
        return {"ok": False, "error": "max_followups must be int"}
    app.state.config.max_followups = count
    app.state.session.max_followups = count
    _persist_config()
    return {"ok": True, "max_followups": count}


@app.post("/config/stream")
async def update_stream_cps(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("stream_cps")
    try:
        cps = max(1, int(value))
    except Exception:
        return {"ok": False, "error": "stream_cps must be int"}
    app.state.config.stream_cps = cps
    _persist_config()
    return {"ok": True, "stream_cps": cps}


@app.post("/config/temperature")
async def update_temperature(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("temperature")
    try:
        temp = float(value)
    except Exception:
        return {"ok": False, "error": "temperature must be number"}
    app.state.config.temperature = temp
    _persist_config()
    return {"ok": True, "temperature": temp}


@app.post("/config/llm-retry")
async def update_llm_retry(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("llm_parse_retries")
    try:
        retries = max(0, int(value))
    except Exception:
        return {"ok": False, "error": "llm_parse_retries must be int"}
    app.state.config.llm_parse_retries = retries
    _persist_config()
    return {"ok": True, "llm_parse_retries": retries}


@app.post("/config/theme")
async def update_theme(payload: dict[str, Any]) -> dict[str, Any]:
    theme = payload.get("theme", "archive")
    if theme not in ("archive", "nautical", "newsprint"):
        return {"ok": False, "error": "unknown theme"}
    session = app.state.session
    session.state.current_state["theme"] = theme
    await connections.broadcast(
        {"type": "server.theme_update", "payload": {"theme": theme}}
    )
    return {"ok": True, "theme": theme}


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


@app.get("/keeper/raw")
async def keeper_raw() -> dict[str, Any]:
    keeper = app.state.keepers.get("llm")
    if keeper is None:
        return {"ok": False, "error": "no llm keeper"}
    return {
        "ok": True,
        "raw": getattr(keeper, "last_raw", ""),
        "usage": getattr(keeper, "last_usage", None),
        "usage_total": getattr(app.state.session, "token_usage", None),
    }


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
                            "module_introduction": session.module.introduction,
                            "theme": session.state.current_state.get("theme", "archive"),
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
                online_ids = await connections.online_player_ids()
                entries = await session.handle_player_action(conn.player_id, action_text, online_ids)
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
