from __future__ import annotations

import threading
import time
import tempfile
from collections import deque
from pathlib import Path
from typing import Any, Dict, Optional

from src.constants import CAMERA_IP
from src.protocol import (
    decrypt_payload_b64_bytes,
    make_ack_body_seq_list16,
    make_ack_body_seq_window16,
    parse_artemis_records,
    parse_artemis_records_strict,
    unpack_f1,
)
from src.session import TrailCamSession

from src.flows.common import _media_file_path, _session_media_root

def send_photo_download_flow(
    session: TrailCamSession,
    dir_num: int,
    media_num: int,
    *,
    dump_dir: str,
    file_type: int = 0,
):
    """
    Request a single media file via cmdId=1285 and capture download payloads.

    Notes:
    - Uses app-like command shape: {"cmdId":1285,"downloadReqs":[...],"token":...}
    - Uses ARTEMIS type 7 (seen in trailcam_10).
    """
    client = session.client
    token = int(session.login_token_u32)
    listen_s = float(session.cfg.client.download_listen_s)
    idle_break_s = float(session.cfg.client.download_idle_s)
    debug = bool(session.cfg.debug)

    art_typ = 7
    req = {
        "cmdId": 1285,
        "downloadReqs": [{"fileType": file_type, "dirNum": dir_num, "mediaNum": media_num}],
        "token": token,
    }

    out_dir = Path(dump_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    stop_hb = threading.Event()
    saw_download_data = threading.Event()
    hb_sent = 0
    dl_req_sent = 0
    drained_packets = 0

    def send_download_req():
        nonlocal dl_req_sent
        client.send_cmd_json(req, art_ver=2, art_typ=art_typ)
        dl_req_sent += 1

    def hb_loop():
        nonlocal hb_sent
        # App captures show cmdId=525 sent in bursts every ~3s during download.
        typ = 0x00010001
        while not stop_hb.is_set():
            burst = 2 if not saw_download_data.is_set() else 10
            for _ in range(burst):
                client.send_cmd_json({"cmdId": 525}, art_ver=2, art_typ=typ)
                hb_sent += 1
                typ += 1
                if typ > 0x00010004:
                    typ = 0x00010001
                if stop_hb.wait(0.012):
                    return
            if stop_hb.wait(3.0):
                return

    def req_resend_loop():
        # Safety resend only if transfer data has not started yet.
        if stop_hb.wait(1.5):
            return
        if saw_download_data.is_set():
            return
        send_download_req()
        if stop_hb.wait(4.0):
            return
        if saw_download_data.is_set():
            return
        send_download_req()

    def drain_inbound(max_s: float = 0.8, quiet_s: float = 0.2) -> int:
        """Best-effort socket drain to reduce stale packets from previous operations."""
        drained = 0
        deadline = time.time() + max_s
        last_pkt_ts = time.time()
        while time.time() < deadline:
            got = client.recv()
            if not got:
                if (time.time() - last_pkt_ts) >= quiet_s:
                    break
                continue
            _addr, _data = got
            drained += 1
            last_pkt_ts = time.time()
        return drained

    print(
        f"TX JSON: download photo cmdId=1285 fileType={file_type} dirNum={dir_num} mediaNum={media_num} art_typ={art_typ}"
    )
    drained_packets = drain_inbound()
    if debug and drained_packets:
        print(f"Drained stale UDP packets before photo download: {drained_packets}")
    send_download_req()
    t_hb = threading.Thread(target=hb_loop, daemon=True)
    t_req = threading.Thread(target=req_resend_loop, daemon=True)
    t_hb.start()
    t_req.start()

    end = time.time() + listen_s
    last_seq3_ts: Optional[float] = None
    last_seq4_ts: Optional[float] = None
    seq0_stream_chunks: Dict[int, bytes] = {}
    seq3_stream_chunks: Dict[int, bytes] = {}
    seq4_stream_chunks: Dict[int, bytes] = {}
    ack_win_seq3 = deque(maxlen=17)  # holds seq16 values
    ack_win_seq4 = deque(maxlen=17)  # holds seq16 values
    ack_pending_seq3 = 0
    ack_pending_seq4 = 0
    acked_seq0 = 0
    acked_seq3 = 0
    acked_seq4 = 0
    dup_seq0 = 0
    dup_seq0_changed = 0
    dup_seq3 = 0
    dup_seq3_changed = 0
    dup_seq4 = 0
    dup_seq4_changed = 0

    while time.time() < end:
        got = client.recv()
        if not got:
            continue
        addr, data = got
        if addr[0] != CAMERA_IP:
            continue
        parsed = unpack_f1(data)
        if not parsed:
            continue
        opcode, body, _ = parsed
        if opcode in (0x41, 0x42):
            client.send_f1(opcode, body)
            continue
        if opcode == 0xE0:
            client.send_f1(0xE1, b"")
            continue

        if opcode == 0xD0 and len(body) >= 4 and body[0] == 0xD1 and body[1] == 0x00:
            if len(body) > 20:
                saw_download_data.set()
            seq0 = (body[2] << 8) | body[3]
            # ACK each chunk sequence directly.
            client.send_f1(0xD1, make_ack_body_seq_list16(0x00, [seq0]))
            acked_seq0 += 1
            chunk = body[4:]
            prev = seq0_stream_chunks.get(seq0)
            if prev is not None:
                dup_seq0 += 1
                if prev != chunk:
                    dup_seq0_changed += 1
            else:
                # Keep first-seen payload for a sequence number.
                # Late duplicates can belong to stale/retransmitted traffic and corrupt assembly.
                seq0_stream_chunks[seq0] = chunk
            for ver, typ, payload in parse_artemis_records(chunk):
                if debug:
                    print(f"RX ARTEMIS ver={ver} typ={typ} len={len(payload)}")
                obj = decrypt_payload_b64_bytes(payload)
                if obj and debug:
                    print("RX JSON:", obj)
            continue

        if opcode == 0xD0 and len(body) >= 4 and body[0] == 0xD1 and body[1] == 0x03:
            saw_download_data.set()
            seq16 = (body[2] << 8) | body[3]
            ack_win_seq3.append(seq16)
            ack_pending_seq3 += 1
            # App does not ACK every chunk; it tends to ACK roughly once per ~10 chunks.
            # This reduces uplink pressure on small devices and matches capture behavior.
            if acked_seq3 < 3 or ack_pending_seq3 >= 10:
                client.send_f1(0xD1, make_ack_body_seq_window16(0x03, list(ack_win_seq3)))
                acked_seq3 += 1
                ack_pending_seq3 = 0
            chunk = body[4:]
            prev = seq3_stream_chunks.get(seq16)
            if prev is not None:
                dup_seq3 += 1
                if prev != chunk:
                    dup_seq3_changed += 1
            else:
                # Keep first-seen payload for a sequence number.
                seq3_stream_chunks[seq16] = chunk
            last_seq3_ts = time.time()
            continue

        if opcode == 0xD0 and len(body) >= 4 and body[0] == 0xD1 and body[1] == 0x04:
            saw_download_data.set()
            seq16 = (body[2] << 8) | body[3]
            ack_win_seq4.append(seq16)
            ack_pending_seq4 += 1
            # App does not ACK every chunk; it tends to ACK roughly once per ~10 chunks.
            if acked_seq4 < 3 or ack_pending_seq4 >= 10:
                client.send_f1(0xD1, make_ack_body_seq_window16(0x04, list(ack_win_seq4)))
                acked_seq4 += 1
                ack_pending_seq4 = 0
            chunk = body[4:]
            prev = seq4_stream_chunks.get(seq16)
            if prev is not None:
                dup_seq4 += 1
                if prev != chunk:
                    dup_seq4_changed += 1
            else:
                # Keep first-seen payload for a sequence number.
                seq4_stream_chunks[seq16] = chunk
            last_seq4_ts = time.time()
            continue

        # If data channels have gone quiet after starting transfer, stop early.
        # Only break once *all* channels that have started are quiet, otherwise we truncate.
        now = time.time()
        started = last_seq3_ts is not None or last_seq4_ts is not None
        if started:
            quiet_ok = True
            if last_seq3_ts is not None:
                quiet_ok = quiet_ok and ((now - last_seq3_ts) >= idle_break_s)
            if last_seq4_ts is not None:
                quiet_ok = quiet_ok and ((now - last_seq4_ts) >= idle_break_s)
            if quiet_ok:
                break

    stop_hb.set()
    if ack_pending_seq3 and ack_win_seq3:
        client.send_f1(0xD1, make_ack_body_seq_window16(0x03, list(ack_win_seq3)))
        acked_seq3 += 1
    if ack_pending_seq4 and ack_win_seq4:
        client.send_f1(0xD1, make_ack_body_seq_window16(0x04, list(ack_win_seq4)))
        acked_seq4 += 1

    print(
        f"Download listen complete: seq0_chunks={len(seq0_stream_chunks)} acked_seq0={acked_seq0} "
        f"seq3_chunks={len(seq3_stream_chunks)} acked_seq3={acked_seq3} "
        f"seq4_chunks={len(seq4_stream_chunks)} acked_seq4={acked_seq4} "
        f"hb_sent={hb_sent} req1285_sent={dl_req_sent}"
    )
    if debug:
        print(
            "Seq dupes changed: "
            f"seq0={dup_seq0}/{dup_seq0_changed} "
            f"seq3={dup_seq3}/{dup_seq3_changed} "
            f"seq4={dup_seq4}/{dup_seq4_changed}"
        )

    assembled0 = b"".join(seq0_stream_chunks[k] for k in sorted(seq0_stream_chunks))
    (out_dir / "seq0_assembled.bin").write_bytes(assembled0)
    assembled3 = b"".join(seq3_stream_chunks[k] for k in sorted(seq3_stream_chunks))
    assembled4 = b"".join(seq4_stream_chunks[k] for k in sorted(seq4_stream_chunks))
    if assembled3:
        (out_dir / "seq3_assembled.bin").write_bytes(assembled3)
    if assembled4:
        (out_dir / "seq4_assembled.bin").write_bytes(assembled4)

    records = parse_artemis_records(assembled0)
    print(f"Parsed ARTEMIS records from seq0 stream: {len(records)}")

    found = 0
    for idx, (ver, typ, payload) in enumerate(records, start=1):
        # Save all type 6/7 payloads for offline comparison.
        if typ in (6, 7):
            found += 1
            payload_path = out_dir / f"record_{idx:03d}_ver{ver}_typ{typ}_payload.bin"
            payload_path.write_bytes(payload)
            soi = payload.find(b"\xff\xd8\xff")
            eoi = payload.rfind(b"\xff\xd9")
            if soi != -1 and eoi != -1 and eoi > soi:
                jpg = payload[soi : eoi + 2]
                jpg_path = out_dir / f"record_{idx:03d}_ver{ver}_typ{typ}.jpg"
                jpg_path.write_bytes(jpg)
                print(f"  extracted {jpg_path} ({len(jpg)} bytes)")
            elif debug:
                print(f"  no jpeg markers in record idx={idx} ver={ver} typ={typ}")

    if found == 0:
        print("No ver/type 6 or 7 records found in seq0 stream")

    def parse_transfer_header72(payload: bytes) -> Optional[Dict[str, int]]:
        if len(payload) < 72:
            return None
        try:
            return {
                "dirNum": int.from_bytes(payload[0x20:0x22], "little"),
                "mediaNum": int.from_bytes(payload[0x22:0x24], "little"),
                "dataLen": int.from_bytes(payload[0x24:0x28], "little"),
                "mediaId": int.from_bytes(payload[0x30:0x34], "little"),
            }
        except Exception:
            return None

    extracted_meta: Dict[Path, Dict[str, int]] = {}

    def extract_jpegs_from_artemis_stream(label: str, blob: bytes) -> List[Path]:
        if not blob:
            return []
        recs = parse_artemis_records_strict(blob)
        if not recs:
            return []
        out_paths: List[Path] = []
        for idx, (ver, typ, payload) in enumerate(recs, start=1):
            h = parse_transfer_header72(payload)
            # Require a parseable transfer header and exact target match.
            # Without this we can accidentally pick unrelated/stale small JPEG payloads.
            if not h:
                continue
            if h["dirNum"] != dir_num or h["mediaNum"] != media_num:
                continue
            if len(payload) < 72:
                continue
            data = payload[72:]
            soi = data.find(b"\xff\xd8\xff")
            if soi == -1:
                continue
            # Prefer the last EOI within this record, but cap at the declared dataLen when present.
            cap_end = len(data)
            if h and h.get("dataLen"):
                cap_end = min(cap_end, int(h["dataLen"]))
            search = data[:cap_end]
            eoi = search.rfind(b"\xff\xd9")
            if eoi == -1 or eoi <= soi:
                continue
            jpg = search[soi : eoi + 2]
            p = out_dir / f"{label}_record_{idx:03d}_ver{ver}_typ{typ}_{len(jpg)}.jpg"
            p.write_bytes(jpg)
            out_paths.append(p)
            declared_len = int(h.get("dataLen") or 0)
            extracted_meta[p] = {
                "declared_len": declared_len,
                "len_delta": abs(declared_len - len(jpg)) if declared_len > 0 else 1_000_000_000,
                "typ7": 1 if typ == 7 else 0,
            }
        return out_paths

    extracted: List[Path] = []
    extracted += extract_jpegs_from_artemis_stream("seq3", assembled3)
    extracted += extract_jpegs_from_artemis_stream("seq4", assembled4)

    best_path: Optional[Path] = None
    if extracted:
        # Prefer candidate with a declared transfer length and tight size match, then typ7, then largest.
        def score(p: Path) -> tuple[int, int, int, int]:
            m = extracted_meta.get(p, {})
            declared = int(m.get("declared_len", 0))
            delta = int(m.get("len_delta", 1_000_000_000))
            typ7 = int(m.get("typ7", 0))
            return (1 if declared > 0 else 0, -delta, typ7, p.stat().st_size)

        best_path = sorted(extracted, key=score, reverse=True)[0]
        final_path = out_dir / "download.jpg"
        final_path.write_bytes(best_path.read_bytes())
        print(f"  extracted download.jpg from {best_path.name} ({final_path.stat().st_size} bytes)")
    elif debug:
        print("  no ARTEMIS-record JPEGs extracted from seq3/seq4")

    return {
        "seq0_chunks": len(seq0_stream_chunks),
        "seq3_chunks": len(seq3_stream_chunks),
        "seq4_chunks": len(seq4_stream_chunks),
        "acked_seq0": acked_seq0,
        "acked_seq3": acked_seq3,
        "acked_seq4": acked_seq4,
        "hb_sent": hb_sent,
        "req1285_sent": dl_req_sent,
        "drained_packets": drained_packets,
        "dump_dir": str(out_dir),
        "best_jpeg": str(out_dir / "download.jpg") if (out_dir / "download.jpg").exists() else None,
    }


def download_photo_to_out_item(session: TrailCamSession, dir_num: int, media_num: int) -> Optional[Path]:
    """Download a photo (dir/media) and write it to the stable output layout.

    Uses a temp dump directory under session.cfg.paths.tmp_dir and only keeps the final JPEG.
    """
    out_root = _session_media_root(session)
    temp_root = str(session.cfg.paths.tmp_dir)

    out_path = _media_file_path(out_root, dir_num, media_num, file_type=0)
    tmp_base = Path(temp_root) / "photo_dumps"
    tmp_base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"photo_{dir_num}_{media_num}_", dir=str(tmp_base)) as td:
        res = send_photo_download_flow(session, dir_num, media_num, dump_dir=td, file_type=0)
        best = res.get("best_jpeg")
        if not best:
            return None
        out_path.write_bytes(Path(best).read_bytes())
        return out_path


def download_photo_to_out(session: TrailCamSession) -> Optional[Path]:
    """Download the session's target photo and write it to the stable output layout."""
    if session.cfg.dir_num is None or session.cfg.media_num is None:
        raise ValueError("session.cfg.dir_num and session.cfg.media_num are required")
    return download_photo_to_out_item(session, int(session.cfg.dir_num), int(session.cfg.media_num))
