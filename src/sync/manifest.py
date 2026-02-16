from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

from src.command.list_media_all_command import ListMediaAllCommand
from src.command.path_utils import camera_media_root
from src.session import TrailCamSession
from src.sync.sync_state import MediaKey


_MEDIA_RE = re.compile(r"^media(?P<num>\d{4})\.(?P<ext>jpg|mp4)$", re.IGNORECASE)


def camera_staging_root(session: TrailCamSession) -> Path:
    return Path(camera_media_root(str(session.cfg.paths.staging_dir), str(session.cfg.camera.alias)))


def build_staging_manifest(session: TrailCamSession) -> Dict[MediaKey, Path]:
    root = camera_staging_root(session)
    out: Dict[MediaKey, Path] = {}
    if not root.exists():
        return out

    for dir_entry in root.iterdir():
        if not dir_entry.is_dir():
            continue
        try:
            dir_num = int(dir_entry.name)
        except ValueError:
            continue
        for file_entry in dir_entry.iterdir():
            if not file_entry.is_file():
                continue
            m = _MEDIA_RE.match(file_entry.name)
            if not m:
                continue
            media_num = int(m.group("num"))
            ext = m.group("ext").lower()
            file_type = 1 if ext == "mp4" else 0
            out[MediaKey(dir_num=dir_num, media_num=media_num, file_type=file_type)] = file_entry
    return out


def build_trailcam_manifest(session: TrailCamSession) -> Dict[MediaKey, Dict[str, Any]]:
    entries = ListMediaAllCommand(session).run()
    out: Dict[MediaKey, Dict[str, Any]] = {}
    for e in entries:
        key = MediaKey(
            dir_num=int(e["dirNum"]),
            media_num=int(e["mediaNum"]),
            file_type=int(e.get("fileType", 0)),
        )
        out[key] = dict(e)
    return out


def compute_missing(
    trailcam_manifest: Dict[MediaKey, Dict[str, Any]],
    staging_manifest: Dict[MediaKey, Path],
) -> list[MediaKey]:
    missing = [k for k in trailcam_manifest if k not in staging_manifest]
    missing.sort(key=lambda k: (k.dir_num, k.media_num, k.file_type), reverse=True)
    return missing

