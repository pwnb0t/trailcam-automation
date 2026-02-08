import base64
import socket
import struct
import time
from pathlib import Path

MAGIC = 0xF1
OP_D0 = 0xD0
OP_D1 = 0xD1

CAMERA_IP = "192.168.43.1"
LOCAL_PORT = 3111

ARTEMIS = b"ARTEMIS\x00"

# These are the *request bodies* from your refresh PCAP (phone->camera).
# Wrap them with F1 framing when sending.
REQ_BODIES = [
    bytes.fromhex(
        "d1000011415254454d495300020000000b00010019000000"
        "4d7a6c423336582f49566f385a7a49357247396a31773d3d00"
    ),
    bytes.fromhex(
        "d1000012415254454d495300020000000c00010019000000"
        "4d7a6c423336582f49566f385a7a49357247396a31773d3d00"
    ),
    bytes.fromhex(
        "d1000013415254454d495300020000000600000059000000"
        "39305248304d6734504d6666594931664143796364504446764b52562f32327965695a6f44504b5246637947306a48376d6b5a43453136756378576347416f3334414f433465664f5a576d4f6b434d6d506b6e6f66413d3d00"
    ),
    bytes.fromhex(
        "d1000014415254454d495300020000000d00010019000000"
        "4d7a6c423336582f49566f385a7a49357247396a31773d3d00"
    ),
]

def pack_f1(opcode: int, body: bytes) -> bytes:
    return bytes([MAGIC, opcode]) + struct.pack(">H", len(body)) + body

def unpack_f1(pkt: bytes):
    if len(pkt) < 4 or pkt[0] != MAGIC:
        return None
    opcode = pkt[1]
    blen = struct.unpack(">H", pkt[2:4])[0]
    body = pkt[4:4+blen]
    return opcode, body

def make_ack_body(seqs):
    # Matches the observed style: d1 00 00 <count> + seq16 list
    seqs = sorted(set(seqs))
    count = len(seqs) & 0xFF
    seq16 = b"".join(struct.pack(">H", s) for s in seqs)
    return bytes([0xD1, 0x00, 0x00, count]) + seq16

def parse_artemis_records(data: bytes):
    records = []
    pos = 0
    while True:
        i = data.find(ARTEMIS, pos)
        if i == -1:
            break
        if i + 8 + 12 > len(data):
            break
        ver = int.from_bytes(data[i+8:i+12], "little")
        typ = int.from_bytes(data[i+12:i+16], "little")
        ln  = int.from_bytes(data[i+16:i+20], "little")
        b64 = data[i+20:i+20+ln]
        # base64 is ASCII; ignore trailing NULs after it
        b64 = b64.split(b"\x00")[0].strip()
        # pad if needed
        pad = (4 - (len(b64) % 4)) % 4
        decoded = base64.b64decode(b64 + b"=" * pad)
        records.append((ver, typ, ln, decoded))
        pos = i + 1
    return records

def refresh_gallery(out_dir="out", camera_port_guess=40611, timeout_s=6.0):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("0.0.0.0", LOCAL_PORT))
    s.settimeout(0.25)

    camera_port = camera_port_guess

    # Send the request bodies (as the app does)
    for body in REQ_BODIES:
        s.sendto(pack_f1(OP_D0, body), (CAMERA_IP, camera_port))
        time.sleep(0.02)

    chunks = {}
    start = time.time()
    last_ack = 0.0

    while time.time() - start < timeout_s:
        try:
            pkt, addr = s.recvfrom(65535)
        except socket.timeout:
            # periodic ACK if we have anything
            if chunks and (time.time() - last_ack) > 0.2:
                ack = pack_f1(OP_D1, make_ack_body(chunks.keys()))
                s.sendto(ack, (CAMERA_IP, camera_port))
                last_ack = time.time()
            continue

        if addr[0] == CAMERA_IP:
            camera_port = addr[1]  # learn session port

        parsed = unpack_f1(pkt)
        if not parsed:
            continue
        opcode, body = parsed
        if opcode != OP_D0:
            continue

        # Large response chunks: body starts with d1 00 00 <seq8>
        if len(body) >= 4 and body[0:3] == b"\xD1\x00\x00":
            seq = body[3]
            payload = body[4:]
            # keep first occurrence
            chunks.setdefault(seq, payload)

            if (time.time() - last_ack) > 0.1:
                ack = pack_f1(OP_D1, make_ack_body(chunks.keys()))
                s.sendto(ack, (CAMERA_IP, camera_port))
                last_ack = time.time()

            # Heuristic: once we have a contiguous run from 0x10 upward, try assemble
            seqs = sorted(chunks.keys())
            if seqs and seqs[0] == 0x10:
                # assemble in order
                assembled = b"".join(chunks[k] for k in seqs)
                if ARTEMIS in assembled:
                    records = parse_artemis_records(assembled)
                    if records:
                        # write outputs
                        (out / "assembled.bin").write_bytes(assembled)
                        for ver, typ, ln, decoded in records:
                            (out / f"artemis_v{ver}_type{typ}.bin").write_bytes(decoded)
                        return records

    raise TimeoutError(f"Did not complete refresh; got chunks={sorted(chunks.keys())}")

if __name__ == "__main__":
    recs = refresh_gallery()
    for ver, typ, ln, decoded in recs:
        print(f"ARTEMIS record: ver={ver} type={typ} b64_len={ln} decoded_len={len(decoded)}")
