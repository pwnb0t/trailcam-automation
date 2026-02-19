from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from src.sync.status import SyncStatus

DEFAULT_STATUS = SyncStatus.PENDING.value


@dataclass(frozen=True)
class MediaKey:
    dir_num: int
    media_num: int
    file_type: int  # 0 photo, 1 video

    def as_state_key(self) -> str:
        return f"{int(self.dir_num)}:{int(self.media_num)}:{int(self.file_type)}"

    @classmethod
    def from_state_key(cls, key: str) -> "MediaKey":
        a, b, c = key.split(":", 2)
        return cls(dir_num=int(a), media_num=int(b), file_type=int(c))


def default_state() -> Dict[str, Any]:
    return {
        "version": 1,
        "run_id_last": "",
        "cameras": {},
    }


class SyncStateStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return default_state()
        raw = json.loads(self.path.read_text("utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid state file format: {self.path}")
        raw.setdefault("version", 1)
        raw.setdefault("run_id_last", "")
        raw.setdefault("cameras", {})
        return raw

    def save(self, state: Dict[str, Any]) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", "utf-8")
        tmp.replace(self.path)

    def rotate_if_exists(self, *, suffix: Optional[str] = None) -> Optional[Path]:
        """Rotate current state file to a timestamped path and remove the active file.

        Returns destination path if rotated, else None when no state file exists.
        """
        if not self.path.exists():
            return None
        stamp = suffix or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        base = self.path.with_name(f"{self.path.stem}.{stamp}{self.path.suffix}")
        dst = base
        n = 1
        while dst.exists():
            dst = self.path.with_name(f"{self.path.stem}.{stamp}.{n}{self.path.suffix}")
            n += 1
        self.path.replace(dst)
        return dst

    @staticmethod
    def ensure_camera_state(state: Dict[str, Any], alias: str) -> Dict[str, Any]:
        cameras = state.setdefault("cameras", {})
        cam = cameras.setdefault(
            alias,
            {
                "status": DEFAULT_STATUS,
                "downloaded": {},
                "organized": {},
                "errors": [],
            },
        )
        cam.setdefault("status", DEFAULT_STATUS)
        cam.setdefault("downloaded", {})
        cam.setdefault("organized", {})
        cam.setdefault("errors", [])
        return cam
