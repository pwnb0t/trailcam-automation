import os
import subprocess
import threading
import time
import tempfile
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.client import TrailCamClient
from src.constants import CAMERA_IP
from src.session import TrailCamSession
from src.command.path_utils import camera_media_root
from src.protocol import (
    decrypt_payload_b64_bytes,
    decrypt_v4_media_data_pages,
    make_ack_body_seq_list16,
    make_ack_body_seq_window16,
    normalize_v4_video_payload_to_annexb,
    parse_artemis_records,
    parse_artemis_records_strict,
    unpack_f1,
)


def _media_dir_path(out_root: str, dir_num: int) -> Path:
    # Stable NAS-friendly layout: out/media/<dirNum>/...
    p = Path(out_root) / str(int(dir_num))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _media_file_path(out_root: str, dir_num: int, media_num: int, file_type: int) -> Path:
    d = _media_dir_path(out_root, dir_num)
    ext = ".mp4" if int(file_type) == 1 else ".jpg"
    return d / f"media{int(media_num):04d}{ext}"


def _session_media_root(session: TrailCamSession) -> str:
    return camera_media_root(str(session.cfg.paths.staging_dir), str(session.cfg.camera.alias))


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
        # App captures show an immediate double-send of cmdId=1285, then a later resend.
        if stop_hb.wait(0.02):
            return
        send_download_req()
        if stop_hb.wait(7.5):
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
    acked_seq0 = 0
    acked_seq3 = 0
    acked_seq4 = 0

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
            # App mostly sends 17-seq ACK windows on channel 0x03.
            client.send_f1(0xD1, make_ack_body_seq_window16(0x03, list(ack_win_seq3)))
            acked_seq3 += 1
            seq3_stream_chunks[seq16] = body[4:]
            last_seq3_ts = time.time()
            continue

        if opcode == 0xD0 and len(body) >= 4 and body[0] == 0xD1 and body[1] == 0x04:
            saw_download_data.set()
            seq16 = (body[2] << 8) | body[3]
            ack_win_seq4.append(seq16)
            # App mostly sends 17-seq ACK windows on channel 0x04.
            client.send_f1(0xD1, make_ack_body_seq_window16(0x04, list(ack_win_seq4)))
            acked_seq4 += 1
            seq4_stream_chunks[seq16] = body[4:]
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

    print(
        f"Download listen complete: seq0_chunks={len(seq0_stream_chunks)} acked_seq0={acked_seq0} "
        f"seq3_chunks={len(seq3_stream_chunks)} acked_seq3={acked_seq3} "
        f"seq4_chunks={len(seq4_stream_chunks)} acked_seq4={acked_seq4} "
        f"hb_sent={hb_sent} req1285_sent={dl_req_sent}"
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


def _parse_artemis_v4_payload_header(payload: bytes) -> Optional[Dict[str, int]]:
    # Empirical header used in video playback/download: 108 bytes.
    if len(payload) < 108:
        return None
    header_len = 108
    data_len = int.from_bytes(payload[16:20], "little", signed=False)
    data_len_off = 16
    if not (0 < data_len == (len(payload) - header_len)):
        data_len = int.from_bytes(payload[20:24], "little", signed=False)
        data_len_off = 20
        if not (0 < data_len == (len(payload) - header_len)):
            return None
    pts_ms = int.from_bytes(payload[8:12], "little", signed=False)
    width = int.from_bytes(payload[28:32], "little", signed=False)
    height = int.from_bytes(payload[32:36], "little", signed=False)
    session_no = int.from_bytes(payload[48:52], "little", signed=False)
    return {
        "header_len": header_len,
        "data_len": data_len,
        "data_len_off": data_len_off,
        "pts_ms": pts_ms,
        "width": width,
        "height": height,
        "session_no": session_no,
    }


def send_video_download_flow_item(
    session: TrailCamSession,
    dir_num: int,
    media_num: int,
    *,
    out_mp4_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Start playback for a gallery video and reconstruct an MP4 (H.264 + AAC)."""
    client = session.client
    token = int(session.login_token_u32)
    file_type = 1
    fps = int(session.cfg.client.video_fps)
    listen_s = float(session.cfg.client.download_listen_s)
    idle_break_s = float(session.cfg.client.download_idle_s)
    debug = bool(session.cfg.debug)

    if not out_mp4_path:
        out_mp4_path = str(_media_file_path(_session_media_root(session), dir_num, media_num, file_type=1))

    # Avoid /tmp on small devices (often tmpfs) by default.
    temp_root_p = Path(str(session.cfg.paths.tmp_dir))
    temp_root_p.mkdir(parents=True, exist_ok=True)

    # Session number: app provides one; we generate a stable-ish u16.
    session_no = int(time.time() * 1000) & 0xFFFF
    start_req = {
        "cmdId": 769,
        "fileType": file_type,
        "dirNum": dir_num,
        "mediaNum": media_num,
        "sessionNo": session_no,
        "token": token,
    }
    stop_req = {"cmdId": 770, "token": token}

    out_mp4 = Path(out_mp4_path)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)

    stop_hb = threading.Event()
    hb_sent = 0
    drained_packets = 0
    duplicate_seq = 0
    duplicate_seq_changed = 0
    out_of_session_records = 0
    pts_backwards_video = 0
    pts_backwards_audio = 0

    def drain_inbound(max_s: float = 0.8, quiet_s: float = 0.2) -> int:
        """Best-effort socket drain to reduce cross-session stale packets."""
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

    def hb_loop():
        nonlocal hb_sent
        typ = 0x00010001
        while not stop_hb.is_set():
            client.send_cmd_json({"cmdId": 525}, art_ver=2, art_typ=typ)
            hb_sent += 1
            typ += 1
            if typ > 0x00010004:
                typ = 0x00010001
            stop_hb.wait(0.7)

    print(
        f"TX JSON: start play record cmdId=769 fileType={file_type} dirNum={dir_num} mediaNum={media_num} sessionNo={session_no}"
    )
    drained_packets = drain_inbound()
    if debug and drained_packets:
        print(f"Drained stale UDP packets before start: {drained_packets}")
    client.send_cmd_json(start_req, art_ver=2, art_typ=2)
    t_hb = threading.Thread(target=hb_loop, daemon=True)
    t_hb.start()

    # Collect JSON response (start play ack) and subtype stream chunks.
    start_play_info: Dict[str, Any] = {}
    chunks02: Dict[int, bytes] = {}
    ack_win = deque(maxlen=33)
    last_data_ts: Optional[float] = None
    end = time.time() + listen_s

    with tempfile.TemporaryDirectory(prefix=f"trailcam_video_{dir_num}_{media_num}_", dir=str(temp_root_p)) as tmp_dir:
        tmp_root = Path(tmp_dir)
        tmp_h264 = tmp_root / "video.h264"
        tmp_aac = tmp_root / "audio.aac"

        v_cnt = 0
        a_cnt = 0
        try:
            while time.time() < end:
                got = client.recv()
                if not got:
                    if last_data_ts is not None and (time.time() - last_data_ts) > idle_break_s:
                        break
                    continue
                addr, data = got
                if addr[0] != CAMERA_IP:
                    continue

                parsed = unpack_f1(data)
                if parsed:
                    opcode, body, _ = parsed
                    if opcode in (0x41, 0x42):
                        client.send_f1(opcode, body)
                        continue
                    if opcode == 0xE0:
                        client.send_f1(0xE1, b"")
                        continue

                    # Data channel: D0 subtype 0x02
                    if opcode == 0xD0 and len(body) >= 4 and body[0] == 0xD1 and body[1] == 0x02:
                        seq16 = (body[2] << 8) | body[3]
                        chunk = body[4:]
                        prev = chunks02.get(seq16)
                        if prev is not None:
                            duplicate_seq += 1
                            if prev != chunk:
                                duplicate_seq_changed += 1
                        # Keep latest chunk for this seq; helps if stale/older packet arrived first.
                        chunks02[seq16] = chunk
                        last_data_ts = time.time()
                        ack_win.append(seq16)
                        client.send_f1(0xD1, make_ack_body_seq_window16(0x02, list(ack_win)))
                        continue

                # Control plane JSON
                for obj in client.handle_incoming_payload(data):
                    if debug:
                        print("RX JSON:", obj)
                    if obj.get("cmdId") == 769 or "startPbRet" in obj:
                        start_play_info = obj

            if not chunks02:
                raise RuntimeError("No D0 subtype=0x02 chunks captured for video stream")

            assembled = b"".join(chunks02[k] for k in sorted(chunks02))
            records = parse_artemis_records_strict(assembled)
            if not records:
                raise RuntimeError("No ARTEMIS records found in subtype=0x02 assembled stream")

            # Decode + decrypt ver=4 payload data.
            v_items: List[tuple[int, bytes, int, int]] = []
            a_items: List[tuple[int, bytes, int, int]] = []
            session_counts: Dict[int, int] = {}
            for rec_idx, (ver, _typ, payload) in enumerate(records):
                if ver != 4:
                    continue
                hdr = _parse_artemis_v4_payload_header(payload)
                if not hdr:
                    continue
                data_off = hdr["header_len"]
                data_len = hdr["data_len"]
                raw = payload[data_off : data_off + data_len]
                dec = decrypt_v4_media_data_pages(raw)
                sess = int(hdr["session_no"])
                session_counts[sess] = session_counts.get(sess, 0) + 1

                # Heuristic classification:
                # - video-like: width/height set and data_len_off=16
                # - audio-like: width/height 0 and data_len_off=20
                if hdr["data_len_off"] == 16 and hdr["width"] and hdr["height"]:
                    v_payload = normalize_v4_video_payload_to_annexb(dec)
                    v_items.append((int(hdr["pts_ms"]), v_payload, sess, rec_idx))
                    v_cnt += 1
                elif hdr["data_len_off"] == 20 and hdr["width"] == 0 and hdr["height"] == 0:
                    a_items.append((int(hdr["pts_ms"]), dec, sess, rec_idx))
                    a_cnt += 1

            target_session_no = session_no
            if target_session_no not in session_counts and session_counts:
                # Fallback to dominant session seen in stream if camera did not honor requested value.
                target_session_no = max(session_counts.items(), key=lambda kv: kv[1])[0]
            if debug and session_counts:
                print(
                    f"ver=4 session_no histogram: {dict(sorted(session_counts.items()))}; "
                    f"selected={target_session_no} requested={session_no}"
                )

            v_items_sess = [x for x in v_items if x[2] == target_session_no]
            a_items_sess = [x for x in a_items if x[2] == target_session_no]
            out_of_session_records = (len(v_items) - len(v_items_sess)) + (len(a_items) - len(a_items_sess))

            for prev, cur in zip(v_items_sess, v_items_sess[1:]):
                if cur[0] < prev[0]:
                    pts_backwards_video += 1
            for prev, cur in zip(a_items_sess, a_items_sess[1:]):
                if cur[0] < prev[0]:
                    pts_backwards_audio += 1

            v_items_sess.sort(key=lambda x: (x[0], x[3]))
            a_items_sess.sort(key=lambda x: (x[0], x[3]))

            # Duplicate PTS records can appear (e.g. retransmit artifacts). Keep the largest payload
            # for a given PTS to avoid concatenating repeated/corrupt access units.
            dedup_video_pts = 0
            dedup_audio_pts = 0
            v_by_pts: Dict[int, tuple[int, bytes, int, int]] = {}
            for item in v_items_sess:
                pts = item[0]
                prev = v_by_pts.get(pts)
                if prev is None or len(item[1]) > len(prev[1]):
                    if prev is not None:
                        dedup_video_pts += 1
                    v_by_pts[pts] = item
                else:
                    dedup_video_pts += 1
            a_by_pts: Dict[int, tuple[int, bytes, int, int]] = {}
            for item in a_items_sess:
                pts = item[0]
                prev = a_by_pts.get(pts)
                if prev is None or len(item[1]) > len(prev[1]):
                    if prev is not None:
                        dedup_audio_pts += 1
                    a_by_pts[pts] = item
                else:
                    dedup_audio_pts += 1

            v_items_sess = [v_by_pts[k] for k in sorted(v_by_pts)]
            a_items_sess = [a_by_pts[k] for k in sorted(a_by_pts)]

            v_h264 = bytearray()
            for _, dec, _, _ in v_items_sess:
                v_h264 += dec
            a_aac = bytearray()
            for _, dec, _, _ in a_items_sess:
                a_aac += dec

            if debug:
                print(f"Start play info: {start_play_info}")
            print(f"Captured subtype_02 chunks={len(chunks02)} bytes={len(assembled)}")
            print(
                f"Parsed ver=4 records: video={v_cnt} audio={a_cnt} "
                f"(session={target_session_no}: video={len(v_items_sess)} audio={len(a_items_sess)})"
            )
            if debug:
                print(
                    f"seq dupes={duplicate_seq} changed={duplicate_seq_changed} "
                    f"out_of_session={out_of_session_records} "
                    f"pts_backwards(video/audio)={pts_backwards_video}/{pts_backwards_audio} "
                    f"dedup_pts(video/audio)={dedup_video_pts}/{dedup_audio_pts}"
                )

            if not v_h264:
                raise RuntimeError("No decrypted video bytes produced (ver=4 video records not found)")
            if not a_aac:
                raise RuntimeError("No decrypted audio bytes produced (ver=4 audio records not found)")

            tmp_h264.write_bytes(bytes(v_h264))
            tmp_aac.write_bytes(bytes(a_aac))

            if subprocess.run(["ffmpeg", "-version"], capture_output=True).returncode != 0:
                raise RuntimeError("ffmpeg not available on PATH, cannot mux video")

            mp4_tmp = tmp_root / "out.mp4"
            cmd = [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-r",
                str(fps),
                "-i",
                str(tmp_h264),
                "-i",
                str(tmp_aac),
                "-c",
                "copy",
                "-bsf:a",
                "aac_adtstoasc",
                str(mp4_tmp),
            ]
            p = subprocess.run(cmd, capture_output=True, text=True)
            if p.returncode != 0 or not mp4_tmp.exists() or mp4_tmp.stat().st_size <= 0:
                err = (p.stderr or "").strip()
                raise RuntimeError(f"ffmpeg mux failed: {err or 'unknown error'}")

            out_mp4.write_bytes(mp4_tmp.read_bytes())
            print(f"Wrote MP4: {out_mp4} ({out_mp4.stat().st_size} bytes)")

        finally:
            # Stop playback and heartbeats.
            try:
                client.send_cmd_json(stop_req, art_ver=2, art_typ=2)
            except Exception:
                pass
            stop_hb.set()

    return {
        "out_mp4": str(out_mp4),
        "tmp_root": str(temp_root_p),
        "hb_sent": hb_sent,
        "video_records": v_cnt,
        "audio_records": a_cnt,
        "subtype02_chunks": len(chunks02),
        "start_play_info": start_play_info,
    }


def send_video_download_flow(session: TrailCamSession) -> Dict[str, Any]:
    """Download the session's target video and write it to the stable output layout."""
    if session.cfg.dir_num is None or session.cfg.media_num is None:
        raise ValueError("session.cfg.dir_num and session.cfg.media_num are required")
    out_mp4 = str(session.cfg.video_out or "").strip() or None
    return send_video_download_flow_item(
        session,
        int(session.cfg.dir_num),
        int(session.cfg.media_num),
        out_mp4_path=out_mp4,
    )


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
