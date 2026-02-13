#!/usr/bin/env python3
import re
import shutil
from pathlib import Path


DIR_RE = re.compile(r"^dir(\d+)$")
MEDIA_RE = re.compile(r"^media(\d+)\.(jpg|mp4)$", re.IGNORECASE)


def migrate_media_root(root: Path) -> None:
    media_root = root / "out" / "media"
    tmp_root = root / "out" / "tmp" / "media_dumps"
    if not media_root.exists():
        print(f"Nothing to do: {media_root} does not exist")
        return

    tmp_root.mkdir(parents=True, exist_ok=True)

    for child in sorted(media_root.iterdir()):
        if not child.is_dir():
            continue
        m = DIR_RE.match(child.name)
        if not m:
            continue
        dir_num = int(m.group(1))
        new_dir = media_root / str(dir_num)
        new_dir.mkdir(parents=True, exist_ok=True)

        # Move stable files at the top-level (mediaNNN.jpg/mp4) to zero-padded names.
        for p in sorted(child.iterdir()):
            if p.is_file():
                m2 = MEDIA_RE.match(p.name)
                if not m2:
                    continue
                media_num = int(m2.group(1))
                ext = m2.group(2).lower()
                dst = new_dir / f"media{media_num:04d}.{ext}"
                if dst.exists():
                    # Prefer keeping the larger file if both exist.
                    try:
                        if p.stat().st_size > dst.stat().st_size:
                            dst.unlink()
                            shutil.move(str(p), str(dst))
                        else:
                            p.unlink()
                    except Exception:
                        pass
                else:
                    shutil.move(str(p), str(dst))

        # Move per-media dump directories into out/tmp/media_dumps/<dir>/<media####>/
        for p in sorted(child.iterdir()):
            if not p.is_dir():
                continue
            if not p.name.startswith("media"):
                continue
            m3 = re.match(r"^media(\d+)$", p.name)
            if not m3:
                continue
            media_num = int(m3.group(1))
            dst = tmp_root / str(dir_num) / f"media{media_num:04d}"
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                # Merge by moving contents; avoid losing anything.
                for sub in p.iterdir():
                    target = dst / sub.name
                    if target.exists():
                        continue
                    shutil.move(str(sub), str(target))
                try:
                    p.rmdir()
                except Exception:
                    pass
            else:
                shutil.move(str(p), str(dst))

        # Remove the old dirNNN folder if empty.
        try:
            next(child.iterdir())
        except StopIteration:
            child.rmdir()


if __name__ == "__main__":
    migrate_media_root(Path.cwd())

