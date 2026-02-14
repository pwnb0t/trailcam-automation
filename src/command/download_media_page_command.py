from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from src.flows import (
    download_photo_to_out,
    fetch_media_list_page,
    send_video_download_flow,
)
from src.session import TrailCamSession
from src.command.command import Command, CommandError


def _media_file_path(out_root: str, dir_num: int, media_num: int, file_type: int) -> str:
    # Stable NAS-friendly layout: out/media/<dirNum>/media####.<ext>
    ext = ".mp4" if int(file_type) == 1 else ".jpg"
    p = Path(out_root) / str(int(dir_num))
    p.mkdir(parents=True, exist_ok=True)
    return str(p / f"media{int(media_num):04d}{ext}")


@dataclass
class DownloadMediaPageCommand(Command):
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
        s = self.session
        client = s.client
        token = int(s.login_token_u32)
        page_no = int(s.defaults.page_no)
        item_cnt_per_page = int(s.defaults.page_item_cnt)
        out_root = str(s.paths.media_out_dir)
        temp_root = str(s.paths.tmp_dir)
        listen_s = float(s.defaults.download_listen_s)
        idle_break_s = float(s.defaults.download_idle_s)
        video_fps = int(s.defaults.video_fps)
        debug = bool(getattr(s, "debug", False))

        # Camera returns an error if itemCntPerPage >= 50 ("need less than 50").
        if item_cnt_per_page >= 50:
            item_cnt_per_page = 45

        entries = fetch_media_list_page(
            client,
            token,
            page_no=page_no,
            item_cnt_per_page=item_cnt_per_page,
            debug=debug,
        )
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
            out_path = download_photo_to_out(
                client,
                token,
                dir_num=dir_num,
                media_num=media_num,
                out_root=out_root,
                listen_s=listen_s,
                idle_break_s=idle_break_s,
                temp_root=temp_root,
                debug=debug,
            )
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
            out_mp4 = _media_file_path(out_root, dir_num, media_num, file_type=1)
            print(f"[video {idx}/{len(videos)}] dir={dir_num} media={media_num}")
            send_video_download_flow(
                client,
                token,
                dir_num=dir_num,
                media_num=media_num,
                file_type=1,
                fps=video_fps,
                listen_s=listen_s,
                idle_break_s=idle_break_s,
                out_mp4_path=str(out_mp4),
                temp_root=temp_root,
                debug=debug,
            )
            results.append(
                {
                    "kind": "video",
                    "dirNum": dir_num,
                    "mediaNum": media_num,
                    "path": str(out_mp4),
                }
            )

        return results
