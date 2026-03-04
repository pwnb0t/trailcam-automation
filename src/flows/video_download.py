from __future__ import annotations

import csv
import subprocess
import threading
import time
import tempfile
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.constants import CAMERA_IP
from src.protocol import (
    decrypt_payload_b64_bytes,
    decrypt_v4_media_data_pages,
    make_ack_body_seq_list16,
    make_ack_body_seq_window16,
    normalize_v4_video_payload_to_annexb_with_mode,
    parse_artemis_records,
    parse_artemis_records_strict,
    unpack_f1,
)
from src.session import TrailCamSession

from src.flows.common import _media_file_path, _session_media_root

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


def _is_sentinel_video_frame(data: bytes) -> bool:
    # Decompiled app explicitly ignores a synthetic marker frame:
    # 00 00 00 01 01
    return len(data) >= 5 and data[:5] == b"\x00\x00\x00\x01\x01"


def _seq16_forward_delta(anchor: int, seq: int) -> int:
    return (int(seq) - int(anchor)) & 0xFFFF


def _order_seq16_from_anchor(keys: List[int], anchor: int) -> List[int]:
    return sorted(keys, key=lambda s: _seq16_forward_delta(anchor, s))


def _seq16_missing_from_anchor(keys: List[int], anchor: int) -> int:
    if not keys:
        return 0
    ordered = _order_seq16_from_anchor(keys, anchor)
    max_delta = _seq16_forward_delta(anchor, ordered[-1])
    expected = max_delta + 1
    return max(0, expected - len(ordered))


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
    strict_video = bool(getattr(session.cfg.client, "strict_video", False))
    max_seq_span = 20000

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
    wrap_events = 0
    rx_seq_packets = 0
    wrap_debug_lines_left = 24
    prev_seq16_rx: Optional[int] = None
    seq_anchor: Optional[int] = None
    seq_outliers_dropped = 0

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
        # Mirror app behavior more closely: send cmdId=525 in short bursts every ~3s.
        typ = 0x00010001
        while not stop_hb.is_set():
            for _ in range(10):
                client.send_cmd_json({"cmdId": 525}, art_ver=2, art_typ=typ)
                hb_sent += 1
                typ += 1
                if typ > 0x00010004:
                    typ = 0x00010001
                if stop_hb.wait(0.012):
                    return
            if stop_hb.wait(3.0):
                return

    print(
        f"TX JSON: start play record cmdId=769 fileType={file_type} dirNum={dir_num} mediaNum={media_num} sessionNo={session_no}"
    )
    drained_packets = drain_inbound()
    if debug and drained_packets:
        print(f"Drained stale UDP packets before start: {drained_packets}")
    # App captures for start/stop playback use ARTEMIS type 15/16.
    client.send_cmd_json(start_req, art_ver=2, art_typ=15)
    t_hb = threading.Thread(target=hb_loop, daemon=True)
    t_hb.start()

    # Collect JSON response (start play ack) and subtype stream chunks.
    start_play_info: Dict[str, Any] = {}
    start_play_info_seen = False
    chunks02: Dict[int, bytes] = {}
    # App captures use ~17 sequence ACK windows on subtype 0x02.
    ack_win = deque(maxlen=17)
    ack_pending = 0
    last_data_ts: Optional[float] = None
    end = time.time() + listen_s

    with tempfile.TemporaryDirectory(prefix=f"trailcam_video_{dir_num}_{media_num}_", dir=str(temp_root_p)) as tmp_dir:
        tmp_root = Path(tmp_dir)
        tmp_h264 = tmp_root / "video.h264"
        tmp_aac = tmp_root / "audio.aac"
        tmp_assembled = tmp_root / "subtype_02_assembled.bin"
        tmp_records_csv = tmp_root / "v4_records.csv"

        v_cnt = 0
        a_cnt = 0
        dropped_sentinel_video = 0
        v4_rows: List[Dict[str, int]] = []
        v_mode_counts: Dict[str, int] = {"annexb": 0, "len16": 0, "raw": 0}
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

                    # Control JSON/data channel carried on subtype 0x00.
                    if opcode == 0xD0 and len(body) >= 4 and body[0] == 0xD1 and body[1] == 0x00:
                        seq0 = (body[2] << 8) | body[3]
                        client.send_f1(0xD1, make_ack_body_seq_list16(0x00, [seq0]))
                        chunk0 = body[4:]
                        for ver, typ, payload in parse_artemis_records(chunk0):
                            obj = decrypt_payload_b64_bytes(payload)
                            if not obj:
                                continue
                            if debug:
                                print("RX JSON:", obj)
                            if not start_play_info_seen and (
                                obj.get("cmdId") == 769 or "startPbRet" in obj
                            ):
                                start_play_info = obj
                                start_play_info_seen = True
                        continue

                    # Data channel: D0 subtype 0x02
                    if opcode == 0xD0 and len(body) >= 4 and body[0] == 0xD1 and body[1] == 0x02:
                        seq16 = (body[2] << 8) | body[3]
                        chunk = body[4:]
                        rx_seq_packets += 1
                        if seq_anchor is None:
                            seq_anchor = seq16
                        else:
                            if _seq16_forward_delta(seq_anchor, seq16) > max_seq_span:
                                seq_outliers_dropped += 1
                                if debug and seq_outliers_dropped <= 10:
                                    print(
                                        f"SEQ02 drop outlier seq16={seq16} anchor={seq_anchor} "
                                        f"delta={_seq16_forward_delta(seq_anchor, seq16)}"
                                    )
                                continue
                        # Instrumentation for investigating possible >16-bit sequencing:
                        # log around wrap boundaries and candidate wrap transitions with
                        # adjacent payload bytes so we can inspect whether hidden high bytes
                        # exist in-band.
                        if debug and wrap_debug_lines_left > 0:
                            near_boundary = seq16 <= 3 or seq16 >= 0xFFFC
                            wrapped = prev_seq16_rx is not None and prev_seq16_rx > 0xF000 and seq16 < 0x1000
                            if wrapped:
                                wrap_events += 1
                            if near_boundary or wrapped:
                                probe = chunk[:8].hex()
                                prev_s = -1 if prev_seq16_rx is None else prev_seq16_rx
                                print(
                                    f"SEQ02 rx_idx={rx_seq_packets} prev={prev_s} seq16={seq16} "
                                    f"wrapped={1 if wrapped else 0} chunk0_8={probe}"
                                )
                                wrap_debug_lines_left -= 1
                        prev_seq16_rx = seq16
                        prev = chunks02.get(seq16)
                        if prev is not None:
                            duplicate_seq += 1
                            if prev != chunk:
                                duplicate_seq_changed += 1
                        if prev is None:
                            # Keep first-seen payload for this seq to avoid late retransmits
                            # replacing already-accepted content.
                            chunks02[seq16] = chunk
                        last_data_ts = time.time()
                        ack_win.append(seq16)
                        ack_pending += 1
                        # App ACK cadence is roughly one ACK per ~10 data packets for subtype 0x02.
                        if len(ack_win) <= 3 or ack_pending >= 10:
                            client.send_f1(0xD1, make_ack_body_seq_window16(0x02, list(ack_win)))
                            ack_pending = 0
                        continue

                # Control plane JSON
                for obj in client.handle_incoming_payload(data):
                    if debug:
                        print("RX JSON:", obj)
                    if not start_play_info_seen and (obj.get("cmdId") == 769 or "startPbRet" in obj):
                        start_play_info = obj
                        start_play_info_seen = True

            if not chunks02:
                raise RuntimeError("No D0 subtype=0x02 chunks captured for video stream")

            if seq_anchor is None:
                raise RuntimeError("No D0 subtype=0x02 sequence anchor established")
            seq_keys_ordered = _order_seq16_from_anchor(list(chunks02.keys()), seq_anchor)
            assembled = b"".join(chunks02[k] for k in seq_keys_ordered)
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
                v4_rows.append(
                    {
                        "record_idx": int(rec_idx),
                        "pts_ms": int(hdr["pts_ms"]),
                        "data_len": int(hdr["data_len"]),
                        "data_len_off": int(hdr["data_len_off"]),
                        "width": int(hdr["width"]),
                        "height": int(hdr["height"]),
                        "session_no": int(sess),
                    }
                )

                # Heuristic classification:
                # - video-like: width/height set and data_len_off=16
                # - audio-like: width/height 0 and data_len_off=20
                if hdr["data_len_off"] == 16 and hdr["width"] and hdr["height"]:
                    if _is_sentinel_video_frame(dec):
                        dropped_sentinel_video += 1
                        continue
                    v_payload, mode = normalize_v4_video_payload_to_annexb_with_mode(dec)
                    if _is_sentinel_video_frame(v_payload):
                        dropped_sentinel_video += 1
                        continue
                    v_mode_counts[mode] = v_mode_counts.get(mode, 0) + 1
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

            # Preserve capture/record order; this matches how the extractor tool reconstructs
            # streams from PCAP and avoids reordering access units by PTS.
            v_items_sess.sort(key=lambda x: x[3])
            a_items_sess.sort(key=lambda x: x[3])

            # Do not deduplicate by PTS: multiple records can legitimately share a PTS.
            dedup_video_pts = 0
            dedup_audio_pts = 0

            v_h264 = bytearray()
            for _, dec, _, _ in v_items_sess:
                v_h264 += dec
            a_aac = bytearray()
            for _, dec, _, _ in a_items_sess:
                a_aac += dec

            if debug:
                print(f"Start play info: {start_play_info}")
            seq_keys = seq_keys_ordered
            missing_seq = _seq16_missing_from_anchor(seq_keys, seq_anchor)
            print(f"Captured subtype_02 chunks={len(chunks02)} bytes={len(assembled)}")
            print(
                f"Parsed ver=4 records: video={v_cnt} audio={a_cnt} "
                f"(session={target_session_no}: video={len(v_items_sess)} audio={len(a_items_sess)})"
            )
            if debug:
                print(
                    f"seq dupes={duplicate_seq} changed={duplicate_seq_changed} "
                    f"seq_anchor={seq_anchor if seq_anchor is not None else -1} "
                    f"seq_range={seq_keys[0] if seq_keys else -1}-{seq_keys[-1] if seq_keys else -1} "
                    f"seq_missing={missing_seq} "
                    f"seq_outliers_dropped={seq_outliers_dropped} "
                    f"seq_wrap_events={wrap_events} "
                    f"dropped_sentinel_video={dropped_sentinel_video} "
                    f"out_of_session={out_of_session_records} "
                    f"pts_backwards(video/audio)={pts_backwards_video}/{pts_backwards_audio} "
                    f"dedup_pts(video/audio)={dedup_video_pts}/{dedup_audio_pts} (disabled) "
                    f"v_modes={v_mode_counts}"
                )

            if strict_video:
                strict_issues = []
                if missing_seq > 0:
                    strict_issues.append(f"missing_seq={missing_seq}")
                if duplicate_seq_changed > 0:
                    strict_issues.append(f"duplicate_seq_changed={duplicate_seq_changed}")
                if out_of_session_records > 0:
                    strict_issues.append(f"out_of_session_records={out_of_session_records}")
                if pts_backwards_video > 0:
                    strict_issues.append(f"pts_backwards_video={pts_backwards_video}")
                if pts_backwards_audio > 0:
                    strict_issues.append(f"pts_backwards_audio={pts_backwards_audio}")
                try:
                    expected_total_frame = int(start_play_info.get("totalFrame", 0))
                except Exception:
                    expected_total_frame = 0
                try:
                    expected_total_time_ms = int(start_play_info.get("totalTime", 0))
                except Exception:
                    expected_total_time_ms = 0
                if expected_total_frame > 0 and len(v_items_sess) != expected_total_frame:
                    strict_issues.append(
                        f"video_frame_count={len(v_items_sess)} expected_totalFrame={expected_total_frame}"
                    )
                if strict_issues:
                    raise RuntimeError(
                        "Strict video transport check failed: " + ", ".join(strict_issues)
                    )

            if not v_h264:
                raise RuntimeError("No decrypted video bytes produced (ver=4 video records not found)")
            if not a_aac:
                raise RuntimeError("No decrypted audio bytes produced (ver=4 audio records not found)")

            tmp_h264.write_bytes(bytes(v_h264))
            tmp_aac.write_bytes(bytes(a_aac))
            tmp_assembled.write_bytes(assembled)
            if v4_rows:
                with tmp_records_csv.open("w", newline="") as f:
                    w = csv.DictWriter(
                        f,
                        fieldnames=[
                            "record_idx",
                            "pts_ms",
                            "data_len",
                            "data_len_off",
                            "width",
                            "height",
                            "session_no",
                        ],
                    )
                    w.writeheader()
                    w.writerows(v4_rows)

            if subprocess.run(["ffmpeg", "-version"], capture_output=True).returncode != 0:
                raise RuntimeError("ffmpeg not available on PATH, cannot mux video")

            # Prefer camera-provided pacing when available.
            mux_fps = float(fps)
            try:
                total_frame = int(start_play_info.get("totalFrame", 0))
                total_time_ms = int(start_play_info.get("totalTime", 0))
                if total_frame > 0 and total_time_ms > 0:
                    derived = (total_frame * 1000.0) / float(total_time_ms)
                    if 1.0 <= derived <= 120.0:
                        mux_fps = float(derived)
            except Exception:
                pass
            if debug:
                print(f"Video mux fps: {mux_fps:.6f}")

            mp4_tmp = tmp_root / "out.mp4"
            cmd = [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-r",
                f"{mux_fps:.6f}",
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
            if debug:
                dbg_dir = out_mp4.parent / f"{out_mp4.stem}.debug"
                dbg_dir.mkdir(parents=True, exist_ok=True)
                (dbg_dir / "subtype_02_assembled.bin").write_bytes(tmp_assembled.read_bytes())
                (dbg_dir / "video.h264").write_bytes(tmp_h264.read_bytes())
                (dbg_dir / "audio.aac").write_bytes(tmp_aac.read_bytes())
                if tmp_records_csv.exists():
                    (dbg_dir / "v4_records.csv").write_bytes(tmp_records_csv.read_bytes())
                print(f"Wrote debug dump: {dbg_dir}")

        finally:
            if ack_pending and ack_win:
                try:
                    client.send_f1(0xD1, make_ack_body_seq_window16(0x02, list(ack_win)))
                except Exception:
                    pass
            # Stop playback and heartbeats.
            try:
                client.send_cmd_json(stop_req, art_ver=2, art_typ=16)
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
