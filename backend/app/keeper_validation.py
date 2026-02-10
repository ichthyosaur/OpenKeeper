from __future__ import annotations

from typing import List

from app.models import KeeperOutput, MessageType


def validate_keeper_output(output: KeeperOutput) -> List[str]:
    errors: list[str] = []

    if output.message_type == MessageType.public:
        if output.visible_to != ["all"]:
            errors.append("public message must have visible_to = ['all']")

    if output.message_type == MessageType.secret:
        if not output.visible_to:
            errors.append("secret message must have visible_to")
        if "all" in output.visible_to:
            errors.append("secret message cannot include 'all' in visible_to")

    if output.message_type == MessageType.system:
        if not output.visible_to:
            errors.append("system message must have visible_to")

    # Basic sanity checks
    if output.content is None:
        errors.append("content is required")

    for action in output.actions:
        params = action.parameters or {}
        if action.function_name in ("apply_damage", "apply_sanity_change"):
            if "amount" not in params:
                errors.append(f"{action.function_name} requires amount")
            elif not isinstance(params.get("amount"), int):
                errors.append(f"{action.function_name} amount must be int")
        if action.function_name == "update_player_attribute":
            if "delta" not in params:
                errors.append("update_player_attribute requires delta")
            elif not isinstance(params.get("delta"), int):
                errors.append("update_player_attribute delta must be int")
        if action.function_name == "end_module":
            if "ending_id" not in params or "description" not in params:
                errors.append("end_module requires ending_id and description")

    return errors
