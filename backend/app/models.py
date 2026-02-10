from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, ConfigDict


class MessageType(str, Enum):
    public = "public"
    secret = "secret"
    system = "system"


class ActorType(str, Enum):
    player = "player"
    keeper = "keeper"
    system = "system"


class ActionType(str, Enum):
    player_action = "player_action"
    keeper_narration = "keeper_narration"
    dice_roll = "dice_roll"
    rule_resolution = "rule_resolution"
    state_update = "state_update"


class I18NText(BaseModel):
    zh: Optional[str] = None
    en: Optional[str] = None


class ActionCall(BaseModel):
    function_name: Literal[
        "roll_dice",
        "apply_damage",
        "apply_sanity_change",
        "update_player_attribute",
        "add_status",
        "remove_status",
    ]
    parameters: dict[str, Any]


class KeeperOutput(BaseModel):
    message_type: MessageType
    visible_to: list[str]
    content: I18NText
    actions: list[ActionCall] = Field(default_factory=list)
    notes: Optional[str] = None


class PlayerAttributes(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    str: int = 50
    dex: int = 50
    int_: int = Field(50, alias="int")
    con: int = 50
    app: int = 50
    pow: int = 50
    siz: int = 50
    edu: int = 50


class PlayerStats(BaseModel):
    hp: int = 10
    hp_max: int = 10
    san: int = 60
    san_max: int = 60
    mp: int = 10
    luck: int = 50


class PlayerProfile(BaseModel):
    player_id: str
    name: str
    gender: str
    color: str
    profession: str
    machine_id: Optional[str] = None
    background: Optional[str] = None
    attributes: PlayerAttributes = Field(default_factory=PlayerAttributes)
    stats: PlayerStats = Field(default_factory=PlayerStats)
    skills: dict[str, int] = Field(default_factory=dict)
    statuses: list[str] = Field(default_factory=list)


class SessionPlayer(BaseModel):
    player_id: str
    name: str
    role: Literal["player", "host"]
    color: str


class HistoryEntry(BaseModel):
    timestamp: datetime
    session_id: str
    actor_type: ActorType
    actor_id: str
    action_type: ActionType
    message_type: MessageType
    visible_to: list[str]
    content: Optional[I18NText] = None
    actions: list[ActionCall] = Field(default_factory=list)
    state_diff: dict[str, Any] = Field(default_factory=dict)
    round_id: str


class SessionState(BaseModel):
    session_id: str
    module_name: str
    players: list[SessionPlayer]
    current_state: dict[str, Any]
    round_id: str
    created_at: datetime
    active: bool = True


class ModuleCharacter(BaseModel):
    name: str
    public_info: str
    hidden_secrets: str


class ModuleEnding(BaseModel):
    ending_id: str
    description: str
    conditions: str


class Module(BaseModel):
    module_name: str
    introduction: str
    entry_narration: str
    key_characters: list[ModuleCharacter]
    core_secrets: list[str]
    possible_endings: list[ModuleEnding]
