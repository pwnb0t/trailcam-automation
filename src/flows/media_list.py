from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from src.constants import CAMERA_IP
from src.protocol import decrypt_payload_b64_bytes, make_ack_body_seq_list16, parse_artemis_records, unpack_f1
from src.session import TrailCamSession


def _collect_media_entries(node: Any, out: List[Dict[str, Any]]) -> None:
    if isinstance(node, dict):
        if "mediaDirNum" in node and "mediaNum" in node:
            ent = dict(node)
            ent.setdefault("dirNum", ent.get("mediaDirNum"))
            out.append(ent)
        elif "dirNum" in node and "mediaNum" in node:
            out.append(node)
        for v in node.values():
            _collect_media_entries(v, out)
    elif isinstance(node, list):
        for item in node:
            _collect_media_entries(item, out)


def normalize_media_entry(ent: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return a canonical media entry dict with stable keys.

    We see a few different shapes in the media list responses. For client logic we want:
    - dirNum (int)
    - mediaNum (int)
    - fileType (int, 0=photo, 1=video)
    Plus optional fields when present: fileName, mediaTime, durationMs, mediaId.
    """
    try:
        dir_num = ent.get("dirNum", ent.get("mediaDirNum"))
        media_num = ent.get("mediaNum")
        if dir_num is None or media_num is None:
            return None
        dir_num_i = int(dir_num)
        media_num_i = int(media_num)
    except Exception:
        return None

    file_type = ent.get("fileType")
    try:
        if file_type is None:
            # Fall back to filename hints if present.
            name = str(ent.get("fileName") or ent.get("name") or "").upper()
            if name.endswith(".MP4") or name.endswith(".AVI"):
                file_type_i = 1
            else:
                file_type_i = 0
        else:
            file_type_i = int(file_type)
    except Exception:
        file_type_i = 0

    out: Dict[str, Any] = {"dirNum": dir_num_i, "mediaNum": media_num_i, "fileType": file_type_i}
    for k in ("fileName", "mediaTime", "durationMs", "mediaId", "mediaType"):
        if k in ent:
            out[k] = ent[k]
    return out


def _is_video_entry(entry: Dict[str, Any]) -> bool:
    file_type = entry.get("fileType")
    if isinstance(file_type, int):
        return file_type == 1
    if isinstance(file_type, str) and file_type.isdigit():
        return int(file_type) == 1

    name = str(entry.get("fileName") or entry.get("name") or "").upper()
    if name.endswith(".MP4") or name.endswith(".AVI"):
        return True
    if name.endswith(".JPG") or name.endswith(".JPEG"):
        return False
    return False


def _is_photo_entry(entry: Dict[str, Any]) -> bool:
    file_type = entry.get("fileType")
    if isinstance(file_type, int):
        return file_type == 0
    if isinstance(file_type, str) and file_type.isdigit():
        return int(file_type) == 0

    media_type = str(entry.get("mediaType", "")).upper()
    if "PHOTO" in media_type or media_type in {"0", "IMAGE", "JPG", "JPEG"}:
        return True

    name = str(entry.get("fileName") or entry.get("name") or "").upper()
    if name.endswith(".JPG") or name.endswith(".JPEG"):
        return True
    if name.endswith(".MP4") or name.endswith(".AVI"):
        return False

    # If unknown, assume photo; caller can inspect results.
    return True


def fetch_media_list_page(
    session: TrailCamSession,
    *,
    page_no: Optional[int] = None,
    item_cnt_per_page: Optional[int] = None,
    retries: int = 3,
    timeout_s: float = 8.0,
) -> List[Dict[str, Any]]:
    client = session.client
    token = int(session.login_token_u32)
    debug = bool(session.cfg.debug)
    if page_no is None:
        page_no = int(session.cfg.client.page_no)
    if item_cnt_per_page is None:
        item_cnt_per_page = int(session.cfg.client.page_item_cnt)

    dev_info = {"cmdId": 512, "token": token}
    media_list = {"cmdId": 768, "itemCntPerPage": item_cnt_per_page, "pageNo": page_no, "token": token}
    entries: List[Dict[str, Any]] = []
    seen_keys: set[tuple[int, int, int]] = set()
    last_media_list_error: Optional[str] = None
    stop_hb = threading.Event()

    def hb_loop():
        typ = 0x00010001
        while not stop_hb.is_set():
            client.send_cmd_json({"cmdId": 525}, art_ver=2, art_typ=typ)
            typ += 1
            if typ > 0x00010004:
                typ = 0x00010001
            stop_hb.wait(0.7)

    t_hb = threading.Thread(target=hb_loop, daemon=True)
    t_hb.start()

    try:
        for attempt in range(1, retries + 1):
            seq0_fragments: Dict[int, bytes] = {}
            if debug:
                print(f"TX JSON: dev info (attempt {attempt}/{retries})")
            client.send_cmd_json(dev_info, art_ver=2, art_typ=2)
            client.send_cmd_json(dev_info, art_ver=2, art_typ=3)
            time.sleep(0.05)
            if debug:
                print(f"TX JSON: media list page={page_no} count={item_cnt_per_page} (attempt {attempt}/{retries})")
            client.send_cmd_json(media_list, art_ver=2, art_typ=4)

            deadline = time.time() + timeout_s
            while time.time() < deadline:
                got = client.recv()
                if not got:
                    continue
                addr, data = got
                if addr[0] != CAMERA_IP:
                    continue
                parsed = unpack_f1(data)
                if parsed:
                    opcode, body, _ = parsed
                    if opcode in (0x41, 0x42):
                        client.send_f1(opcode, body)
                    elif opcode == 0xE0:
                        client.send_f1(0xE1, b"")
                    elif opcode == 0xD0 and len(body) >= 4 and body[0] == 0xD1 and body[1] == 0x00:
                        seq0 = (body[2] << 8) | body[3]
                        client.send_f1(0xD1, make_ack_body_seq_list16(0x00, [seq0]))
                        chunk = body[4:]
                        seq0_fragments[seq0] = chunk
                        for ver, typ, payload in parse_artemis_records(chunk):
                            if typ not in (4, 36):
                                continue
                            obj = decrypt_payload_b64_bytes(payload)
                            if not obj:
                                continue
                            if debug:
                                print("RX JSON media list:", obj)
                            if obj.get("cmdId") == 768 and obj.get("getMediaListRet") not in (None, 0):
                                last_media_list_error = str(obj.get("errorMsg") or obj)
                            found: List[Dict[str, Any]] = []
                            _collect_media_entries(obj, found)
                            for ent in found:
                                norm = normalize_media_entry(ent)
                                if not norm:
                                    continue
                                key = (norm["dirNum"], norm["mediaNum"], int(norm.get("fileType", 0)))
                                if key in seen_keys:
                                    continue
                                seen_keys.add(key)
                                entries.append(norm)
                for obj in client.handle_incoming_payload(data):
                    # Some responses may arrive via generic JSON path.
                    if obj.get("cmdId") == 768 and obj.get("getMediaListRet") not in (None, 0):
                        last_media_list_error = str(obj.get("errorMsg") or obj)
                    found: List[Dict[str, Any]] = []
                    _collect_media_entries(obj, found)
                    for ent in found:
                        norm = normalize_media_entry(ent)
                        if not norm:
                            continue
                        key = (norm["dirNum"], norm["mediaNum"], int(norm.get("fileType", 0)))
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)
                        entries.append(norm)
            if seq0_fragments:
                assembled_seq0 = b"".join(seq0_fragments[k] for k in sorted(seq0_fragments))
                for ver, typ, payload in parse_artemis_records(assembled_seq0):
                    if typ not in (4, 36):
                        continue
                    obj = decrypt_payload_b64_bytes(payload)
                    if not obj:
                        continue
                    if debug:
                        print("RX JSON media list (assembled):", obj)
                    if obj.get("cmdId") == 768 and obj.get("getMediaListRet") not in (None, 0):
                        last_media_list_error = str(obj.get("errorMsg") or obj)
                    found: List[Dict[str, Any]] = []
                    _collect_media_entries(obj, found)
                    for ent in found:
                        norm = normalize_media_entry(ent)
                        if not norm:
                            continue
                        key = (norm["dirNum"], norm["mediaNum"], int(norm.get("fileType", 0)))
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)
                        entries.append(norm)

            if entries:
                break
    finally:
        stop_hb.set()

    if not entries and last_media_list_error:
        print(f"Media list error: {last_media_list_error}")
    return entries
