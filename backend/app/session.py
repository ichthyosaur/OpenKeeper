from __future__ import annotations

import uuid
import asyncio
from datetime import datetime
from typing import Any, Iterable, Optional, List, Dict, Union, Callable, Awaitable

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
        max_followups: int = 2,
        keeper: Optional[Any] = None,
        keeper_mode: str = "stub",
    ) -> None:
        self.store = store
        self.module = module
        self.session_id = "default-session"
        self.round_id = str(uuid.uuid4())
        self.history_count = history_count
        self.max_followups = max_followups
        base_state = current_state or {"players": {}, "npcs": {}, "notes": {}}
        base_state.setdefault("shared_findings", {"items": [], "clues": []})
        self.state = SessionState(
            session_id=self.session_id,
            module_name=module.module_name,
            players=players or [],
            current_state=base_state,
            round_id=self.round_id,
            created_at=datetime.utcnow(),
            active=True,
        )
        self.history_cache: list[HistoryEntry] = []
        self.keeper = keeper or KeeperStub()
        self.keeper_mode = keeper_mode
        self.token_usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}
        self.last_online_ids: list[str] = []

    async def ensure_session(self) -> None:
        existing = await self.store.sessions.find_one({"_id": self.session_id})
        if existing:
            return
        self.state.current_state["phase"] = "lobby"
        self.state.current_state.setdefault("shared_findings", {"items": [], "clues": []})
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

    async def handle_player_action(
        self,
        player_id: str,
        action_text: I18NText,
        online_ids: Optional[list[str]] = None,
        on_entries: Optional[Callable[[list[HistoryEntry]], Awaitable[None]]] = None,
    ) -> list[HistoryEntry]:
        entries: list[HistoryEntry] = []
        async def emit(new_entries: list[HistoryEntry]) -> None:
            if on_entries and new_entries:
                await on_entries(new_entries)
        if online_ids is not None:
            self.last_online_ids = list(online_ids)
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
            await emit([entry])
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
            await emit([entry])
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
        await emit([player_entry])

        system_text = self.build_llm_context_text(self.history_count, online_ids)
        history_text = self.build_llm_history_text(self.history_count)
        context_text = f"[System]\n{system_text}\n\n[History]\n{history_text}"
        try:
            keeper_output = self.keeper.generate(action_text, player_id, context_text)
            self._accumulate_token_usage()
            keeper_entries = await self._handle_keeper_output(keeper_output)
            entries.extend(keeper_entries)
            await emit(keeper_entries)
            if (
                keeper_output.actions
                and self.state.current_state.get("phase") != "ended"
                and self._is_player_active(player_id)
            ):
                follow_entries = await self._followup_after_actions(
                    player_id, online_ids, on_entries=on_entries
                )
                entries.extend(follow_entries)
            if self._should_force_ending(keeper_output.actions, online_ids):
                forced_entries = await self._force_ending(player_id, online_ids)
                entries.extend(forced_entries)
                await emit(forced_entries)
        except Exception as exc:
            msg = str(exc)
            if "timed out" in msg.lower():
                public_entry = self._make_history_entry(
                    actor_type=ActorType.system,
                    actor_id="system",
                    action_type=ActionType.rule_resolution,
                    message_type=MessageType.system,
                    visible_to=["all"],
                    content=I18NText(
                        zh="寒风掠过，屋内的影子像被潮湿的海雾牵扯般摇曳。守密者的回应迟缓而阴沉。",
                        en="A damp wind drifts through, and the shadows waver like a distant sea-fog. The Keeper's answer falters.",
                    ),
                    state_diff={"keeper_error": msg},
                )
                await self._record_history(public_entry)
                entries.append(public_entry)
                await emit([public_entry])
            host_entry = self._make_history_entry(
                actor_type=ActorType.system,
                actor_id="system",
                action_type=ActionType.rule_resolution,
                message_type=MessageType.system,
                visible_to=["host"],
                content=I18NText(
                    zh=f"Keeper 调用失败：{exc}",
                    en=f"Keeper call failed: {exc}",
                ),
                state_diff={"keeper_error": msg},
            )
            await self._record_history(host_entry)
            entries.append(host_entry)
            await emit([host_entry])
        return entries

    async def _handle_keeper_output(self, output: KeeperOutput) -> list[HistoryEntry]:
        entries: list[HistoryEntry] = []
        if output.message_type == MessageType.public:
            output.visible_to = ["all"]
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
        if output.actions:
            action_entries = await self._apply_actions(
                output.actions, output.message_type, output.visible_to
            )
            entries.extend(action_entries)
            if self.state.current_state.get("phase") == "ended":
                return entries
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

    async def _followup_after_actions(
        self,
        player_id: str,
        online_ids: Optional[list[str]] = None,
        on_entries: Optional[Callable[[list[HistoryEntry]], Awaitable[None]]] = None,
    ) -> list[HistoryEntry]:
        followups = 0
        all_entries: list[HistoryEntry] = []
        async def emit(new_entries: list[HistoryEntry]) -> None:
            if on_entries and new_entries:
                await on_entries(new_entries)
        while followups < self.max_followups:
            if not self._is_player_active(player_id):
                break
            followups += 1
            system_text = self.build_llm_context_text(self.history_count, online_ids)
            history_text = self.build_llm_history_text(self.history_count)
            context_text = f"[System]\n{system_text}\n\n[History]\n{history_text}"
            follow_text = I18NText(
                zh="请基于刚刚的叙事与动作结果继续叙事，必须输出JSON。如果仍需要新的判定/动作，可以在 actions 中给出；否则 actions 留空。",
                en="Continue the narration based on the latest narration and action results. Output JSON only. If further actions are needed, include them in actions; otherwise keep actions empty.",
            )
            output = None
            for attempt in range(2):
                try:
                    output = self.keeper.generate(follow_text, player_id, context_text)
                    self._accumulate_token_usage()
                except Exception as exc:
                    entry = self._make_history_entry(
                        actor_type=ActorType.system,
                        actor_id="system",
                        action_type=ActionType.rule_resolution,
                        message_type=MessageType.system,
                        visible_to=["host"],
                        content=I18NText(
                            zh=f"续写失败：{exc}",
                            en=f"Follow-up failed: {exc}",
                        ),
                    )
                    await self._record_history(entry)
                    all_entries.append(entry)
                    return all_entries
                if output and (output.notes or "").startswith("llm_parse_error") and attempt == 0:
                    await asyncio.sleep(0.5)
                    continue
                break

            if output is None:
                break
            follow_entries = await self._handle_keeper_output(output)
            all_entries.extend(follow_entries)
            await emit(follow_entries)

            if not output.actions or self.state.current_state.get("phase") == "ended":
                break
            await asyncio.sleep(5)
        return all_entries
        # follow-ups handled in loop above

    async def _apply_actions(
        self, actions: Iterable[ActionCall], message_type: MessageType, visible_to: list[str]
    ) -> list[HistoryEntry]:
        entries: list[HistoryEntry] = []
        online_ids = self.last_online_ids or None
        for action in actions:
            if action.function_name == "end_module":
                params = action.parameters or {}
                ending_id = params.get("ending_id", "")
                description = params.get("description", "")
                if isinstance(description, dict):
                    description = description.get("zh") or description.get("en") or ""
                entry = await self.end_session(ending_id, description)
                entries.append(entry)
                continue
            state_diff = dispatch_action(action, self.state.current_state)
            action_type = (
                ActionType.dice_roll
                if action.function_name in ("roll_dice", "oppose_check")
                else ActionType.state_update
            )
            content = self._action_content(action, state_diff)
            entry = self._make_history_entry(
                actor_type=ActorType.system,
                actor_id="system",
                action_type=action_type,
                message_type=MessageType.system,
                visible_to=["all"],
                content=content,
                actions=[action],
                state_diff=state_diff,
            )
            await self._record_history(entry)
            entries.append(entry)
            await self._persist_player_if_needed(action)
            death_entry = self._maybe_add_death_or_madness(action)
            if death_entry is not None:
                await self._record_history(death_entry)
                entries.append(death_entry)
                await self._persist_player_if_needed(action)
                if self._should_force_ending(None, online_ids):
                    entries.extend(await self._force_ending(action.parameters.get("player_id", ""), online_ids))
        await self.store.sessions.update_one(
            {"_id": self.session_id},
            {"$set": {"current_state": self.state.current_state}},
        )
        return entries

    async def _persist_player_if_needed(self, action: ActionCall) -> None:
        params = action.parameters or {}
        player_id = params.get("player_id")
        if not player_id:
            return
        player = self.state.current_state.get("players", {}).get(player_id)
        if not player:
            return
        await self.store.players.update_one(
            {"_id": player_id},
            {"$set": player},
            upsert=True,
        )

    def _action_content(self, action: ActionCall, state_diff: dict[str, Any]) -> I18NText:
        if action.function_name == "roll_dice":
            dice = state_diff.get("dice", {})
            total = dice.get("total", "?")
            expr = dice.get("expression", "")
            reason = state_diff.get("reason", "")
            if dice.get("type") == "coc7e":
                target = dice.get("target")
                level = dice.get("success_level", "failure")
                difficulty = dice.get("difficulty", "regular")
                difficulty_map = {
                    "regular": "常规",
                    "hard": "困难",
                    "extreme": "极难",
                }
                level_map = {
                    "critical": "大成功",
                    "extreme_success": "极难成功",
                    "hard_success": "困难成功",
                    "regular_success": "成功",
                    "failure": "失败",
                    "fumble": "大失败",
                }
                skill_name = state_diff.get("skill_name", "")
                return I18NText(
                    zh=(
                        f"检定 {skill_name or ''} 目标{target} 难度{difficulty_map.get(difficulty, difficulty)}，"
                        f"结果{total}（{level_map.get(level, level)}）。{reason}"
                    ),
                    en=f"Check {skill_name or ''} target {target} difficulty {difficulty}, roll {total} ({level}). {reason}",
                )
            return I18NText(
                zh=f"掷骰 {expr}，结果 {total}。{reason}",
                en=f"Rolled {expr}, result {total}. {reason}",
            )
        if action.function_name == "oppose_check":
            reason = state_diff.get("reason", "")
            attacker = state_diff.get("attacker", {})
            defender = state_diff.get("defender", {})
            winner = state_diff.get("winner", "tie")
            a_total = attacker.get("total", "?")
            b_total = defender.get("total", "?")
            a_skill = attacker.get("skill_name") or "攻击方"
            b_skill = defender.get("skill_name") or "防守方"
            return I18NText(
                zh=f"对抗检定 {a_skill}({a_total}) vs {b_skill}({b_total})，胜者：{winner}。{reason}",
                en=f"Opposed check {a_skill}({a_total}) vs {b_skill}({b_total}), winner: {winner}. {reason}",
            )
        if action.function_name == "apply_damage":
            pid = action.parameters.get("player_id", "")
            amount = action.parameters.get("amount", "")
            name = self.state.current_state.get("players", {}).get(pid, {}).get("name", pid)
            return I18NText(
                zh=f"对 {name} 造成伤害 {amount}。",
                en=f"Applied {amount} damage to {name}.",
            )
        if action.function_name == "apply_sanity_change":
            pid = action.parameters.get("player_id", "")
            amount = action.parameters.get("amount", "")
            name = self.state.current_state.get("players", {}).get(pid, {}).get("name", pid)
            return I18NText(
                zh=f"对 {name} 理智变化 {amount}。",
                en=f"Applied sanity change {amount} to {name}.",
            )
        if action.function_name == "update_player_attribute":
            pid = action.parameters.get("player_id", "")
            attr = action.parameters.get("attribute", "")
            delta = action.parameters.get("delta", "")
            name = self.state.current_state.get("players", {}).get(pid, {}).get("name", pid)
            return I18NText(
                zh=f"调整 {name} 属性 {attr} 变化 {delta}。",
                en=f"Adjusted {name} attribute {attr} by {delta}.",
            )
        if action.function_name == "add_status":
            pid = action.parameters.get("player_id", "")
            status = action.parameters.get("status", "")
            name = self.state.current_state.get("players", {}).get(pid, {}).get("name", pid)
            return I18NText(
                zh=f"为 {name} 添加状态 {status}。",
                en=f"Added status {status} to {name}.",
            )
        if action.function_name == "add_item":
            pid = action.parameters.get("player_id", "")
            raw = action.parameters.get("item") or action.parameters
            description = raw.get("description") or raw.get("name") or ""
            name = self.state.current_state.get("players", {}).get(pid, {}).get("name", pid)
            return I18NText(
                zh=f"为 {name} 添加物品 {description}。",
                en=f"Added item {description} to {name}.",
            )
        if action.function_name == "add_clue":
            pid = action.parameters.get("player_id", "")
            raw = action.parameters.get("clue") or action.parameters
            description = raw.get("description") or raw.get("clue_id") or raw.get("name") or ""
            name = self.state.current_state.get("players", {}).get(pid, {}).get("name", pid)
            return I18NText(
                zh=f"为 {name} 添加线索 {description}。",
                en=f"Added clue {description} to {name}.",
            )
        if action.function_name == "remove_status":
            pid = action.parameters.get("player_id", "")
            status = action.parameters.get("status", "")
            name = self.state.current_state.get("players", {}).get(pid, {}).get("name", pid)
            return I18NText(
                zh=f"为 {name} 移除状态 {status}。",
                en=f"Removed status {status} from {name}.",
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

    def _maybe_add_death_or_madness(self, action: ActionCall) -> Optional[HistoryEntry]:
        params = action.parameters or {}
        player_id = params.get("player_id")
        if not player_id:
            return None
        player = self.state.current_state.get("players", {}).get(player_id, {})
        stats = player.get("stats", {})
        statuses = player.setdefault("statuses", [])
        hp = int(stats.get("hp", 1))
        san = int(stats.get("san", 1))
        if hp > 0 and san > 0:
            return None
        name = player.get("name", player_id)
        if hp <= 0:
            if "dead" in statuses:
                return None
            statuses.append("dead")
            content = I18NText(
                zh=f"{name} 的呼吸在冰冷的空气里断成空白，身体缓缓失去力量，倒在尘土与阴影之间。",
                en=f"{name}'s breath fades into the cold air and the body collapses into dust and shadow.",
            )
        else:
            if "insane" in statuses:
                return None
            statuses.append("insane")
            content = I18NText(
                zh=f"{name} 的目光失焦，低语吞没了意识，理智在沉默里崩塌。",
                en=f"{name}'s gaze breaks; whispers swallow the mind and reason collapses into silence.",
            )
        return self._make_history_entry(
            actor_type=ActorType.keeper,
            actor_id="keeper",
            action_type=ActionType.keeper_narration,
            message_type=MessageType.public,
            visible_to=["all"],
            content=content,
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

    def build_llm_context_text(
        self, limit: int = 100, online_ids: Optional[list[str]] = None
    ) -> str:
        module = self.module
        state_lines: list[str] = []
        id_lines: list[str] = []
        for pid, pdata in self.state.current_state.get("players", {}).items():
            if online_ids is not None and pid not in online_ids:
                continue
            stats = pdata.get("stats", {})
            hp = stats.get("hp", 0)
            hp_max = stats.get("hp_max", hp)
            san = stats.get("san", 0)
            san_max = stats.get("san_max", san)
            name = pdata.get("name", pid)
            statuses = pdata.get("statuses", [])
            items = pdata.get("items", [])
            clues = pdata.get("clues", [])
            state_lines.append(
                f"{name}: HP {hp}/{hp_max}, SAN {san}/{san_max}, "
                f"状态 {statuses or []}, 道具 {items or []}, 线索 {clues or []}"
            )
            id_lines.append(f"- {name} (player_id: {pid})")
        state_text = "\n".join(state_lines)
        id_text = "\n".join(id_lines)
        locations_text = "\n".join(
            (
                f"- {loc.name}: {loc.description}\n"
                f"  特征: {loc.features or []}\n"
                f"  秘密: {loc.secrets or []}\n"
                f"  连接: {loc.connections or []}"
            )
            for loc in module.locations
        )
        scenes_text = "\n".join(
            (
                f"- {scene.title}: {scene.summary}\n"
                f"  节拍: {scene.beats or []}\n"
                f"  需要线索: {scene.required_clues or []}\n"
                f"  结果: {scene.outcomes or []}"
            )
            for scene in module.scenes
        )
        clues_text = "\n".join(
            (
                f"- {clue.clue_id} @ {clue.location}: {clue.description}\n"
                f"  关联: {clue.linked_to or []}\n"
                f"  揭示: {clue.reveal}"
            )
            for clue in module.clues
        )
        events_text = "\n".join(
            (
                f"- {event.event_id}: {event.description}\n"
                f"  触发: {event.trigger}\n"
                f"  后果: {event.consequences or []}"
            )
            for event in module.events
        )
        items_text = "\n".join(
            (
                f"- {item.name}: {item.description}\n"
                f"  效果: {item.effect}\n"
                f"  位置: {item.location}"
            )
            for item in module.items
        )
        factions_text = "\n".join(
            (
                f"- {faction.name}: {faction.goal}\n"
                f"  资源: {faction.resources or []}\n"
                f"  手段: {faction.methods or []}\n"
                f"  态度: {faction.attitude}"
            )
            for faction in module.factions
        )
        threats_text = "\n".join(
            (
                f"- {threat.name}: {threat.nature}\n"
                f"  征兆: {threat.signs or []}\n"
                f"  升级: {threat.escalation or []}\n"
                f"  弱点: {threat.weakness}"
            )
            for threat in module.threats
        )
        timeline_text = "\n".join(
            f"- {entry.time}: {entry.event}" for entry in module.timeline
        )
        ending_triggers_text = "\n".join(f"- {t}" for t in module.ending_triggers)
        characters_text = "\n".join(
            f"- {ch.name}: {ch.public_info}\n  隐藏: {ch.hidden_secrets}"
            for ch in module.key_characters
        )
        secrets_text = "\n".join(f"- {s}" for s in module.core_secrets)
        endings_text = "\n".join(
            f"- {e.ending_id}: {e.description}\n  条件: {e.conditions}"
            for e in module.possible_endings
        )
        return (
            f"模组: {module.module_name}\n"
            f"简介: {module.introduction}\n"
            f"开场叙事: {module.entry_narration}\n"
            f"关键人物:\n{characters_text}\n"
            f"核心秘密:\n{secrets_text}\n"
            f"可能结局:\n{endings_text}\n"
            f"玩家ID列表:\n{id_text}\n"
            f"地点:\n{locations_text}\n"
            f"场景:\n{scenes_text}\n"
            f"线索:\n{clues_text}\n"
            f"事件:\n{events_text}\n"
            f"道具:\n{items_text}\n"
            f"势力:\n{factions_text}\n"
            f"威胁:\n{threats_text}\n"
            f"时间线:\n{timeline_text}\n"
            f"结局触发条件:\n{ending_triggers_text}\n"
            f"当前状态:\n{state_text}"
        )

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

    def _is_player_active(self, player_id: str) -> bool:
        player = self.state.current_state.get("players", {}).get(player_id, {})
        stats = player.get("stats", {})
        return int(stats.get("hp", 1)) > 0 and int(stats.get("san", 1)) > 0

    def _accumulate_token_usage(self) -> None:
        usage = getattr(self.keeper, "last_usage", None) or {}
        self.token_usage["prompt_tokens"] += int(usage.get("prompt_tokens", 0) or 0)
        self.token_usage["completion_tokens"] += int(usage.get("completion_tokens", 0) or 0)

    def reset_token_usage(self) -> None:
        self.token_usage = {"prompt_tokens": 0, "completion_tokens": 0}

    def _all_players_inactive(self, online_ids: Optional[list[str]] = None) -> bool:
        players = list(self.state.current_state.get("players", {}).values())
        if online_ids:
            players = [p for p in players if p.get("player_id") in online_ids]
        if not players:
            return False
        for player in players:
            stats = player.get("stats", {})
            if int(stats.get("hp", 1)) > 0 and int(stats.get("san", 1)) > 0:
                return False
        return True

    def _should_force_ending(
        self, actions: Optional[list[ActionCall]], online_ids: Optional[list[str]] = None
    ) -> bool:
        if self.state.current_state.get("phase") == "ended":
            return False
        if self.state.current_state.get("ending_forced"):
            return False
        if actions and any(a.function_name == "end_module" for a in actions):
            return False
        return self._all_players_inactive(online_ids)

    async def _force_ending(
        self, player_id: str, online_ids: Optional[list[str]] = None
    ) -> list[HistoryEntry]:
        self.state.current_state["ending_forced"] = True
        await self.store.sessions.update_one(
            {"_id": self.session_id},
            {"$set": {"current_state": self.state.current_state}},
        )
        entries: list[HistoryEntry] = []

        system_text = self.build_llm_context_text(self.history_count, online_ids)
        history_text = self.build_llm_history_text(self.history_count)
        context_text = f"[System]\n{system_text}\n\n[History]\n{history_text}"
        follow_text = I18NText(
            zh="所有玩家已死亡或疯狂。请立刻输出结局叙事并调用 end_module，选择最符合的 ending_id。",
            en="All players are dead or insane. Immediately output an ending and call end_module with the best ending_id.",
        )
        output = self.keeper.generate(follow_text, player_id, context_text)
        self._accumulate_token_usage()
        entries.extend(await self._handle_keeper_output(output))
        return entries

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
        self.reset_token_usage()
        for pid, pdata in self.state.current_state.get("players", {}).items():
            stats = pdata.get("stats", {})
            hp_max = stats.get("hp_max", stats.get("hp", 10))
            san_max = stats.get("san_max", stats.get("san", 60))
            stats["hp"] = hp_max
            stats["san"] = san_max
            pdata["stats"] = stats
            pdata["items"] = []
            pdata["clues"] = []
            statuses = pdata.get("statuses") or []
            if statuses:
                pdata["statuses"] = [
                    s
                    for s in statuses
                    if not (str(s).startswith("持有道具：") or str(s).startswith("持有线索："))
                ]
            await self.store.players.update_one(
                {"_id": pid},
                {"$set": pdata},
                upsert=True,
            )
        self.state.current_state["shared_findings"] = {"items": [], "clues": []}
        await self.store.history.delete_many({"session_id": self.session_id})
        await self.store.sessions.update_one(
            {"_id": self.session_id},
            {"$set": {"round_id": self.round_id, "current_state": self.state.current_state}},
        )

    async def end_session(self, ending_id: str, description: str, keeper_text: str = "") -> HistoryEntry:
        self.state.current_state["phase"] = "ended"
        await self.store.sessions.update_one(
            {"_id": self.session_id},
            {"$set": {"active": False, "current_state": self.state.current_state}},
        )
        conditions = ""
        for ending in self.module.possible_endings:
            if ending.ending_id == ending_id:
                conditions = ending.conditions
                break
        if not conditions and self.module.ending_triggers:
            conditions = " / ".join(self.module.ending_triggers)
        entry = self._make_history_entry(
            actor_type=ActorType.system,
            actor_id="system",
            action_type=ActionType.rule_resolution,
            message_type=MessageType.public,
            visible_to=["all"],
            content=I18NText(
                zh=f"模组结束：{description}",
                en=f"Module ended: {description}",
            ),
            state_diff={
                "ending_id": ending_id,
                "description": description,
                "keeper_text": keeper_text,
                "conditions": conditions,
            },
        )
        await self._record_history(entry)
        return entry
