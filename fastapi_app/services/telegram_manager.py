from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

from apps.scouting.models import Patrol


@dataclass
class TelegramNodeResult:
    ok: bool
    invite_link: str
    reason: str = ""
    total_patrols: int = 0
    total_members: int = 0


class TelegramManager:
    """
    Helper for dynamic multi-patrol node bootstrap.

    Note: Telegram Bot API does not allow bots to create normal groups directly.
    This manager generates unique deep links and optional invite links to a pre-created hub chat.
    """

    def __init__(self) -> None:
        self.bot_username = os.getenv("TELEGRAM_BOT_USERNAME", "")
        self.shared_hub_chat_id = os.getenv("TELEGRAM_SHARED_HUB_CHAT_ID", "")

    def create_multi_patrol_node(self, patrols: list[Patrol]) -> TelegramNodeResult:
        if not patrols:
            return TelegramNodeResult(ok=False, invite_link="", reason="no_patrols")

        if len(patrols) > 3:
            return TelegramNodeResult(ok=False, invite_link="", reason="max_3_patrols")

        total_members = sum(max(0, int(p.member_count or 0)) for p in patrols)
        if total_members > 15:
            return TelegramNodeResult(ok=False, invite_link="", reason="max_15_members", total_members=total_members)

        seed = uuid.uuid4().hex[:20]
        deep_link = self._build_startgroup_link(seed)

        return TelegramNodeResult(
            ok=True,
            invite_link=deep_link,
            total_patrols=len(patrols),
            total_members=total_members,
        )

    def build_unique_patrol_link(self, patrol: Patrol) -> str:
        token = patrol.telegram_node_token or uuid.uuid4()
        return self._build_startgroup_link(token.hex[:20])

    def _build_startgroup_link(self, token_suffix: str) -> str:
        if self.bot_username:
            return f"https://t.me/{self.bot_username}?startgroup=ligilo_{token_suffix}"
        return f"https://t.me/share/url?url=ligilo-node-{token_suffix}"
