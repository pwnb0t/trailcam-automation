from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from src.flows import (
    download_photo_to_out_item,
    fetch_media_list_page,
    send_video_download_flow_item,
)
from src.session import TrailCamSession
from src.command.command import Command, CommandError
from src.command.path_utils import media_file_path


@dataclass
class DownloadMediaPageCommand(Command):
    session: TrailCamSession

    def validate(self) -> None:
        s = self.session
        if s.client is None:
            raise CommandError("session.client is required")
        if not isinstance(s.login_token_u32, int) or s.login_token_u32 <= 0:
            raise CommandError("session.login_token_u32 must be a positive int")
        if not s.cfg.paths.media_out_dir:
            raise CommandError("session.cfg.paths.media_out_dir is required")
        if not s.cfg.paths.tmp_dir:
            raise CommandError("session.cfg.paths.tmp_dir is required")
        if int(s.cfg.client.page_item_cnt) >= 50:
            raise CommandError("session.cfg.client.page_item_cnt must be < 50 (camera rejects >= 50)")

    def run(self) -> List[Dict[str, Any]]:
        self.validate()
        s = self.session
        page_no = int(s.cfg.client.page_no)
        out_root = str(s.cfg.paths.media_out_dir)
        entries = fetch_media_list_page(s)
        if not entries:
            print("No media entries found on requested page.")
            return []

        photos = [e for e in entries if int(e.get("fileType", 0)) == 0]
        videos = [e for e in entries if int(e.get("fileType", 0)) == 1]

        results: List[Dict[str, Any]] = []
        if photos:
            print(f"Downloading {len(photos)} photo(s) from page {page_no} into {out_root} ...")
        for idx, entry in enumerate(photos, start=1):
            dir_num = int(entry["dirNum"])
            media_num = int(entry["mediaNum"])
            print(f"[photo {idx}/{len(photos)}] dir={dir_num} media={media_num}")
            out_path = download_photo_to_out_item(s, dir_num, media_num)
            results.append(
                {
                    "kind": "photo",
                    "dirNum": dir_num,
                    "mediaNum": media_num,
                    "path": str(out_path) if out_path else None,
                }
            )

        if videos:
            print(f"Downloading {len(videos)} video(s) from page {page_no} into {out_root} ...")
        for idx, entry in enumerate(videos, start=1):
            dir_num = int(entry["dirNum"])
            media_num = int(entry["mediaNum"])
            out_mp4 = media_file_path(out_root, dir_num, media_num, file_type=1)
            print(f"[video {idx}/{len(videos)}] dir={dir_num} media={media_num}")
            send_video_download_flow_item(s, dir_num, media_num, out_mp4_path=str(out_mp4))
            results.append(
                {
                    "kind": "video",
                    "dirNum": dir_num,
                    "mediaNum": media_num,
                    "path": str(out_mp4),
                }
            )

        return results
