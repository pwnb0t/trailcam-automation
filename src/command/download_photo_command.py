from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from src.command.command import Command, CommandError
from src.flows import download_photo_to_out
from src.session import TrailCamSession


@dataclass
class DownloadPhotoCommand(Command):
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
        out_path = download_photo_to_out(s)
        return {
            "kind": "photo",
            "dirNum": int(s.target_dir_num),
            "mediaNum": int(s.target_media_num),
            "path": str(out_path) if out_path else None,
        }
