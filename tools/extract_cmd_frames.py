#!/usr/bin/env python3
"""Extract and decrypt command JSON from PCAP payloads.

Two heuristics:
1) EVC_ frame scan (20-byte header, payload_len at +0x10, base64 payload)
2) Base64-run scan (find base64-like substrings, try AES decrypt, validate JSON)

AES: CBC, key "xs38nul7cqf7m1va", IV=0, zero padding.
"""
import argparse
import base64
import binascii
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Tuple

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

KEY = b"xs38nul7cqf7m1va"
IV = b"\x00" * 16

BASE64_RE = re.compile(rb"[A-Za-z0-9+/=]{24,4096}")

@dataclass
class Packet:
    frame: int
    payload: bytes


def run_tshark(pcap: str) -> List[Tuple[int, str, str, str, str, bytes]]:
    cmd = [
        "tshark",
        "-r",
        pcap,
        "-T",
        "fields",
        "-e",
        "frame.number",
        "-e",
        "ip.src",
        "-e",
        "ip.dst",
        "-e",
        "tcp.srcport",
        "-e",
        "tcp.dstport",
        "-e",
        "udp.srcport",
        "-e",
        "udp.dstport",
        "-e",
        "data",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip())
    out = []
    for line in proc.stdout.splitlines():
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 8:
            continue
        frame_s, src, dst, tcp_sport, tcp_dport, udp_sport, udp_dport, data_hex = parts[:8]
        if not data_hex:
            continue
        try:
            payload = binascii.unhexlify(data_hex)
        except binascii.Error:
            continue
        sport = tcp_sport or udp_sport
        dport = tcp_dport or udp_dport
        if not sport or not dport:
            continue
        try:
            frame = int(frame_s)
        except ValueError:
            continue
        out.append((frame, src, dst, sport, dport, payload))
    return out


def decrypt_payload(ct: bytes) -> bytes:
    if len(ct) % 16 != 0:
        return b""
    cipher = Cipher(algorithms.AES(KEY), modes.CBC(IV), backend=default_backend())
    dec = cipher.decryptor()
    pt = dec.update(ct) + dec.finalize()
    return pt


def looks_like_json(pt: bytes) -> bool:
    s = pt.lstrip(b"\x00 \t\r\n")
    if not s.startswith(b"{"):
        return False
    return b"cmdId" in s or b"token" in s or b"getMediaListRet" in s


def scan_evc(stream: bytes) -> List[Tuple[int, str]]:
    results = []
    idx = 0
    while True:
        pos = stream.find(b"EVC_", idx)
        if pos == -1:
            break
        if pos + 20 > len(stream):
            break
        header = stream[pos:pos+20]
        payload_len = int.from_bytes(header[0x10:0x14], "little", signed=False)
        if payload_len <= 0 or payload_len > 1024 * 1024:
            idx = pos + 1
            continue
        start = pos + 0x14
        end = start + payload_len
        if end > len(stream):
            idx = pos + 1
            continue
        b64 = stream[start:end]
        if b"\x00" in b64:
            b64 = b64.split(b"\x00", 1)[0]
        try:
            ct = base64.b64decode(b64)
        except Exception:
            idx = pos + 1
            continue
        pt = decrypt_payload(ct).rstrip(b"\x00")
        if looks_like_json(pt):
            results.append((pos, pt.decode("utf-8", errors="replace")))
        idx = pos + 1
    return results


def scan_base64(stream: bytes) -> List[Tuple[int, str]]:
    results = []
    for m in BASE64_RE.finditer(stream):
        b64 = m.group(0)
        # avoid massive false positives
        if len(b64) < 24 or len(b64) % 4 != 0:
            continue
        try:
            ct = base64.b64decode(b64)
        except Exception:
            continue
        pt = decrypt_payload(ct)
        if looks_like_json(pt):
            results.append((m.start(), pt.rstrip(b"\x00").decode("utf-8", errors="replace")))
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pcap", help="pcap file path")
    ap.add_argument("--min-flow-bytes", type=int, default=256, help="minimum concatenated payload size")
    ap.add_argument("--scan-base64", action="store_true", help="also scan for base64-encoded encrypted JSON")
    args = ap.parse_args()

    rows = run_tshark(args.pcap)
    flows: Dict[str, List[Packet]] = defaultdict(list)

    for frame, src, dst, sport, dport, payload in rows:
        flow_id = f"{src}:{sport}->{dst}:{dport}"
        flows[flow_id].append(Packet(frame=frame, payload=payload))

    total_hits = 0
    for flow_id, packets in flows.items():
        packets.sort(key=lambda p: p.frame)
        stream = b"".join(p.payload for p in packets)
        if len(stream) < args.min_flow_bytes:
            continue

        evc_hits = scan_evc(stream)
        b64_hits = scan_base64(stream) if args.scan_base64 else []

        if evc_hits or b64_hits:
            total_hits += len(evc_hits) + len(b64_hits)
            print(f"FLOW {flow_id} bytes={len(stream)} EVC_hits={len(evc_hits)} B64_hits={len(b64_hits)}")
            for off, text in evc_hits:
                print(f"  EVC offset={off}")
                print(text)
                print("---")
            for off, text in b64_hits:
                print(f"  B64 offset={off}")
                print(text)
                print("---")

    if total_hits == 0:
        print("No command JSON found with current heuristics.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
