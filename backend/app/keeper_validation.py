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

    return errors
