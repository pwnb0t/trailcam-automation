#!/usr/bin/env python3
import asyncio
from pathlib import Path

from connection import connect_and_login
from flows import (
    download_photo_to_out,
    fetch_media_list_all,
    fetch_media_list_page,
    send_video_download_flow,
)
from src.command.download_media_page_command import DownloadMediaPageCommand
from runner_inputs import parse_env_and_args_to_config


async def main():
    cfg = parse_env_and_args_to_config()
    session = await connect_and_login(cfg)
    print(f"Camera addr: {session.client.camera_addr}")
    print(f"Login token: {session.login_token_u32}")

    if cfg.op == "login_only":
        return

    if cfg.op == "download_photo":
        out_path = download_photo_to_out(
            session.client,
            session.login_token_u32,
            dir_num=int(cfg.dir_num),
            media_num=int(cfg.media_num),
            out_root=session.paths.media_out_dir,
            listen_s=session.defaults.download_listen_s,
            idle_break_s=session.defaults.download_idle_s,
            debug=session.debug,
        )
        print(f"Wrote photo: {out_path or 'none'}")
        return

    if cfg.op == "download_video":
        if cfg.video_out:
            out_mp4 = cfg.video_out
        else:
            out_mp4 = str(Path(session.paths.media_out_dir) / str(cfg.dir_num) / f"media{int(cfg.media_num):04d}.mp4")
        send_video_download_flow(
            session.client,
            session.login_token_u32,
            dir_num=int(cfg.dir_num),
            media_num=int(cfg.media_num),
            file_type=1,
            fps=session.defaults.video_fps,
            listen_s=session.defaults.download_listen_s,
            idle_break_s=session.defaults.download_idle_s,
            out_mp4_path=out_mp4,
            debug=session.debug,
        )
        return

    if cfg.op == "download_page":
        cmd = DownloadMediaPageCommand(session)
        results = cmd.run()
        print(f"Downloaded page results: {len(results)} item(s)")
        for r in results:
            kind = r.get("kind", "media")
            path = r.get("path")
            print(f"  {kind} dir={r.get('dirNum')} media={r.get('mediaNum')} path={path or 'none'}")
        return

    if cfg.op == "list_media_page":
        page = fetch_media_list_page(
            session.client,
            session.login_token_u32,
            page_no=session.defaults.page_no,
            item_cnt_per_page=session.defaults.page_item_cnt,
            debug=session.debug,
        )
        print(f"Media entries (page {session.defaults.page_no}): {len(page)}")
        for e in page:
            print(
                f"  dir={e.get('dirNum')} media={e.get('mediaNum')} fileType={e.get('fileType')} "
                f"name={e.get('fileName') or ''} time={e.get('mediaTime') or ''} durMs={e.get('durationMs') or ''}"
            )
        return

    if cfg.op == "list_media_all":
        all_entries = fetch_media_list_all(
            session.client,
            session.login_token_u32,
            item_cnt_per_page=session.defaults.page_item_cnt,
            max_pages=session.defaults.list_max_pages,
            debug=session.debug,
        )
        print(f"Media entries (all): {len(all_entries)}")
        for e in all_entries:
            print(
                f"  dir={e.get('dirNum')} media={e.get('mediaNum')} fileType={e.get('fileType')} "
                f"name={e.get('fileName') or ''} time={e.get('mediaTime') or ''} durMs={e.get('durationMs') or ''}"
            )
        return
    raise SystemExit(f"Unhandled op: {cfg.op!r}")


if __name__ == "__main__":
    asyncio.run(main())
