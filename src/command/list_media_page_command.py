from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from src.command.command import Command, CommandError
from src.flows import fetch_media_list_page
from src.session import TrailCamSession


@dataclass
class ListMediaPageCommand(Command):
    session: TrailCamSession

    def validate(self) -> None:
        s = self.session
        if s.client is None:
            raise CommandError("session.client is required")
        if not isinstance(s.login_token_u32, int) or s.login_token_u32 <= 0:
            raise CommandError("session.login_token_u32 must be a positive int")
        if int(s.cfg.client.page_item_cnt) >= 50:
            raise CommandError("session.cfg.client.page_item_cnt must be < 50 (camera rejects >= 50)")

    def run(self) -> List[Dict[str, Any]]:
        self.validate()
        s = self.session
        return fetch_media_list_page(s)
