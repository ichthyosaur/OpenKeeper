from __future__ import annotations

import random
import re
from typing import Any

from app.models import ActionCall


_DICE_RE = re.compile(r"(\d+)d(\d+)([+-]\d+)?", re.IGNORECASE)


def _coc_success_level(roll: int, target: int) -> str:
    if roll == 1:
        return "critical"
    if target < 50 and roll >= 96:
        return "fumble"
    if target >= 50 and roll == 100:
        return "fumble"
    if roll <= max(1, target // 5):
        return "extreme_success"
    if roll <= max(1, target // 2):
        return "hard_success"
    if roll <= target:
        return "regular_success"
    return "failure"


def roll_coc_check(
    target: int,
    *,
    bonus_dice: int = 0,
    penalty_dice: int = 0,
) -> dict[str, Any]:
    bonus = max(0, int(bonus_dice))
    penalty = max(0, int(penalty_dice))
    net = bonus - penalty
    unit = random.randint(0, 9)
    tens_count = 1 + abs(net)
    tens_rolls = [random.randint(0, 9) for _ in range(tens_count)]
    if net >= 0:
        chosen_tens = min(tens_rolls)
    else:
        chosen_tens = max(tens_rolls)
    total = chosen_tens * 10 + unit
    if total == 0:
        total = 100
    level = _coc_success_level(total, target)
    return {
        "type": "coc7e",
        "expression": "1d100",
        "unit": unit,
        "tens": chosen_tens,
        "tens_rolls": tens_rolls,
        "bonus_dice": bonus,
        "penalty_dice": penalty,
        "target": target,
        "total": total,
        "success_level": level,
    }


def _success_rank(level: str) -> int:
    order = {
        "critical": 5,
        "extreme_success": 4,
        "hard_success": 3,
        "regular_success": 2,
        "failure": 1,
        "fumble": 0,
    }
    return order.get(level, 1)


def _compare_opposed(a: dict[str, Any], b: dict[str, Any]) -> str:
    ar = _success_rank(a.get("success_level", "failure"))
    br = _success_rank(b.get("success_level", "failure"))
    if ar > br:
        return "attacker"
    if br > ar:
        return "defender"
    at = int(a.get("target", 0))
    bt = int(b.get("target", 0))
    if at > bt:
        return "attacker"
    if bt > at:
        return "defender"
    aroll = int(a.get("total", 0))
    broll = int(b.get("total", 0))
    if aroll > broll:
        return "attacker"
    if broll > aroll:
        return "defender"
    return "tie"


def roll_dice_expression(expr: str) -> dict[str, Any]:
    cleaned = expr.replace(" ", "")
    match = _DICE_RE.search(cleaned)
    if not match:
        raise ValueError("Invalid dice expression. Expected format like 1d100+10")
    count = int(match.group(1))
    sides = int(match.group(2))
    modifier = int(match.group(3) or 0)
    rolls = [random.randint(1, sides) for _ in range(count)]
    total = sum(rolls) + modifier
    return {
        "expression": expr,
        "rolls": rolls,
        "modifier": modifier,
        "total": total,
    }


def dispatch_action(action: ActionCall, state: dict[str, Any]) -> dict[str, Any]:
    fn = action.function_name
    params = action.parameters
    if fn == "roll_dice":
        target = params.get("target")
        if target is not None:
            result = roll_coc_check(
                int(target),
                bonus_dice=int(params.get("bonus_dice", 0)),
                penalty_dice=int(params.get("penalty_dice", 0)),
            )
            difficulty = params.get("difficulty", "regular")
            reason = params.get("reason")
            skill_name = params.get("skill_name")
            required = {
                "regular": "regular_success",
                "hard": "hard_success",
                "extreme": "extreme_success",
            }.get(difficulty, "regular_success")
            level = result.get("success_level", "failure")
            result["difficulty"] = difficulty
            result["is_success"] = level in ("critical", "extreme_success", "hard_success", "regular_success") and (
                required == "regular_success"
                or (required == "hard_success" and level in ("hard_success", "extreme_success", "critical"))
                or (required == "extreme_success" and level in ("extreme_success", "critical"))
            )
            return {
                "dice": result,
                "reason": reason,
                "actor_id": params.get("actor_id"),
                "skill_name": skill_name,
            }
        result = roll_dice_expression(params["dice_expression"])
        return {"dice": result, "reason": params.get("reason"), "actor_id": params.get("actor_id")}
    if fn == "oppose_check":
        attacker = params.get("attacker", {})
        defender = params.get("defender", {})
        reason = params.get("reason")
        a_roll = roll_coc_check(
            int(attacker.get("target", 0)),
            bonus_dice=int(attacker.get("bonus_dice", 0)),
            penalty_dice=int(attacker.get("penalty_dice", 0)),
        )
        b_roll = roll_coc_check(
            int(defender.get("target", 0)),
            bonus_dice=int(defender.get("bonus_dice", 0)),
            penalty_dice=int(defender.get("penalty_dice", 0)),
        )
        a_roll["difficulty"] = attacker.get("difficulty", "regular")
        b_roll["difficulty"] = defender.get("difficulty", "regular")
        a_roll["skill_name"] = attacker.get("skill_name")
        b_roll["skill_name"] = defender.get("skill_name")
        winner = _compare_opposed(a_roll, b_roll)
        return {
            "opposed": True,
            "attacker": a_roll,
            "defender": b_roll,
            "winner": winner,
            "reason": reason,
            "actor_id": params.get("actor_id"),
        }
    if fn == "apply_damage":
        return _apply_damage(state, params)
    if fn == "apply_sanity_change":
        return _apply_sanity_change(state, params)
    if fn == "update_player_attribute":
        return _update_player_attribute(state, params)
    if fn == "add_item":
        return _add_item(state, params)
    if fn == "add_clue":
        return _add_clue(state, params)
    if fn == "add_status":
        return _add_status(state, params)
    if fn == "remove_status":
        return _remove_status(state, params)
    raise ValueError(f"Unsupported function: {fn}")


def _get_player(state: dict[str, Any], player_id: str) -> dict[str, Any]:
    player = state.setdefault("players", {}).get(player_id)
    if player is None:
        raise KeyError(f"Player {player_id} not found")
    return player


def _apply_damage(state: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    player = _get_player(state, params["player_id"])
    amount = int(params["amount"])
    stats = player.setdefault("stats", {})
    current = int(stats.get("hp", 0))
    hp_max = int(stats.get("hp_max", current))
    stats["hp"] = max(0, min(hp_max, current - amount))
    return {
        "players": {
            params["player_id"]: {
                "stats": {"hp": stats["hp"], "hp_max": hp_max},
                "last_damage": {"amount": amount, "source": params.get("source")},
            }
        }
    }


def _apply_sanity_change(state: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    player = _get_player(state, params["player_id"])
    amount = int(params["amount"])
    stats = player.setdefault("stats", {})
    current = int(stats.get("san", 0))
    san_max = int(stats.get("san_max", current))
    stats["san"] = max(0, min(san_max, current + amount))
    return {
        "players": {
            params["player_id"]: {
                "stats": {"san": stats["san"], "san_max": san_max},
                "last_sanity": {"amount": amount, "source": params.get("source")},
            }
        }
    }


def _update_player_attribute(state: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    player = _get_player(state, params["player_id"])
    attribute = params["attribute"]
    delta = int(params["delta"])

    if attribute.startswith("skills."):
        skill = attribute.split(".", 1)[1]
        skills = player.setdefault("skills", {})
        skills[skill] = int(skills.get(skill, 0)) + delta
        return {"players": {params["player_id"]: {"skills": {skill: skills[skill]}}}}

    attributes = player.setdefault("attributes", {})
    if attribute in attributes:
        attributes[attribute] = int(attributes.get(attribute, 0)) + delta
        return {"players": {params["player_id"]: {"attributes": {attribute: attributes[attribute]}}}}

    stats = player.setdefault("stats", {})
    if attribute in stats:
        new_value = int(stats.get(attribute, 0)) + delta
        if attribute == "hp":
            hp_max = int(stats.get("hp_max", new_value))
            new_value = max(0, min(hp_max, new_value))
            stats["hp_max"] = hp_max
        if attribute == "san":
            san_max = int(stats.get("san_max", new_value))
            new_value = max(0, min(san_max, new_value))
            stats["san_max"] = san_max
        if attribute == "hp_max":
            new_value = max(1, new_value)
            stats["hp_max"] = new_value
            stats["hp"] = min(int(stats.get("hp", new_value)), new_value)
        if attribute == "san_max":
            new_value = max(1, new_value)
            stats["san_max"] = new_value
            stats["san"] = min(int(stats.get("san", new_value)), new_value)
        stats[attribute] = new_value
        return {"players": {params["player_id"]: {"stats": {attribute: stats[attribute]}}}}

    raise KeyError(f"Unknown attribute: {attribute}")


def _add_status(state: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    player = _get_player(state, params["player_id"])
    status = params["status"]
    statuses = player.setdefault("statuses", [])
    if status not in statuses:
        statuses.append(status)
    return {"players": {params["player_id"]: {"statuses": statuses}}}


def _remove_status(state: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    player = _get_player(state, params["player_id"])
    status = params["status"]
    statuses = player.setdefault("statuses", [])
    if status in statuses:
        statuses.remove(status)
    return {"players": {params["player_id"]: {"statuses": statuses}}}


def _normalize_finding(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        return {"description": raw}
    if isinstance(raw, dict):
        description = (
            raw.get("description")
            or raw.get("name")
            or raw.get("clue_id")
            or raw.get("item_id")
            or raw.get("id")
            or ""
        )
        result = {"description": description}
        if raw.get("reveal"):
            result["reveal"] = raw.get("reveal")
        if raw.get("effect"):
            result["effect"] = raw.get("effect")
        return result
    return {"description": ""}


def _extract_entries(params: dict[str, Any], key: str) -> list[dict[str, Any]]:
    entries: list[Any] = []
    plural = f"{key}s"
    if isinstance(params.get(plural), list):
        entries.extend(params.get(plural, []))
    if key in params:
        entries.append(params.get(key))
    if not entries and any(k in params for k in ("description", "name", "reveal", "effect", "details")):
        entries.append(params)
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        item = _normalize_finding(entry)
        if item.get("description"):
            normalized.append(item)
    return normalized


def _merge_findings(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    known = {item.get("description") for item in existing if item.get("description")}
    for entry in incoming:
        desc = entry.get("description")
        if not desc or desc in known:
            continue
        existing.append(entry)
        known.add(desc)
    return existing


def _add_item(state: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    player = _get_player(state, params["player_id"])
    items = player.setdefault("items", [])
    incoming = _extract_entries(params, "item")
    items = _merge_findings(items, incoming)
    player["items"] = items
    return {"players": {params["player_id"]: {"items": items}}}


def _add_clue(state: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    player = _get_player(state, params["player_id"])
    clues = player.setdefault("clues", [])
    incoming = _extract_entries(params, "clue")
    clues = _merge_findings(clues, incoming)
    player["clues"] = clues
    return {"players": {params["player_id"]: {"clues": clues}}}
