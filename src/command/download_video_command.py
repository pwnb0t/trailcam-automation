from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from src.command.command import Command, CommandError
from src.flows import send_video_download_flow
from src.session import TrailCamSession


@dataclass
class DownloadVideoCommand(Command):
    session: TrailCamSession

    def validate(self) -> None:
        s = self.session
        if s.client is None:
            raise CommandError("session.client is required")
        if not isinstance(s.login_token_u32, int) or s.login_token_u32 <= 0:
            raise CommandError("session.login_token_u32 must be a positive int")
        if s.target_dir_num is None or s.target_media_num is None:
            raise CommandError("session.target_dir_num and session.target_media_num are required")
        if not s.paths.media_out_dir:
            raise CommandError("session.paths.media_out_dir is required")
        if not s.paths.tmp_dir:
            raise CommandError("session.paths.tmp_dir is required")

    def run(self) -> Dict[str, Any]:
        self.validate()
        s = self.session
        dir_num = int(s.target_dir_num)
        media_num = int(s.target_media_num)
        res = send_video_download_flow(s)
        out_mp4 = str(res.get("out_mp4") or "")
        return {"kind": "video", "dirNum": dir_num, "mediaNum": media_num, "path": out_mp4}
