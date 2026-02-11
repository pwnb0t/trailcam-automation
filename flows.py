import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from client import TrailCamClient
from constants import CAMERA_IP, WIFI_IFNAME, CAMERA_USERNAME, CAMERA_PASSWORD
from protocol import (
    decrypt_artemis_json,
    decrypt_cmd_b64,
    decrypt_payload_b64_bytes,
    make_ack_body_seq16,
    make_ack_body_seq8,
    parse_artemis_records,
    unpack_f1,
)
from seed import get_seed_thumbnail_reqs


def nmcli_rescan() -> None:
    subprocess.run(["sudo", "nmcli", "dev", "wifi", "rescan"], capture_output=True)


def nmcli_list_ssids() -> List[str]:
    p = subprocess.run(["sudo", "nmcli", "-t", "-f", "SSID", "dev", "wifi"], text=True, capture_output=True)
    if p.returncode != 0:
        return []
    return [line.strip() for line in p.stdout.splitlines() if line.strip()]


def nmcli_connect(ssid: str, pwd: str, ifname: str = WIFI_IFNAME) -> bool:
    # remove stale profile first
    subprocess.run(["sudo", "nmcli", "con", "delete", "id", ssid], text=True, capture_output=True)
    cmd = ["sudo", "nmcli", "dev", "wifi", "connect", ssid, "password", pwd, "ifname", ifname]
    p = subprocess.run(cmd, text=True, capture_output=True)
    if p.returncode != 0:
        err = (p.stderr or "").strip()
        out = (p.stdout or "").strip()
        print("nmcli connect failed:")
        if out:
            print(out)
        if err:
            print(err)
        return False
    return True


def wifi_has_camera_ip(ifname: str = WIFI_IFNAME) -> bool:
    p = subprocess.run(["sudo", "ip", "-br", "addr", "show", ifname], text=True, capture_output=True)
    out = p.stdout.strip()
    return "192.168.43." in out


def handshake_prelude(client: TrailCamClient, debug: bool = False, duration_s: float = 3.0):
    seen_ops = {}
    start = time.time()
    while time.time() - start < duration_s:
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
        seen_ops[opcode] = seen_ops.get(opcode, 0) + 1
        if debug:
            print(f"RX opcode=0x{opcode:02x} len={len(body)}")
        if opcode in (0x41, 0x42):
            client.send_f1(opcode, body)
            time.sleep(0.02)
            client.send_f1(opcode, body)
        elif opcode == 0xE0:
            client.send_f1(0xE1, b"")
        elif opcode == 0xD0 and len(body) >= 4 and body[0] == 0xD1 and body[1] == 0x00:
            seq8 = body[3]
            ack = make_ack_body_seq8([seq8])
            client.send_f1(0xD1, ack)
    if debug:
        print("Handshake opcodes seen:", {hex(k): v for k, v in seen_ops.items()})


def login_and_get_token(
    client: TrailCamClient,
    timeout_s: float = 5.0,
    retries: int = 3,
) -> Optional[int]:
    login_obj = {
        "cmdId": 0,
        "usrName": CAMERA_USERNAME,
        "password": CAMERA_PASSWORD,
        "needVideo": 0,
        "needAudio": 0,
        "utcTime": int(time.time()),
        "supportHeartBeat": True,
    }
    for _ in range(retries):
        client.send_cmd_json(login_obj, art_ver=2, art_typ=1)
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            got = client.recv()
            if not got:
                continue
            addr, data = got
            if addr[0] != CAMERA_IP:
                continue
            objs = client.handle_incoming_payload(data)
            for obj in objs:
                if obj.get("cmdId") == 0 and "token" in obj:
                    return int(obj["token"])
    return None


def send_full_json_flow(
    client: TrailCamClient,
    token: int,
    page: int = 0,
    per_page: int = 45,
    listen_s: float = 12.0,
    repeats: int = 1,
    dump_thumbs: bool = False,
    thumb_offset: int = 0,
    thumb_dir: Optional[int] = None,
    dump_artemis: bool = False,
    debug: bool = False,
):
    time.sleep(0.3)
    dev_info = {"cmdId": 512, "token": token}
    media_list = {"cmdId": 768, "itemCntPerPage": per_page, "pageNo": page, "token": token}

    thumb_reqs = get_seed_thumbnail_reqs()
    thumb_cmd = None
    if thumb_reqs:
        if thumb_offset or thumb_dir is not None:
            adj = []
            for r in thumb_reqs:
                nr = dict(r)
                if thumb_offset:
                    nr["mediaNum"] = int(nr["mediaNum"]) + int(thumb_offset)
                if thumb_dir is not None:
                    nr["dirNum"] = int(thumb_dir)
                adj.append(nr)
            thumb_reqs = adj
        thumb_cmd = {"cmdId": 772, "thumbnailReqs": thumb_reqs, "token": token}
    else:
        thumb_cmd = {"cmdId": 772, "thumbnailReqs": [], "token": token}

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

    def send_dev_media(round_idx: int):
        print(f"TX JSON: dev info (attempt {round_idx}/{repeats})")
        client.send_cmd_json(dev_info, art_ver=2, art_typ=2)
        client.send_cmd_json(dev_info, art_ver=2, art_typ=3)
        time.sleep(0.05)
        print(f"TX JSON: media list (attempt {round_idx}/{repeats})")
        client.send_cmd_json(media_list, art_ver=2, art_typ=4)
        if thumb_cmd:
            print(f"TX JSON: thumbs (attempt {round_idx}/{repeats})")
            client.send_cmd_json(thumb_cmd, art_ver=2, art_typ=5)
        time.sleep(0.1)

    for i in range(repeats):
        send_dev_media(i + 1)

    large_chunks: Dict[int, bytes] = {}
    seq8_chunks: Dict[int, bytes] = {}
    seen_seq8: set[int] = set()
    seen_seq16: set[int] = set()
    end = time.time() + listen_s
    while time.time() < end:
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
            if opcode == 0xD0 and len(body) >= 4 and body[0] == 0xD1 and body[1] == 0x00:
                seq8 = body[3]
                seen_seq8.add(seq8)
                client.send_f1(0xD1, make_ack_body_seq8(sorted(seen_seq8)))
                seq8_chunks[seq8] = body[4:]
                for ver, typ, payload in parse_artemis_records(body[4:]):
                    print(f"RX ARTEMIS ver={ver} typ={typ} len={len(payload)}")
                    if dump_artemis and typ in (4, 36):
                        out_dir = Path("out") / "artemis"
                        out_dir.mkdir(parents=True, exist_ok=True)
                        fname = out_dir / f"rx_ver{ver}_typ{typ}_seq{seq8}.bin"
                        fname.write_bytes(payload)
                    if typ in (4, 36):
                        obj = decrypt_payload_b64_bytes(payload)
                        if obj and debug:
                            print("RX JSON media list:", obj)
            elif opcode == 0xD0 and len(body) >= 4 and body[0] == 0xD1 and body[1] == 0x04:
                seq16 = (body[2] << 8) | body[3]
                seen_seq16.add(seq16)
                client.send_f1(0xD1, make_ack_body_seq16(sorted(seen_seq16)))
                large_chunks[seq16] = body[4:]

        objs = client.handle_incoming_payload(data)
        for obj in objs:
            print("RX JSON:", obj)

    stop_hb.set()

    if not large_chunks:
        # still try to parse seq8 stream for media list JSON
        if seq8_chunks:
            assembled_small = b"".join(seq8_chunks[k] for k in sorted(seq8_chunks))
            for ver, typ, payload in parse_artemis_records(assembled_small):
                if typ in (4, 36):
                    obj = decrypt_payload_b64_bytes(payload)
                    if obj and debug:
                        print("RX JSON media list:", obj)
        return

    # parse seq8 stream for media list JSON (multi-chunk)
    if seq8_chunks:
        assembled_small = b"".join(seq8_chunks[k] for k in sorted(seq8_chunks))
        for ver, typ, payload in parse_artemis_records(assembled_small):
            if typ in (4, 36):
                obj = decrypt_payload_b64_bytes(payload)
                if obj and debug:
                    print("RX JSON media list:", obj)

    assembled = b"".join(large_chunks[k] for k in sorted(large_chunks))
    print(f"Large D0 stream: {len(large_chunks)} chunks, {len(assembled)} bytes")

    records = parse_artemis_records(assembled)
    if not records:
        print("No ARTEMIS records found in large stream")
        return

    print(f"Gallery records: {len(records)}")
    out_dir = Path("out")
    if dump_thumbs:
        out_dir.mkdir(parents=True, exist_ok=True)

    for idx, (ver, typ, payload) in enumerate(records, start=1):
        if len(payload) < 72:
            continue
        mac = payload[0:17].decode("ascii", errors="ignore").strip("\x00")
        record_id = int.from_bytes(payload[0x22:0x24], "little")
        jpeg_len = int.from_bytes(payload[0x24:0x26], "little")
        jpeg = payload[72 : 72 + jpeg_len]
        print(f"  {idx:02d}: record_id={record_id} jpeg_len={jpeg_len} mac={mac}")
        if dump_thumbs and jpeg.startswith(b"\xff\xd8"):
            (out_dir / f"thumb_{record_id}.jpg").write_bytes(jpeg)


def send_photo_download_flow(
    client: TrailCamClient,
    token: int,
    dir_num: int,
    media_num: int,
    file_type: int = 0,
    art_typ: int = 7,
    listen_s: float = 20.0,
    dump_dir: str = "out/download",
    debug: bool = False,
):
    """
    Request a single media file via cmdId=1285 and capture download payloads.

    Notes:
    - Uses app-like command shape: {"cmdId":1285,"downloadReqs":[...],"token":...}
    - Uses ARTEMIS type 7 by default (seen in trailcam_10).
    """
    req = {
        "cmdId": 1285,
        "downloadReqs": [{"fileType": file_type, "dirNum": dir_num, "mediaNum": media_num}],
        "token": token,
    }

    out_dir = Path(dump_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

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

    print(
        f"TX JSON: download photo cmdId=1285 fileType={file_type} dirNum={dir_num} mediaNum={media_num} art_typ={art_typ}"
    )
    client.send_cmd_json(req, art_ver=2, art_typ=art_typ)

    end = time.time() + listen_s
    seq8_stream_chunks: List[bytes] = []
    seq16_chunks: Dict[int, bytes] = {}
    seen_seq16: set[int] = set()
    acked_seq8 = 0

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
            seq8 = body[3]
            # ACK each chunk sequence directly; avoids seq8 wrap ambiguity
            client.send_f1(0xD1, make_ack_body_seq8([seq8]))
            acked_seq8 += 1
            chunk = body[4:]
            seq8_stream_chunks.append(chunk)
            for ver, typ, payload in parse_artemis_records(chunk):
                if debug:
                    print(f"RX ARTEMIS ver={ver} typ={typ} len={len(payload)}")
                obj = decrypt_payload_b64_bytes(payload)
                if obj and debug:
                    print("RX JSON:", obj)
            continue

        if opcode == 0xD0 and len(body) >= 4 and body[0] == 0xD1 and body[1] == 0x04:
            seq16 = (body[2] << 8) | body[3]
            seen_seq16.add(seq16)
            client.send_f1(0xD1, make_ack_body_seq16(sorted(seen_seq16)))
            seq16_chunks[seq16] = body[4:]

    stop_hb.set()

    print(f"Download listen complete: seq8_chunks={len(seq8_stream_chunks)} acked_seq8={acked_seq8}")

    assembled = b"".join(seq8_stream_chunks)
    (out_dir / "seq8_assembled.bin").write_bytes(assembled)

    records = parse_artemis_records(assembled)
    print(f"Parsed ARTEMIS records from seq8 stream: {len(records)}")

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
        print("No ver/type 6 or 7 records found in seq8 stream")

    if seq16_chunks:
        assembled16 = b"".join(seq16_chunks[k] for k in sorted(seq16_chunks))
        (out_dir / "seq16_assembled.bin").write_bytes(assembled16)
        if debug:
            print(f"Also captured seq16 stream: chunks={len(seq16_chunks)} bytes={len(assembled16)}")


def extract_gallery_records(assembled: bytes, out_dir: Optional[str] = None):
    records = []
    for ver, typ, payload in parse_artemis_records(assembled):
        if len(payload) < 72:
            continue
        header = payload[:72]
        mac = header[:17].decode("ascii", errors="ignore")
        record_id = int.from_bytes(header[34:36], "little")
        jpeg_len = int.from_bytes(header[36:38], "little")
        jpeg = payload[72 : 72 + jpeg_len]
        records.append((record_id, jpeg_len, ver, typ, mac, jpeg))

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        for record_id, jpeg_len, ver, typ, mac, jpeg in records:
            if not jpeg.startswith(b"\xff\xd8\xff"):
                continue
            fname = f"thumb_{record_id}_type{typ}_ver{ver}_{mac.replace(':','')}.jpg"
            path = os.path.join(out_dir, fname)
            with open(path, "wb") as f:
                f.write(jpeg)

    return records
