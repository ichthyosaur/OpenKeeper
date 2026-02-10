from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Iterable, Optional, List, Dict

from app.actions import dispatch_action
from app.db import MongoStore
from app.keeper import KeeperStub
from app.keeper_validation import validate_keeper_output
from app.models import (
    ActionCall,
    ActionType,
    ActorType,
    HistoryEntry,
    I18NText,
    KeeperOutput,
    MessageType,
    Module,
    PlayerProfile,
    SessionPlayer,
    SessionState,
)


class SessionManager:
    def __init__(
        self,
        store: MongoStore,
        module: Module,
        *,
        players: Optional[List[SessionPlayer]] = None,
        current_state: Optional[Dict[str, Any]] = None,
        history_count: int = 100,
    ) -> None:
        self.store = store
        self.module = module
        self.session_id = "default-session"
        self.round_id = str(uuid.uuid4())
        self.history_count = history_count
        self.state = SessionState(
            session_id=self.session_id,
            module_name=module.module_name,
            players=players or [],
            current_state=current_state or {"players": {}, "npcs": {}, "notes": {}},
            round_id=self.round_id,
            created_at=datetime.utcnow(),
            active=True,
        )
        self.history_cache: list[HistoryEntry] = []
        self.keeper = KeeperStub()

    async def ensure_session(self) -> None:
        existing = await self.store.sessions.find_one({"_id": self.session_id})
        if existing:
            return
        self.state.current_state["phase"] = "lobby"
        await self.store.sessions.insert_one(
            {
                "_id": self.session_id,
                "module_name": self.module.module_name,
                "players": [],
                "created_at": self.state.created_at,
                "active": True,
                "current_state": self.state.current_state,
                "round_id": self.round_id,
                "module_snapshot": self.module.model_dump(),
            }
        )

    async def hydrate_players(self) -> None:
        players: list[dict[str, Any]] = []
        if hasattr(self.store.players, "items"):
            players = list(self.store.players.items)
        else:
            cursor = self.store.players.find({})
            players = [doc async for doc in cursor]
        for doc in players:
            player_id = doc.get("player_id") or doc.get("_id")
            if not player_id:
                continue
            doc["player_id"] = player_id
            stats = doc.get("stats") or {}
            if "hp_max" not in stats:
                stats["hp_max"] = stats.get("hp", 10)
            if "san_max" not in stats:
                stats["san_max"] = stats.get("san", 60)
            doc["stats"] = stats
            self.state.current_state.setdefault("players", {})[player_id] = doc
            if not any(p.player_id == player_id for p in self.state.players):
                self.state.players.append(
                    SessionPlayer(
                        player_id=player_id,
                        name=doc.get("name", "Unknown"),
                        role="player",
                        color=doc.get("color", "#64748b"),
                    )
                )

    async def add_player(self, profile: PlayerProfile, role: str) -> None:
        if len(self.state.players) >= 12:
            raise ValueError("Room is full (max 12 players)")
        data = profile.model_dump(by_alias=True)
        await self.store.players.update_one(
            {"_id": profile.player_id},
            {"$set": data},
            upsert=True,
        )
        self.state.players.append(
            SessionPlayer(
                player_id=profile.player_id,
                name=profile.name,
                role=role,
                color=profile.color,
            )
        )
        self.state.current_state["players"][profile.player_id] = data
        await self.store.sessions.update_one(
            {"_id": self.session_id},
            {
                "$set": {
                    "players": [p.model_dump() for p in self.state.players],
                    "current_state": self.state.current_state,
                }
            },
        )

    async def handle_player_action(self, player_id: str, action_text: I18NText) -> list[HistoryEntry]:
        entries: list[HistoryEntry] = []
        phase = self.state.current_state.get("phase", "lobby")
        if phase != "active":
            entry = self._make_history_entry(
                actor_type=ActorType.system,
                actor_id="system",
                action_type=ActionType.rule_resolution,
                message_type=MessageType.system,
                visible_to=[player_id],
                content=I18NText(
                    zh="调查尚未开始，请等待主持人开启模组。",
                    en="Investigation has not started. Please wait for the host.",
                ),
            )
            await self._record_history(entry)
            return [entry]
        player = self.state.current_state.get("players", {}).get(player_id, {})
        stats = player.get("stats", {})
        if int(stats.get("hp", 1)) <= 0 or int(stats.get("san", 1)) <= 0:
            entry = self._make_history_entry(
                actor_type=ActorType.system,
                actor_id="system",
                action_type=ActionType.rule_resolution,
                message_type=MessageType.system,
                visible_to=[player_id],
                content=I18NText(
                    zh="你的角色已死亡或疯狂，无法再行动。",
                    en="Your character is dead or insane and cannot act.",
                ),
            )
            await self._record_history(entry)
            return [entry]
        player_entry = self._make_history_entry(
            actor_type=ActorType.player,
            actor_id=player_id,
            action_type=ActionType.player_action,
            message_type=MessageType.public,
            visible_to=["all"],
            content=action_text,
        )
        await self._record_history(player_entry)
        entries.append(player_entry)

        context_text = self.build_llm_context_text(self.history_count)
        keeper_output = self.keeper.generate(action_text, player_id, context_text)
        entries.extend(await self._handle_keeper_output(keeper_output))
        return entries

    async def _handle_keeper_output(self, output: KeeperOutput) -> list[HistoryEntry]:
        entries: list[HistoryEntry] = []
        errors = validate_keeper_output(output)
        if errors:
            entry = self._make_history_entry(
                actor_type=ActorType.system,
                actor_id="system",
                action_type=ActionType.rule_resolution,
                message_type=MessageType.system,
                visible_to=["all"],
                content=I18NText(
                    zh="Keeper 输出无效，已忽略。",
                    en="Keeper output invalid and ignored.",
                ),
                state_diff={"validation_errors": errors},
            )
            await self._record_history(entry)
            return [entry]
        if output.actions:
            action_entries = await self._apply_actions(
                output.actions, output.message_type, output.visible_to
            )
            entries.extend(action_entries)
        narration = self._make_history_entry(
            actor_type=ActorType.keeper,
            actor_id="keeper",
            action_type=ActionType.keeper_narration,
            message_type=output.message_type,
            visible_to=output.visible_to,
            content=output.content,
            actions=output.actions,
        )
        await self._record_history(narration)
        entries.append(narration)
        return entries

    async def add_keeper_narration(self, content: I18NText) -> HistoryEntry:
        entry = self._make_history_entry(
            actor_type=ActorType.keeper,
            actor_id="keeper",
            action_type=ActionType.keeper_narration,
            message_type=MessageType.public,
            visible_to=["all"],
            content=content,
        )
        await self._record_history(entry)
        return entry

    async def handle_keeper_output(self, output: KeeperOutput) -> list[HistoryEntry]:
        return await self._handle_keeper_output(output)

    async def _apply_actions(
        self, actions: Iterable[ActionCall], message_type: MessageType, visible_to: list[str]
    ) -> list[HistoryEntry]:
        entries: list[HistoryEntry] = []
        for action in actions:
            state_diff = dispatch_action(action, self.state.current_state)
            action_type = (
                ActionType.dice_roll if action.function_name == "roll_dice" else ActionType.state_update
            )
            content = self._action_content(action, state_diff)
            entry = self._make_history_entry(
                actor_type=ActorType.system,
                actor_id="system",
                action_type=action_type,
                message_type=message_type if message_type != MessageType.public else MessageType.system,
                visible_to=visible_to if message_type == MessageType.secret else ["all"],
                content=content,
                actions=[action],
                state_diff=state_diff,
            )
            await self._record_history(entry)
            entries.append(entry)
        await self.store.sessions.update_one(
            {"_id": self.session_id},
            {"$set": {"current_state": self.state.current_state}},
        )
        return entries

    def _action_content(self, action: ActionCall, state_diff: dict[str, Any]) -> I18NText:
        if action.function_name == "roll_dice":
            dice = state_diff.get("dice", {})
            total = dice.get("total", "?")
            expr = dice.get("expression", "")
            reason = state_diff.get("reason", "")
            return I18NText(
                zh=f"掷骰 {expr}，结果 {total}。{reason}",
                en=f"Rolled {expr}, result {total}. {reason}",
            )
        if action.function_name == "apply_damage":
            pid = action.parameters.get("player_id", "")
            amount = action.parameters.get("amount", "")
            return I18NText(
                zh=f"对 {pid} 造成伤害 {amount}。",
                en=f"Applied {amount} damage to {pid}.",
            )
        if action.function_name == "apply_sanity_change":
            pid = action.parameters.get("player_id", "")
            amount = action.parameters.get("amount", "")
            return I18NText(
                zh=f"对 {pid} 理智变化 {amount}。",
                en=f"Applied sanity change {amount} to {pid}.",
            )
        if action.function_name == "update_player_attribute":
            pid = action.parameters.get("player_id", "")
            attr = action.parameters.get("attribute", "")
            delta = action.parameters.get("delta", "")
            return I18NText(
                zh=f"调整 {pid} 属性 {attr} 变化 {delta}。",
                en=f"Adjusted {pid} attribute {attr} by {delta}.",
            )
        if action.function_name == "add_status":
            pid = action.parameters.get("player_id", "")
            status = action.parameters.get("status", "")
            return I18NText(
                zh=f"为 {pid} 添加状态 {status}。",
                en=f"Added status {status} to {pid}.",
            )
        if action.function_name == "remove_status":
            pid = action.parameters.get("player_id", "")
            status = action.parameters.get("status", "")
            return I18NText(
                zh=f"为 {pid} 移除状态 {status}。",
                en=f"Removed status {status} from {pid}.",
            )
        return I18NText(zh="系统执行动作。", en="System executed an action.")

    def _make_history_entry(
        self,
        *,
        actor_type: ActorType,
        actor_id: str,
        action_type: ActionType,
        message_type: MessageType,
        visible_to: list[str],
        content: Optional[I18NText],
        actions: Optional[list[ActionCall]] = None,
        state_diff: Optional[dict[str, Any]] = None,
    ) -> HistoryEntry:
        return HistoryEntry(
            timestamp=datetime.utcnow(),
            session_id=self.session_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action_type=action_type,
            message_type=message_type,
            visible_to=visible_to,
            content=content,
            actions=actions or [],
            state_diff=state_diff or {},
            round_id=self.round_id,
        )

    async def _record_history(self, entry: HistoryEntry) -> None:
        self.history_cache.append(entry)
        await self.store.history.insert_one(entry.model_dump())
        await self._snapshot_round()

    async def _snapshot_round(self) -> None:
        await self.store.snapshots.insert_one(
            {
                "session_id": self.session_id,
                "round_id": self.round_id,
                "created_at": datetime.utcnow(),
                "history": [h.model_dump() for h in self.history_cache],
                "final_state": self.state.current_state,
            }
        )

    async def get_history(self) -> list[HistoryEntry]:
        if self.history_cache:
            return list(self.history_cache)
        cursor = self.store.history.find({"session_id": self.session_id}).sort("timestamp", 1)
        data = [HistoryEntry(**doc) async for doc in cursor]
        self.history_cache = data
        return data

    def build_llm_history_text(self, limit: int = 100) -> str:
        entries = self.history_cache[-limit:] if self.history_cache else []
        lines: list[str] = []
        for entry in entries:
            text = self._entry_to_text(entry)
            if text:
                lines.append(text)
        return "\n".join(lines)

    def build_llm_context_text(self, limit: int = 100) -> str:
        history_text = self.build_llm_history_text(limit)
        state_lines: list[str] = []
        for pid, pdata in self.state.current_state.get("players", {}).items():
            stats = pdata.get("stats", {})
            hp = stats.get("hp", 0)
            hp_max = stats.get("hp_max", hp)
            san = stats.get("san", 0)
            san_max = stats.get("san_max", san)
            name = pdata.get("name", pid)
            state_lines.append(f\"{name}: HP {hp}/{hp_max}, SAN {san}/{san_max}\")
        state_text = \"\\n\".join(state_lines)
        return (\n            f\"模组: {self.module.module_name}\\n\"\n            f\"简介: {self.module.introduction}\\n\"\n            f\"当前状态:\\n{state_text}\\n\"\n            f\"历史:\\n{history_text}\"\n        )

    def _entry_to_text(self, entry: HistoryEntry) -> str:
        content = entry.content
        if content is None:
            return ""
        text = content.zh or content.en or ""
        if not text:
            return ""
        actor = self._actor_label(entry)
        secret_tag = "（秘密）" if entry.message_type == MessageType.secret else ""
        return f"{actor}{secret_tag}: {text}"

    def _actor_label(self, entry: HistoryEntry) -> str:
        if entry.actor_type == ActorType.player:
            player = self.state.current_state.get("players", {}).get(entry.actor_id, {})
            return player.get("name") or "玩家"
        if entry.actor_type == ActorType.keeper:
            return "Keeper"
        return "系统"

    async def reset_session(self) -> None:
        history = await self.get_history()
        if history:
            await self.store.snapshots.insert_one(
                {
                    "session_id": self.session_id,
                    "round_id": self.round_id,
                    "created_at": datetime.utcnow(),
                    "history": [h.model_dump() for h in history],
                    "final_state": self.state.current_state,
                }
            )
        self.history_cache = []
        self.round_id = str(uuid.uuid4())
        self.state.current_state["phase"] = "lobby"
        await self.store.history.delete_many({"session_id": self.session_id})
        await self.store.sessions.update_one(
            {"_id": self.session_id},
            {"$set": {"round_id": self.round_id, "current_state": self.state.current_state}},
        )
