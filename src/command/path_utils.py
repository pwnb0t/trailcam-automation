from __future__ import annotations

from pathlib import Path


def media_file_path(out_root: str, dir_num: int, media_num: int, file_type: int) -> str:
    """Stable NAS-friendly layout: out/media/<dirNum>/media####.<ext>"""
    ext = ".mp4" if int(file_type) == 1 else ".jpg"
    p = Path(out_root) / str(int(dir_num))
    p.mkdir(parents=True, exist_ok=True)
    return str(p / f"media{int(media_num):04d}{ext}")

