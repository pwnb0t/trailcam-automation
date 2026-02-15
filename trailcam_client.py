#!/usr/bin/env python3
import asyncio

from src.connection.connection import connect_and_login
from src.command.download_media_page_command import DownloadMediaPageCommand
from src.command.download_single_command import DownloadSingleCommand
from src.command.list_media_all_command import ListMediaAllCommand
from src.command.list_media_page_command import ListMediaPageCommand
from src.config import parse_config_and_args


async def main():
    cfg = parse_config_and_args()
    session = await connect_and_login(cfg)
    print(f"Camera addr: {session.client.camera_addr}")
    print(f"Login token: {session.login_token_u32}")

    if cfg.op == "login_only":
        return

    if cfg.op == "download_single":
        r = DownloadSingleCommand(session).run()
        print(f"Wrote {r.get('kind')}: {r.get('path') or 'none'}")
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
        page = ListMediaPageCommand(session).run()
        print(f"Media entries (page {session.client_cfg.page_no}): {len(page)}")
        for e in page:
            print(
                f"  dir={e.get('dirNum')} media={e.get('mediaNum')} fileType={e.get('fileType')} "
                f"name={e.get('fileName') or ''} time={e.get('mediaTime') or ''} durMs={e.get('durationMs') or ''}"
            )
        return

    if cfg.op == "list_media_all":
        all_entries = ListMediaAllCommand(session).run()
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
