from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from src.command.command import Command, CommandError
from src.command.path_utils import media_file_path
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
        out_mp4 = str(s.target_video_out or "").strip()
        if not out_mp4:
            out_mp4 = media_file_path(str(s.paths.media_out_dir), dir_num, media_num, file_type=1)

        send_video_download_flow(
            s.client,
            s.login_token_u32,
            dir_num=dir_num,
            media_num=media_num,
            file_type=1,
            fps=int(s.defaults.video_fps),
            listen_s=float(s.defaults.download_listen_s),
            idle_break_s=float(s.defaults.download_idle_s),
            out_mp4_path=str(out_mp4),
            temp_root=str(s.paths.tmp_dir),
            debug=bool(s.debug),
        )
        return {"kind": "video", "dirNum": dir_num, "mediaNum": media_num, "path": str(out_mp4)}

