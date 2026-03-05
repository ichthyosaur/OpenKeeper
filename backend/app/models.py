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
        "update_npc_trust",
        "add_item",
        "add_clue",
        "add_status",
        "remove_status",
        "oppose_check",
        "end_module",
    ]
    parameters: dict[str, Any]


class KeeperOutput(BaseModel):
    message_type: MessageType
    visible_to: list[str]
    content: I18NText
    actions: list[ActionCall] = Field(default_factory=list)
    notes: Optional[Any] = None


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
    creation_meta: dict[str, Any] = Field(default_factory=dict)


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


class ModuleNode(BaseModel):
    node_id: str
    title: str
    mood: str
    public_signals: list[str] = Field(default_factory=list)
    hidden_truths: list[str] = Field(default_factory=list)
    connected_nodes: list[str] = Field(default_factory=list)


class ModuleNpc(BaseModel):
    npc_id: str
    name: str
    role: str
    public_face: str
    private_motive: str
    pressure_points: list[str] = Field(default_factory=list)


class ModuleClue(BaseModel):
    clue_id: str
    name: str
    description: str
    discovered_at: list[str] = Field(default_factory=list)
    validates: list[str] = Field(default_factory=list)
    ambiguity: str = "medium"
    reliability: str = "pending"


class ModuleItem(BaseModel):
    item_id: str
    name: str
    description: str
    discovered_at: list[str] = Field(default_factory=list)
    usage_hint: str = ""


class ModuleClockStage(BaseModel):
    at: int
    omen: str


class ModuleClockTickRule(BaseModel):
    event: Literal[
        "check_failure",
        "check_fumble",
        "hp_loss",
        "san_loss",
        "status_added",
    ]
    amount: int = 1
    min_loss: int = 1
    status_contains: str = ""
    action_names: list[str] = Field(default_factory=list)


class ModuleThreatClock(BaseModel):
    name: str
    max: int = 6
    tick_triggers: list[str] = Field(default_factory=list)
    stages: list[ModuleClockStage] = Field(default_factory=list)
    tick_rules: list[ModuleClockTickRule] = Field(default_factory=list)


class ModuleEnding(BaseModel):
    ending_id: str
    title: str
    summary: str
    trigger: str


class Module(BaseModel):
    module_id: str
    module_name: str
    introduction: str
    opening_narration: str
    tone: str = "mysterious, restrained, uneasy"
    investigation_principles: list[str] = Field(default_factory=list)
    nodes: list[ModuleNode] = Field(default_factory=list)
    npcs: list[ModuleNpc] = Field(default_factory=list)
    clues: list[ModuleClue] = Field(default_factory=list)
    items: list[ModuleItem] = Field(default_factory=list)
    threat_clock: ModuleThreatClock
    victory_conditions: list[str] = Field(default_factory=list)
    failure_conditions: list[str] = Field(default_factory=list)
    endings: list[ModuleEnding] = Field(default_factory=list)
    keeper_notes: list[str] = Field(default_factory=list)
