from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from src.command.command import Command, CommandError
from src.flows import fetch_media_list_page
from src.session import TrailCamSession


@dataclass
class ListMediaAllCommand(Command):
    session: TrailCamSession

    def validate(self) -> None:
        s = self.session
        if s.client is None:
            raise CommandError("session.client is required")
        if not isinstance(s.login_token_u32, int) or s.login_token_u32 <= 0:
            raise CommandError("session.login_token_u32 must be a positive int")
        if int(s.cfg.client.page_item_cnt) >= 50:
            raise CommandError("session.cfg.client.page_item_cnt must be < 50 (camera rejects >= 50)")
        if int(s.cfg.client.list_max_pages) <= 0:
            raise CommandError("session.cfg.client.list_max_pages must be > 0")

    def run(self) -> List[Dict[str, Any]]:
        self.validate()
        session = self.session

        all_entries: List[Dict[str, Any]] = []
        seen: set[tuple[int, int, int]] = set()
        last_page_keys = None
        repeat_pages = 0
        no_new_pages = 0

        item_cnt_per_page = int(session.cfg.client.page_item_cnt)
        max_pages = int(session.cfg.client.list_max_pages)
        debug = bool(session.cfg.debug)

        print(
            f"Listing media pages: item_cnt={item_cnt_per_page} max_pages={max_pages}"
        )
        for page_no in range(0, max_pages):
            print(f"  requesting page {page_no} ...", flush=True)
            page = fetch_media_list_page(session, page_no=page_no, item_cnt_per_page=item_cnt_per_page)
            if not page:
                print(f"  page {page_no}: empty response; stopping")
                break

            keys = {(e["dirNum"], e["mediaNum"], int(e.get("fileType", 0))) for e in page}
            new_keys = keys - seen
            if not new_keys:
                no_new_pages += 1
            else:
                no_new_pages = 0
            print(
                f"  page {page_no}: entries={len(page)} new={len(new_keys)} "
                f"repeat_pages={repeat_pages} no_new_pages={no_new_pages}",
                flush=True,
            )
            if debug:
                print(f"  page {page_no}: running_unique={len(seen) + len(new_keys)}")

            if last_page_keys is not None and keys == last_page_keys:
                repeat_pages += 1
            else:
                repeat_pages = 0
            last_page_keys = keys
            if repeat_pages >= 2:
                print(f"  stopping: repeated page content detected ({repeat_pages} times)")
                break
            if no_new_pages >= 2:
                print(f"  stopping: no new entries for {no_new_pages} pages")
                break

            for e in page:
                k = (e["dirNum"], e["mediaNum"], int(e.get("fileType", 0)))
                if k in seen:
                    continue
                seen.add(k)
                all_entries.append(e)

        return all_entries
