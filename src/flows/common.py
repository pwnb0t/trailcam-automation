from __future__ import annotations

from pathlib import Path

from src.command.path_utils import camera_media_root
from src.session import TrailCamSession


def _media_dir_path(out_root: str, dir_num: int) -> Path:
    # Stable NAS-friendly layout: out/media/<dirNum>/...
    p = Path(out_root) / str(int(dir_num))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _media_file_path(out_root: str, dir_num: int, media_num: int, file_type: int) -> Path:
    d = _media_dir_path(out_root, dir_num)
    ext = ".mp4" if int(file_type) == 1 else ".jpg"
    return d / f"media{int(media_num):04d}{ext}"


def _session_media_root(session: TrailCamSession) -> str:
    return camera_media_root(str(session.cfg.paths.staging_dir), str(session.cfg.camera.alias))
