from __future__ import annotations

from pathlib import Path


def camera_media_root(out_root: str, camera_alias: str) -> str:
    """Per-camera output root: <out_root>/<alias>."""
    p = Path(out_root) / str(camera_alias)
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def media_file_path(out_root: str, dir_num: int, media_num: int, file_type: int) -> str:
    """Stable NAS-friendly layout: out/media/<dirNum>/media####.<ext>"""
    ext = ".mp4" if int(file_type) == 1 else ".jpg"
    p = Path(out_root) / str(int(dir_num))
    p.mkdir(parents=True, exist_ok=True)
    return str(p / f"media{int(media_num):04d}{ext}")
