from __future__ import annotations

import random
import re
from typing import Any

from app.models import ActionCall


_DICE_RE = re.compile(r"^(\d+)d(\d+)([+-]\d+)?$")


def roll_dice_expression(expr: str) -> dict[str, Any]:
    match = _DICE_RE.match(expr.replace(" ", ""))
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
        result = roll_dice_expression(params["dice_expression"])
        return {"dice": result, "reason": params.get("reason"), "actor_id": params.get("actor_id")}
    if fn == "apply_damage":
        return _apply_damage(state, params)
    if fn == "apply_sanity_change":
        return _apply_sanity_change(state, params)
    if fn == "update_player_attribute":
        return _update_player_attribute(state, params)
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
