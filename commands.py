from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from flows import download_media_page
from session import TrailCamSession


class CommandError(RuntimeError):
    pass


@dataclass
class DownloadMediaPageCommand:
    session: TrailCamSession

    def validate(self) -> None:
        s = self.session
        if s.client is None:
            raise CommandError("session.client is required")
        if not isinstance(s.login_token_u32, int) or s.login_token_u32 <= 0:
            raise CommandError("session.login_token_u32 must be a positive int")
        if not s.paths.media_out_dir:
            raise CommandError("session.paths.media_out_dir is required")
        if not s.paths.tmp_dir:
            raise CommandError("session.paths.tmp_dir is required")
        if int(s.defaults.page_item_cnt) >= 50:
            raise CommandError("session.defaults.page_item_cnt must be < 50 (camera rejects >= 50)")

    def run(self) -> List[Dict[str, Any]]:
        self.validate()
        return download_media_page(self.session)
