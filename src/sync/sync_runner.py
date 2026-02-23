from __future__ import annotations

import asyncio
import shutil
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from src.command.format_sd_card_command import FormatSdCardCommand
from src.command.path_utils import camera_media_root, media_file_path
from src.config import ClientConfig, PathsConfig, RunnerConfig
from src.connection.connection import connect_and_login
from src.flows import download_photo_to_out_item, send_video_download_flow_item
from src.notify.email_notifier import EmailNotifier
from src.sync.sync_config import SyncConfig
from src.sync.manifest import build_staging_manifest, build_trailcam_manifest, compute_missing
from src.sync.organize import organize_one
from src.sync.status import SyncStatus
from src.sync.sync_state import MediaKey, SyncStateStore


def _run_id_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


class SyncRunner:
    def __init__(
        self,
        cfg: SyncConfig,
        state_store: SyncStateStore,
    ):
        if cfg.app_cfg is None:
            raise ValueError("SyncRunner requires cfg.app_cfg in non-status mode")
        self.cfg = cfg
        self.app_cfg = cfg.app_cfg
        self.state_store = state_store
        self.final_media_dir = Path(cfg.final_media_dir)
        self.dupes_dir = Path(cfg.dupes_dir)
        self.notifier: Optional[EmailNotifier] = cfg.notifier
        self.debug = bool(cfg.debug)
        self.dry_run = bool(cfg.dry_run)
        self.stage_only = bool(cfg.stage_only)

    async def run_all(self) -> bool:
        aliases = sorted(self.app_cfg.cameras.keys())
        all_ok = True
        for alias in aliases:
            try:
                await self.run_camera(alias)
            except Exception as e:
                all_ok = False
                print(f"[{alias}] failed: {e}")
                if self.notifier is not None:
                    try:
                        self.notifier.send_failure(
                            camera_alias=alias,
                            error=str(e),
                            details=traceback.format_exc(),
                        )
                    except Exception as notify_err:
                        print(f"[{alias}] failure email send failed: {notify_err}")
        return all_ok

    async def run_camera(self, alias: str) -> None:
        cam = self.app_cfg.get_camera(alias)
        state = self.state_store.load()
        state["run_id_last"] = _run_id_now()
        cam_state = self.state_store.ensure_camera_state(state, alias)
        if str(cam_state.get("status", "")).lower() == SyncStatus.DONE.value:
            print(f"[{alias}] status=done in state file; skipping")
            self.state_store.save(state)
            return
        self.state_store.save(state)
        cfg = RunnerConfig(
            camera=cam,
            client=self._client_cfg(),
            paths=self._paths_cfg(),
            op="sync",
            debug=self.debug,
        )

        print(f"[{alias}] connect/login ...")
        session = await connect_and_login(cfg)
        try:
            cam_state["battery_percent"] = session.battery_percent
            if session.battery_percent is None:
                print(f"[{alias}] battery_percent=unknown")
            else:
                print(f"[{alias}] battery_percent={session.battery_percent}")
            cam_state["status"] = SyncStatus.DOWNLOAD.value
            self.state_store.save(state)

            trailcam_manifest: Optional[Dict[MediaKey, Dict[str, Any]]] = None
            while True:
                trailcam_manifest = build_trailcam_manifest(session)
                staging_manifest = build_staging_manifest(session)
                missing = compute_missing(trailcam_manifest, staging_manifest)
                print(
                    f"[{alias}] download-check: trailcam={len(trailcam_manifest)} staged={len(staging_manifest)} missing={len(missing)}"
                )
                if not missing:
                    break
                await self._download_missing(
                    state=state,
                    session=session,
                    alias=alias,
                    cam_state=cam_state,
                    missing=missing,
                )

            cam_state["status"] = SyncStatus.VERIFY.value
            self.state_store.save(state)

            # Verify: full rebuild of both manifests; if mismatch, loop back to download.
            while True:
                trailcam_manifest = build_trailcam_manifest(session)
                staging_manifest = build_staging_manifest(session)
                missing = compute_missing(trailcam_manifest, staging_manifest)
                print(f"[{alias}] verify: trailcam={len(trailcam_manifest)} staged={len(staging_manifest)} missing={len(missing)}")
                if not missing:
                    break
                cam_state["status"] = SyncStatus.DOWNLOAD.value
                self.state_store.save(state)
                await self._download_missing(
                    state=state,
                    session=session,
                    alias=alias,
                    cam_state=cam_state,
                    missing=missing,
                )
                cam_state["status"] = SyncStatus.VERIFY.value
                self.state_store.save(state)

            if self.stage_only:
                cam_state["status"] = SyncStatus.STAGED.value
                self.state_store.save(state)
                print(f"[{alias}] stage-only: leaving files in staging, skipping clear/organize")
                return

            cam_state["status"] = SyncStatus.CLEAR.value
            self.state_store.save(state)
            if self.dry_run:
                print(f"[{alias}] dry-run: skipping clear")
            else:
                print(f"[{alias}] clear: delete media all (format)")
                FormatSdCardCommand(session).run()

            cam_state["status"] = SyncStatus.ORGANIZE.value
            self.state_store.save(state)
            self._organize_staging(
                state=state,
                session=session,
                alias=alias,
                cam_state=cam_state,
                trailcam_manifest=trailcam_manifest or {},
            )

            cam_state["status"] = SyncStatus.DONE.value
            self.state_store.save(state)
            print(f"[{alias}] done")
        except Exception as e:
            cam_state["status"] = SyncStatus.ERROR.value
            cam_state.setdefault("errors", []).append(str(e))
            self.state_store.save(state)
            raise
        finally:
            try:
                session.client.close()
            except Exception:
                pass

    def _client_cfg(self) -> ClientConfig:
        c = self.app_cfg.client
        return ClientConfig(
            wifi_ifname=c.wifi_ifname,
            bluetooth_adapter=c.bluetooth_adapter,
            udp_local_port=c.udp_local_port,
            page_no=c.page_no,
            page_item_cnt=c.page_item_cnt,
            list_max_pages=c.list_max_pages,
            download_listen_s=c.download_listen_s,
            download_idle_s=c.download_idle_s,
            photo_download_retries=c.photo_download_retries,
            video_fps=c.video_fps,
            strict_video=c.strict_video,
        )

    def _paths_cfg(self) -> PathsConfig:
        p = self.app_cfg.paths
        return PathsConfig(staging_dir=p.staging_dir, tmp_dir=p.tmp_dir, final_media_dir=p.final_media_dir)

    @staticmethod
    def _state_key(key: MediaKey) -> str:
        return key.as_state_key()

    @staticmethod
    def _cleanup_tmp_for_alias(session_alias: str, tmp_root: str) -> None:
        base = Path(tmp_root)
        alias_dir = base / session_alias
        alias_dir.mkdir(parents=True, exist_ok=True)
        for child in alias_dir.iterdir():
            if child.is_file():
                child.unlink(missing_ok=True)
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)

    async def _download_missing(
        self,
        *,
        state: Dict[str, Any],
        session,
        alias: str,
        cam_state: Dict[str, Any],
        missing: list[MediaKey],
    ) -> None:
        self._cleanup_tmp_for_alias(alias, str(session.cfg.paths.tmp_dir))
        downloaded = cam_state.setdefault("downloaded", {})
        out_root = camera_media_root(str(session.cfg.paths.staging_dir), alias)

        for idx, key in enumerate(missing, start=1):
            skey = self._state_key(key)
            print(
                f"[{alias}] download {idx}/{len(missing)} dir={key.dir_num} media={key.media_num} fileType={key.file_type}"
            )
            first_seen = downloaded.get(skey, {}).get("first_seen_at")
            if not first_seen:
                first_seen = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

            if key.file_type == 0:
                retries = max(1, int(session.cfg.client.photo_download_retries))
                out_path = None
                for attempt in range(1, retries + 1):
                    out = download_photo_to_out_item(session, key.dir_num, key.media_num)
                    if out is not None and out.exists() and out.stat().st_size > 0:
                        out_path = out
                        break
                    print(
                        f"[{alias}] photo retry {attempt}/{retries} failed dir={key.dir_num} media={key.media_num}"
                    )
                    if attempt < retries:
                        time.sleep(0.6)
                if out_path is None:
                    raise RuntimeError(
                        f"Photo download failed after {retries} attempts dir={key.dir_num} media={key.media_num}"
                    )
            else:
                out_path = Path(media_file_path(out_root, key.dir_num, key.media_num, key.file_type))
                send_video_download_flow_item(session, key.dir_num, key.media_num, out_mp4_path=str(out_path))

            if not out_path.exists() or out_path.stat().st_size <= 0:
                raise RuntimeError(f"Downloaded file missing/empty: {out_path}")

            downloaded[skey] = {
                "staged_path": str(out_path),
                "size": int(out_path.stat().st_size),
                "first_seen_at": first_seen,
            }
            self.state_store.save(state)
            # Avoid hot-looping event loop on long blocking calls.
            await asyncio.sleep(0)

    def _organize_staging(
        self,
        *,
        state: Dict[str, Any],
        session,
        alias: str,
        cam_state: Dict[str, Any],
        trailcam_manifest: Dict[MediaKey, Dict[str, Any]],
    ) -> None:
        self.final_media_dir.mkdir(parents=True, exist_ok=True)
        self.dupes_dir.mkdir(parents=True, exist_ok=True)
        staging_manifest = build_staging_manifest(session)
        downloaded = cam_state.setdefault("downloaded", {})
        organized = cam_state.setdefault("organized", {})
        run_id = _run_id_now()

        for key, staged_path in sorted(staging_manifest.items(), key=lambda kv: (kv[0].dir_num, kv[0].media_num, kv[0].file_type)):
            skey = self._state_key(key)
            first_seen = downloaded.get(skey, {}).get("first_seen_at")
            meta = trailcam_manifest.get(key)
            if self.dry_run:
                print(f"[{alias}] dry-run organize dir={key.dir_num} media={key.media_num} fileType={key.file_type}")
                continue
            res = organize_one(
                alias=alias,
                key=key,
                staged_path=staged_path,
                meta=meta,
                first_seen_at=first_seen,
                final_root=self.final_media_dir,
                dupes_root=self.dupes_dir,
                run_id=run_id,
                week_boundary_weekday=int(self.app_cfg.organize.week_boundary_weekday),
                week_boundary_hour_local=int(self.app_cfg.organize.week_boundary_hour_local),
                media_time_mode=str(self.app_cfg.organize.media_time_mode),
            )
            organized[skey] = res
            self.state_store.save(state)
