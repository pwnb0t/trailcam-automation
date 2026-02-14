#!/usr/bin/env python3
"""
pcap_to_csv.py

Parse TrailCam UDP traffic from a PCAP and emit a "scan-friendly" CSV.

Design goals:
- Works without root (offline) and relies on tshark for PCAP decoding.
- Filters down to "F1" protocol frames (data[0]==0xF1).
- Excludes external opcode 0xF9 traffic by default.
- Avoids dumping full payloads; instead shows opcode/subtype/seq and a short summary.
"""

from __future__ import annotations

import argparse
import binascii
import csv
import ipaddress
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Iterable, Optional


F1_MAGIC = 0xF1


@dataclass(frozen=True)
class Row:
    frame_no: int
    t_rel: float
    t_delta: float
    src: str
    sport: int
    dst: str
    dport: int
    direction: str
    opcode: str
    subtype: str
    seq_lo: str
    seq16: str
    body_len: int
    art_ver: str
    art_typ: str
    art_len: str
    summary: str


def _run_tshark_fields(pcap_path: str, display_filter: str) -> list[list[str]]:
    # Tab-separated for robustness; one packet per line.
    # frame.time_relative: seconds since beginning of capture
    cmd = [
        "tshark",
        "-r",
        pcap_path,
        "-Y",
        display_filter,
        "-T",
        "fields",
        "-E",
        "separator=\t",
        "-e",
        "frame.number",
        "-e",
        "frame.time_relative",
        "-e",
        "ip.src",
        "-e",
        "udp.srcport",
        "-e",
        "ip.dst",
        "-e",
        "udp.dstport",
        "-e",
        "data",
    ]
    out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
    rows: list[list[str]] = []
    for line in out.splitlines():
        parts = line.decode("utf-8", errors="replace").split("\t")
        # tshark can emit empty fields; keep arity stable
        while len(parts) < 7:
            parts.append("")
        rows.append(parts[:7])
    return rows


def _parse_hex_bytes(hex_str: str) -> Optional[bytes]:
    hs = hex_str.strip()
    if not hs:
        return None
    try:
        return binascii.unhexlify(hs)
    except Exception:
        return None


def _is_broadcast_ip(ip: str) -> bool:
    return ip in {"255.255.255.255", "192.168.43.255"}


def _infer_client_ip(packets: list[tuple[str, str]], camera_ip: str) -> Optional[str]:
    # Pick the most common non-camera IP that talks to camera.
    counts: dict[str, int] = {}
    for src, dst in packets:
        if src != camera_ip:
            counts[src] = counts.get(src, 0) + 1
        if dst != camera_ip:
            counts[dst] = counts.get(dst, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _direction(src: str, dst: str, camera_ip: str, client_ip: Optional[str]) -> str:
    if src == camera_ip and client_ip and dst == client_ip:
        return "cam->client"
    if client_ip and src == client_ip and dst == camera_ip:
        return "client->cam"
    if _is_broadcast_ip(dst):
        if src == camera_ip:
            return "cam->broadcast"
        if client_ip and src == client_ip:
            return "client->broadcast"
        return "->broadcast"
    if src == camera_ip:
        return "cam->other"
    if client_ip and src == client_ip:
        return "client->other"
    return "other"


def _opcode_name(op: int) -> str:
    return f"0x{op:02x}"


def _subtype_name(st: Optional[int]) -> str:
    if st is None:
        return ""
    return f"0x{st:02x}"


def _find_ascii_json(blob: bytes) -> Optional[dict]:
    # Heuristic: find a JSON object in ASCII inside the payload.
    # Avoid huge backtracking; scan for smallish {...} and validate via json.loads.
    s = blob.decode("utf-8", errors="ignore")
    for m in re.finditer(r"\{[^{}]{10,2000}\}", s):
        candidate = m.group(0)
        try:
            obj = json.loads(candidate)
        except Exception:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _first_artemis_record(blob: bytes) -> Optional[tuple[int, int, int, bytes]]:
    """Return (ver, typ, payload_len, payload_bytes) for the first record in blob."""
    i = blob.find(b"ARTEMIS\x00")
    if i == -1 or i + 20 > len(blob):
        return None
    ver = int.from_bytes(blob[i + 8 : i + 12], "little")
    typ = int.from_bytes(blob[i + 12 : i + 16], "little")
    ln = int.from_bytes(blob[i + 16 : i + 20], "little")
    j = i + 20 + ln
    if ln <= 0 or j > len(blob):
        return None
    payload = blob[i + 20 : j]
    return ver, typ, ln, payload


def _summarize(op: int, subtype: Optional[int], payload: bytes) -> str:
    if op == 0x30:
        return "beacon/broadcast"
    if op in (0x41, 0x42, 0x43):
        return "handshake"
    if op == 0xE0:
        return "keepalive trigger"
    if op == 0xE1:
        return "keepalive response"
    if op == 0xD1:
        return "ack"
    if op == 0xF9:
        return "internet/p2p/telemetry? (excluded by default)"
    if op == 0xD0:
        art = _first_artemis_record(payload)
        if subtype == 0x00:
            # First try: proper ARTEMIS decrypt (preferred)
            if art is not None:
                try:
                    # Import lazily so this tool can still run in minimal envs.
                    from src import protocol

                    objs = protocol.decrypt_artemis_json(payload)
                    if objs:
                        return "ARTEMIS json " + json.dumps(objs[0], separators=(",", ":"), sort_keys=True)
                except Exception:
                    pass

            # Fallback: plaintext JSON heuristic
            obj = _find_ascii_json(payload)
            if obj is not None:
                return "json " + json.dumps(obj, separators=(",", ":"), sort_keys=True)

            if art is not None:
                ver, typ, ln, _pl = art
                return f"ARTEMIS v={ver} t={typ} len={ln}"
            return "ctrl/data"
        if subtype == 0x03:
            if b"\xff\xd8" in payload:
                return "bulk (jpeg marker seen)"
            if art is not None:
                ver, typ, ln, _pl = art
                return f"bulk ARTEMIS v={ver} t={typ} len={ln}"
            return "bulk"
        if subtype == 0x04:
            if b"\xff\xd8" in payload:
                return "stream2 (jpeg marker seen)"
            if art is not None:
                ver, typ, ln, _pl = art
                return f"stream2 ARTEMIS v={ver} t={typ} len={ln}"
            return "stream2"
        return "data"
    return ""


def iter_rows(
    pcap_path: str,
    camera_ip: str,
    client_ip: Optional[str],
    include_f9: bool,
    include_broadcast: bool,
) -> Iterable[Row]:
    # Filter to UDP with a data field and our magic.
    base_filter = "udp && data && data[0]==f1"
    tshark_rows = _run_tshark_fields(pcap_path, base_filter)

    # First pass: parse minimal addressing and infer client_ip if not provided.
    addr_pairs: list[tuple[str, str]] = []
    parsed: list[tuple[int, float, str, int, str, int, bytes]] = []
    for fr, t_rel, src, sport, dst, dport, data_hex in tshark_rows:
        if not src or not dst or not sport or not dport or not data_hex:
            continue
        data = _parse_hex_bytes(data_hex)
        if not data or len(data) < 4 or data[0] != F1_MAGIC:
            continue
        try:
            frame_no = int(fr)
            t = float(t_rel)
            sp = int(sport)
            dp = int(dport)
        except Exception:
            continue
        addr_pairs.append((src, dst))
        parsed.append((frame_no, t, src, sp, dst, dp, data))

    if client_ip is None:
        client_ip = _infer_client_ip(addr_pairs, camera_ip=camera_ip)

    # Second pass: filter down to camera/client traffic.
    last_t: Optional[float] = None
    for frame_no, t, src, sp, dst, dp, data in parsed:
        op = data[1]
        body_len = (data[2] << 8) | data[3]
        body = data[4 : 4 + body_len]

        # Exclude external 0xF9 by default
        if op == 0xF9 and not include_f9:
            if src != camera_ip and dst != camera_ip:
                continue

        # Filter to "relevant" addresses:
        # - Anything to/from camera IP
        # - Broadcast frames if include_broadcast
        # - Optionally include external 0xF9 if it involves the inferred/declared client IP
        if src != camera_ip and dst != camera_ip:
            if op == 0xF9 and include_f9 and client_ip and (src == client_ip or dst == client_ip):
                pass
            elif include_broadcast and _is_broadcast_ip(dst):
                pass
            else:
                continue

        st: Optional[int] = None
        seq_lo: Optional[int] = None
        seq16: Optional[int] = None
        art_ver: Optional[int] = None
        art_typ: Optional[int] = None
        art_len: Optional[int] = None

        if op == 0xD0 and len(body) >= 2 and body[0] == 0xD1:
            st = body[1]
            if len(body) >= 4:
                seq_lo = body[3]
                seq16 = (body[2] << 8) | body[3]
        elif op == 0xD1:
            # ACK body is also D1-framed in practice; try to parse similarly.
            if len(body) >= 2 and body[0] == 0xD1:
                st = body[1]
                if len(body) >= 4:
                    seq_lo = body[3]
                    seq16 = (body[2] << 8) | body[3]

        art = _first_artemis_record(body)
        if art is not None:
            art_ver, art_typ, art_len, _payload = art

        direction = _direction(src, dst, camera_ip=camera_ip, client_ip=client_ip)
        if direction.endswith("broadcast") and not include_broadcast:
            continue

        delta = 0.0 if last_t is None else max(0.0, t - last_t)
        last_t = t

        summary = _summarize(op, st, body)
        yield Row(
            frame_no=frame_no,
            t_rel=t,
            t_delta=delta,
            src=src,
            sport=sp,
            dst=dst,
            dport=dp,
            direction=direction,
            opcode=_opcode_name(op),
            subtype=_subtype_name(st),
            seq_lo="" if seq_lo is None else str(seq_lo),
            seq16="" if seq16 is None else str(seq16),
            body_len=body_len,
            art_ver="" if art_ver is None else str(art_ver),
            art_typ="" if art_typ is None else str(art_typ),
            art_len="" if art_len is None else str(art_len),
            summary=summary,
        )


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Parse TrailCam UDP F1 protocol traffic from a PCAP and emit a scan-friendly CSV."
    )
    ap.add_argument("pcap", help="Path to pcap file")
    ap.add_argument(
        "-o",
        "--out",
        help="Output CSV path (default: stdout)",
        default="",
    )
    ap.add_argument(
        "--camera-ip",
        default="192.168.43.1",
        help="Camera IP (default: 192.168.43.1)",
    )
    ap.add_argument(
        "--client-ip",
        default="",
        help="Client IP (default: auto-detect from PCAP)",
    )
    ap.add_argument(
        "--include-f9",
        action="store_true",
        help="Include opcode 0xF9 packets (otherwise excluded when not to/from camera ip)",
    )
    ap.add_argument(
        "--include-broadcast",
        action="store_true",
        help="Include broadcast frames (e.g. opcode 0x30 to 192.168.43.255/255.255.255.255)",
    )
    args = ap.parse_args(argv)

    pcap_path = args.pcap
    if not os.path.exists(pcap_path):
        print(f"pcap not found: {pcap_path}", file=sys.stderr)
        return 2

    # Validate IPs early for nicer errors.
    try:
        ipaddress.ip_address(args.camera_ip)
    except Exception:
        print(f"invalid --camera-ip: {args.camera_ip}", file=sys.stderr)
        return 2

    client_ip = args.client_ip.strip() or None
    if client_ip is not None:
        try:
            ipaddress.ip_address(client_ip)
        except Exception:
            print(f"invalid --client-ip: {client_ip}", file=sys.stderr)
            return 2

    out_f = sys.stdout
    if args.out:
        out_f = open(args.out, "w", newline="", encoding="utf-8")

    try:
        w = csv.writer(out_f)
        w.writerow(
            [
                "frame",
                "t_rel_s",
                "t_delta_s",
                "src",
                "sport",
                "dst",
                "dport",
                "direction",
                "opcode",
                "subtype",
                "seq_lo",
                "seq16",
                "body_len",
                "art_ver",
                "art_typ",
                "art_len",
                "summary",
            ]
        )
        for r in iter_rows(
            pcap_path,
            camera_ip=args.camera_ip,
            client_ip=client_ip,
            include_f9=args.include_f9,
            include_broadcast=args.include_broadcast,
        ):
            w.writerow(
                [
                    r.frame_no,
                    f"{r.t_rel:.6f}",
                    f"{r.t_delta:.6f}",
                    r.src,
                    r.sport,
                    r.dst,
                    r.dport,
                    r.direction,
                    r.opcode,
                    r.subtype,
                    r.seq_lo,
                    r.seq16,
                    r.body_len,
                    r.art_ver,
                    r.art_typ,
                    r.art_len,
                    r.summary,
                ]
            )
    finally:
        if out_f is not sys.stdout:
            out_f.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
