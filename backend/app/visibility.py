from __future__ import annotations

from app.models import HistoryEntry, MessageType


def is_visible(entry: HistoryEntry, viewer_id: str, viewer_role: str) -> bool:
    if entry.message_type == MessageType.public:
        return True
    if viewer_role == "host":
        return True
    return "all" in entry.visible_to or viewer_id in entry.visible_to


def filter_history(history: list[HistoryEntry], viewer_id: str, viewer_role: str) -> list[HistoryEntry]:
    return [entry for entry in history if is_visible(entry, viewer_id, viewer_role)]


def filter_state(state: dict, viewer_id: str, viewer_role: str) -> dict:
    if viewer_role == "host":
        return state
    filtered = dict(state)
    players = filtered.get("players", {})
    summarized: dict[str, dict] = {}
    for pid, pdata in players.items():
        if pid == viewer_id:
            summarized[pid] = pdata
        else:
            summarized[pid] = {
                "player_id": pdata.get("player_id", pid),
                "name": pdata.get("name"),
                "color": pdata.get("color"),
                "stats": {
                    "hp": pdata.get("stats", {}).get("hp"),
                    "hp_max": pdata.get("stats", {}).get("hp_max", pdata.get("stats", {}).get("hp")),
                    "san": pdata.get("stats", {}).get("san"),
                    "san_max": pdata.get("stats", {}).get("san_max", pdata.get("stats", {}).get("san")),
                },
            }
    filtered["players"] = summarized
    return filtered
