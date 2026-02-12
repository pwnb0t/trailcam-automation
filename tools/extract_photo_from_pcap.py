#!/usr/bin/env python3
"""Extract photo-like JPEG payloads from TrailCam download traffic in a PCAP.

This targets the high-volume camera->client D0 subtype 0x03 stream observed
during cmdId=1285 download flows.
"""

import argparse
import binascii
import struct
import subprocess
from pathlib import Path
from typing import Iterable, List, Tuple


def tshark_rows(pcap: str, src: str, dst: str) -> Iterable[Tuple[int, bytes]]:
    cmd = [
        "tshark",
        "-r",
        pcap,
        "-Y",
        f"ip.src=={src} && ip.dst=={dst} && udp && data",
        "-T",
        "fields",
        "-e",
        "frame.number",
        "-e",
        "data",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "tshark failed")
    for line in proc.stdout.splitlines():
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        try:
            frame = int(parts[0])
            payload = binascii.unhexlify(parts[1])
        except Exception:
            continue
        yield frame, payload


def extract_d0_subtype_chunks(
    pcap: str, src: str, dst: str, subtype: int
) -> List[Tuple[int, int, bytes]]:
    chunks: List[Tuple[int, int, bytes]] = []
    for frame, pkt in tshark_rows(pcap, src, dst):
        if len(pkt) < 8 or pkt[0] != 0xF1 or pkt[1] != 0xD0:
            continue
        body_len = struct.unpack("!H", pkt[2:4])[0]
        if len(pkt) < 4 + body_len:
            continue
        body = pkt[4 : 4 + body_len]
        if len(body) < 4 or body[0] != 0xD1 or body[1] != subtype:
            continue
        seq = body[3]
        chunks.append((frame, seq, body[4:]))
    return chunks


def carve_jpegs(blob: bytes) -> List[bytes]:
    """Carve candidate JPEGs using both nearest-EOI and wide-span strategies."""
    sois: List[int] = []
    eois: List[int] = []
    i = 0
    while True:
        i = blob.find(b"\xff\xd8\xff", i)
        if i == -1:
            break
        sois.append(i)
        i += 1
    j = 0
    while True:
        j = blob.find(b"\xff\xd9", j)
        if j == -1:
            break
        eois.append(j)
        j += 1

    out: List[bytes] = []
    if not sois or not eois:
        return out

    # Wide-span candidate often carries the full frame in this protocol.
    out.append(blob[sois[0] : eois[-1] + 2])

    for s in sois:
        e = next((x for x in eois if x > s), None)
        if e is None:
            continue
        out.append(blob[s : e + 2])
    # De-duplicate equal candidates while preserving order.
    uniq: List[bytes] = []
    seen = set()
    for c in out:
        h = hash(c)
        if h in seen:
            continue
        seen.add(h)
        uniq.append(c)
    return uniq


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pcap", help="Input PCAP")
    ap.add_argument("--src", required=True, help="Camera IP")
    ap.add_argument("--dst", required=True, help="Client IP")
    ap.add_argument("--subtype", type=lambda x: int(x, 0), default=0x03, help="D0 subtype (default: 0x03)")
    ap.add_argument("--out-dir", default="out/extract", help="Output directory")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    chunks = extract_d0_subtype_chunks(args.pcap, args.src, args.dst, args.subtype)
    if not chunks:
        print("No matching D0 subtype chunks found.")
        return 1

    blob = b"".join(c for _, _, c in chunks)
    seq_hist = {}
    for _, seq, _ in chunks:
        seq_hist[seq] = seq_hist.get(seq, 0) + 1

    raw_path = out_dir / f"subtype_{args.subtype:02x}_raw.bin"
    raw_path.write_bytes(blob)

    print(f"chunks={len(chunks)} bytes={len(blob)} seq_unique={len(seq_hist)} raw={raw_path}")

    cands = carve_jpegs(blob)
    if not cands:
        print("No JPEG markers found.")
        return 2

    # Persist all carved candidates; print largest first.
    sizes = sorted([(len(c), i, c) for i, c in enumerate(cands, 1)], reverse=True)
    for size, i, data in sizes:
        path = out_dir / f"carved_{i:03d}_{size}.jpg"
        path.write_bytes(data)
    largest = sizes[0]
    print(f"carved={len(cands)} largest={largest[0]} -> carved_{{id}}_{{size}}.jpg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
