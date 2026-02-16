from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.command.command import Command, CommandError
from src.command.path_utils import camera_media_root, media_file_path
from src.flows import (
    fetch_media_list_page,
    download_photo_to_out_item,
    send_video_download_flow_item,
)
from src.session import TrailCamSession


@dataclass
class DownloadSingleCommand(Command):
    session: TrailCamSession

    def validate(self) -> None:
        s = self.session
        if s.client is None:
            raise CommandError("session.client is required")
        if not isinstance(s.login_token_u32, int) or s.login_token_u32 <= 0:
            raise CommandError("session.login_token_u32 must be a positive int")
        if s.cfg.media_num is None:
            raise CommandError("session.cfg.media_num is required")
        if s.cfg.dir_num is None:
            raise CommandError("session.cfg.dir_num is required")
        if int(s.cfg.client.page_item_cnt) >= 50:
            raise CommandError("session.cfg.client.page_item_cnt must be < 50 (camera rejects >= 50)")

    def _find_entry(self) -> Optional[Dict[str, Any]]:
        s = self.session
        want_dir = int(s.cfg.dir_num)
        want_media = int(s.cfg.media_num)
        max_pages = int(s.cfg.client.list_max_pages)
        item_cnt = int(s.cfg.client.page_item_cnt)

        for page_no in range(0, max_pages):
            entries = fetch_media_list_page(s, page_no=page_no, item_cnt_per_page=item_cnt)
            for e in entries:
                if int(e.get("dirNum", -1)) == want_dir and int(e.get("mediaNum", -1)) == want_media:
                    return e
        return None

    def run(self) -> Dict[str, Any]:
        self.validate()
        s = self.session
        entry = self._find_entry()
        if not entry:
            raise CommandError(
                f"Media not found in list: dir={int(s.cfg.dir_num)} media={int(s.cfg.media_num)} "
                f"(searched up to list_max_pages={int(s.cfg.client.list_max_pages)})"
            )

        file_type = int(entry.get("fileType", 0))
        dir_num = int(entry["dirNum"])
        media_num = int(entry["mediaNum"])

        if file_type == 0:
            out_path = download_photo_to_out_item(s, dir_num, media_num)
            return {"kind": "photo", "dirNum": dir_num, "mediaNum": media_num, "path": str(out_path) if out_path else None}

        if file_type == 1:
            out_mp4 = str(s.cfg.video_out or "").strip()
            if not out_mp4:
                out_root = camera_media_root(str(s.cfg.paths.staging_dir), str(s.cfg.camera.alias))
                out_mp4 = media_file_path(out_root, dir_num, media_num, file_type=1)
            send_video_download_flow_item(s, dir_num, media_num, out_mp4_path=out_mp4)
            return {"kind": "video", "dirNum": dir_num, "mediaNum": media_num, "path": str(out_mp4)}

        raise CommandError(f"Unknown fileType={file_type} for dir={dir_num} media={media_num}")
