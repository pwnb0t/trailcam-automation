from __future__ import annotations

import hashlib
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from src.sync.sync_state import MediaKey


def _parse_media_time_unix(value: Any, *, mode: str = "local_epoch") -> Optional[datetime]:
    try:
        ts = int(value)
    except Exception:
        return None
    if mode == "utc_epoch":
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
    else:
        # Camera reports mediaTime as epoch-like value tied to local wall-clock.
        dt = datetime.fromtimestamp(ts).astimezone()
    if dt.year < 2018 or dt.year > 2100:
        return None
    return dt


def _extract_jpg_embedded_time(path: Path) -> Optional[datetime]:
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS
    except Exception:
        return None
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            if not exif:
                return None
            tag_map = {TAGS.get(k, str(k)): v for k, v in exif.items()}
            raw = tag_map.get("DateTimeOriginal") or tag_map.get("DateTime")
            if not raw:
                return None
            dt = datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S")
            return dt.astimezone()
    except Exception:
        return None


def _extract_mp4_embedded_time(path: Path) -> Optional[datetime]:
    # Best-effort: ffprobe if available.
    try:
        p = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format_tags=creation_time",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            text=True,
            capture_output=True,
        )
    except Exception:
        return None
    if p.returncode != 0:
        return None
    val = (p.stdout or "").strip()
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        return dt.astimezone()
    except Exception:
        return None


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso_utc(s: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone()
    except Exception:
        return None


def _week_bucket_label(dt_local: datetime, *, boundary_weekday: int, boundary_hour_local: int) -> str:
    # Buckets are ISO year-week labels, but with a configurable rollover moment.
    # Before rollover on the boundary weekday, keep the current ISO week.
    # At/after rollover on the boundary weekday, advance to the *next* ISO week.
    #
    # Example with Sunday 11:00:
    # - Sun 10:59 -> current ISO week
    # - Sun 11:00+ -> next ISO week
    wkday = dt_local.weekday()
    shifted = dt_local

    if wkday == int(boundary_weekday):
        boundary = dt_local.replace(hour=int(boundary_hour_local), minute=0, second=0, microsecond=0)
        if dt_local >= boundary:
            # Advance to next Monday so isocalendar() reports the next ISO week.
            days_to_next_monday = (7 - wkday) % 7
            if days_to_next_monday == 0:
                days_to_next_monday = 7
            shifted = dt_local + timedelta(days=days_to_next_monday)

    iso = shifted.isocalendar()
    return f"{iso.year:04d}-{iso.week:02d}"


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _same_content(a: Path, b: Path) -> bool:
    if a.stat().st_size != b.stat().st_size:
        return False
    return _hash_file(a) == _hash_file(b)


@dataclass(frozen=True)
class OrganizeDecision:
    when_local: datetime
    ts_source: str  # mediaTime|embedded|first_seen_at


def choose_timestamp(
    *,
    key: MediaKey,
    meta: Optional[Dict[str, Any]],
    staged_path: Path,
    first_seen_at: Optional[str],
    media_time_mode: str = "local_epoch",
) -> Tuple[OrganizeDecision, str]:
    if meta:
        dt = _parse_media_time_unix(meta.get("mediaTime"), mode=media_time_mode)
        if dt is not None:
            return OrganizeDecision(when_local=dt, ts_source="mediaTime"), (first_seen_at or _iso_now())

    embedded = _extract_mp4_embedded_time(staged_path) if key.file_type == 1 else _extract_jpg_embedded_time(staged_path)
    if embedded is not None:
        return OrganizeDecision(when_local=embedded, ts_source="embedded"), (first_seen_at or _iso_now())

    if first_seen_at:
        dt = _parse_iso_utc(first_seen_at)
        if dt is not None:
            return OrganizeDecision(when_local=dt, ts_source="first_seen_at"), first_seen_at

    now_iso = _iso_now()
    dt_now = _parse_iso_utc(now_iso)
    assert dt_now is not None
    return OrganizeDecision(when_local=dt_now, ts_source="first_seen_at"), now_iso


def final_filename(alias: str, key: MediaKey, when_local: datetime) -> str:
    ts = when_local.strftime("%Y-%m-%d_%H-%M-%S")
    ext = "mp4" if key.file_type == 1 else "jpg"
    return f"{ts}_{alias}.{ext}"


def organize_one(
    *,
    alias: str,
    key: MediaKey,
    staged_path: Path,
    meta: Optional[Dict[str, Any]],
    first_seen_at: Optional[str],
    final_root: Path,
    dupes_root: Path,
    run_id: str,
    week_boundary_weekday: int = 6,
    week_boundary_hour_local: int = 8,
    media_time_mode: str = "local_epoch",
) -> Dict[str, Any]:
    decision, first_seen = choose_timestamp(
        key=key,
        meta=meta,
        staged_path=staged_path,
        first_seen_at=first_seen_at,
        media_time_mode=media_time_mode,
    )
    bucket = _week_bucket_label(
        decision.when_local,
        boundary_weekday=int(week_boundary_weekday),
        boundary_hour_local=int(week_boundary_hour_local),
    )
    dst_dir = final_root / bucket
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / final_filename(alias, key, decision.when_local)

    if dst.exists():
        if _same_content(staged_path, dst):
            staged_path.unlink(missing_ok=True)
            return {
                "action": "already_present",
                "final_path": str(dst),
                "first_seen_at": first_seen,
                "final_ts_source": decision.ts_source,
            }
        dupe_dir = dupes_root / run_id / alias / str(key.dir_num)
        dupe_dir.mkdir(parents=True, exist_ok=True)
        dupe_path = dupe_dir / staged_path.name
        shutil.move(str(staged_path), str(dupe_path))
        return {
            "action": "dupe_conflict",
            "final_path": str(dst),
            "dupe_path": str(dupe_path),
            "first_seen_at": first_seen,
            "final_ts_source": decision.ts_source,
        }

    shutil.move(str(staged_path), str(dst))
    return {
        "action": "moved",
        "final_path": str(dst),
        "first_seen_at": first_seen,
        "final_ts_source": decision.ts_source,
    }
