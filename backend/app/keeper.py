from __future__ import annotations

from datetime import datetime

from pathlib import Path

from app.models import ActionCall, I18NText, KeeperOutput, MessageType

# Deprecated: Stub Keeper is kept for reference only. Use LLM Keeper instead.


PROMPT_PATH = Path(__file__).resolve().parent / "keeper_prompt_zh.txt"


class KeeperStub:
    def generate(self, action_text: I18NText, player_id: str, context_text: str = "") -> KeeperOutput:
        prompt = PROMPT_PATH.read_text(encoding="utf-8") if PROMPT_PATH.exists() else ""
        text = (action_text.zh or action_text.en or "").lower()
        actions: list[ActionCall] = []
        if "roll" in text or "掷骰" in text or "检定" in text:
            actions.append(
                ActionCall(
                    function_name="roll_dice",
                    parameters={
                        "dice_expression": "1d100",
                        "reason": "General check",
                        "actor_id": player_id,
                    },
                )
            )
            content = I18NText(
                zh="你尝试检定，命运即将揭晓。",
                en="You attempt a check; fate is about to be revealed.",
            )
        else:
            content = I18NText(
                zh="Keeper 记录了你的行动，房间的气氛微妙变化。",
                en="The Keeper notes your action; the room's mood subtly shifts.",
            )
        return KeeperOutput(
            message_type=MessageType.public,
            visible_to=["all"],
            content=content,
            actions=actions,
            notes=(
                f"stubbed at {datetime.utcnow().isoformat()}Z | "
                f"prompt_len={len(prompt)} | ctx_len={len(context_text)}"
            ),
        )
