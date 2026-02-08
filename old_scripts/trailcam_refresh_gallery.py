#!/usr/bin/env python3
import base64
import socket
import struct
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

MAGIC = 0xF1

OP_41 = 0x41
OP_D0 = 0xD0
OP_D1 = 0xD1
OP_E0 = 0xE0

CAMERA_IP = "192.168.43.1"

# Critical: in the connect PCAP, the app uses LOCAL_PORT=16734 for the session
LOCAL_PORT = 16734

ARTEMIS = b"ARTEMIS\x00"


def unpack_f1(pkt: bytes) -> Optional[Tuple[int, bytes, int]]:
    """
    Returns (opcode, body, body_len) or None if not an F1 packet.
    """
    if len(pkt) < 4 or pkt[0] != MAGIC:
        return None
    opcode = pkt[1]
    blen = struct.unpack("!H", pkt[2:4])[0]
    if len(pkt) < 4 + blen:
        return None
    body = pkt[4:4 + blen]
    return opcode, body, blen


def pack_f1(opcode: int, body: bytes) -> bytes:
    return bytes([MAGIC, opcode]) + struct.pack("!H", len(body)) + body


def make_ack_body(seqs8: List[int]) -> bytes:
    """
    ACK body format (matches observed behavior):
      d1 00 00 <count8> + list of seq16 BE
    Even though camera uses seq8 in D0 chunk header, ACK uses seq16.
    """
    seqs = sorted(set(seqs8))
    count = len(seqs) & 0xFF
    seq16 = b"".join(struct.pack(">H", s) for s in seqs)
    return bytes([0xD1, 0x00, 0x00, count]) + seq16


def parse_artemis_records(assembled: bytes):
    """
    Finds ARTEMIS\\x00 records inside assembled bytes.
    Record layout (observed):
      "ARTEMIS\\x00"
      uint32_le version
      uint32_le type
      uint32_le b64_len
      b64 bytes (b64_len)
      [NUL padding]
    Returns list of (ver, typ, decoded_bytes).
    """
    out = []
    pos = 0
    while True:
        i = assembled.find(ARTEMIS, pos)
        if i == -1:
            break
        if i + 8 + 12 > len(assembled):
            break
        ver = int.from_bytes(assembled[i + 8:i + 12], "little")
        typ = int.from_bytes(assembled[i + 12:i + 16], "little")
        ln = int.from_bytes(assembled[i + 16:i + 20], "little")
        b64 = assembled[i + 20:i + 20 + ln]
        # Trim padding NULs if any:
        b64 = b64.split(b"\x00")[0].strip()
        pad = (4 - (len(b64) % 4)) % 4
        decoded = base64.b64decode(b64 + b"=" * pad)
        out.append((ver, typ, decoded))
        pos = i + 1
    return out


class TrailCamSession:
    def __init__(self, timeout_s: float = 0.25):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", LOCAL_PORT))
        self.sock.settimeout(timeout_s)
        self.camera_addr: Optional[Tuple[str, int]] = None  # learned as (ip, port)

    def close(self):
        self.sock.close()

    def send_raw(self, payload: bytes):
        if not self.camera_addr:
            raise RuntimeError("Camera addr not learned yet")
        self.sock.sendto(payload, self.camera_addr)

    def send_f1(self, opcode: int, body: bytes):
        self.send_raw(pack_f1(opcode, body))

    def recv(self) -> Optional[Tuple[Tuple[str, int], bytes]]:
        try:
            data, addr = self.sock.recvfrom(65535)
            return addr, data
        except socket.timeout:
            return None

    def learn_camera_port(self, max_wait_s: float = 3.0) -> None:
        """
        Learn camera session port from first inbound UDP packet from 192.168.43.1.
        """
        deadline = time.time() + max_wait_s
        while time.time() < deadline:
            got = self.recv()
            if not got:
                continue
            addr, data = got
            if addr[0] != CAMERA_IP:
                continue
            # accept any inbound from camera as port-discovery
            self.camera_addr = addr
            return
        raise TimeoutError("Did not see any inbound UDP from camera to learn session port")

    def wait_and_echo_f1_41(self, max_wait_s: float = 3.0) -> None:
        """
        Wait for camera handshake F1 41 and echo it back.
        In the connect PCAP, the app sends it twice; we do the same.
        """
        if not self.camera_addr:
            raise RuntimeError("camera_addr not set")

        deadline = time.time() + max_wait_s
        while time.time() < deadline:
            got = self.recv()
            if not got:
                continue
            addr, data = got
            if addr[0] != CAMERA_IP:
                continue
            parsed = unpack_f1(data)
            if not parsed:
                continue
            opcode, body, _ = parsed
            if opcode == OP_41:
                # Echo back exactly as received (same body)
                self.send_f1(OP_41, body)
                time.sleep(0.02)
                self.send_f1(OP_41, body)
                return
        raise TimeoutError("Did not receive F1 41 handshake from camera")


def run_refresh_with_connect_fixtures(out_dir: str = "out",
                                     max_wait_s: float = 8.0) -> List[Tuple[int, int, bytes]]:
    """
    Replays the connect-prelude fixtures from trailcam_2-1-connect.pcap,
    then collects the resulting chunk stream and extracts ARTEMIS records.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    sess = TrailCamSession()
    try:
        # 1) Learn camera port (e.g. 40611)
        sess.learn_camera_port()

        # 2) Wait for handshake and echo F1 41
        sess.wait_and_echo_f1_41()

        # 3) Replay exact phone->camera fixtures from the connect PCAP
        # These are FULL F1 packets (already include F1 header).
        FIXTURE_PACKETS = [
            bytes.fromhex("f1e00000"),
            bytes.fromhex("f1e00000"),
            bytes.fromhex("f1e00000"),
            bytes.fromhex("f1d10006d10000010000"),
            bytes.fromhex("f1e00000"),
            bytes.fromhex(
                "f1d000c5"
                "d1000000"
                "415254454d4953"
                "0002000000"
                "21000000"
                "ad000000"
                "4a385757755144506d59534c66752f675841472b557162427935354b50326945323551504e6f667a6e3034302b4e493967377a65584c6b497058704330375358766f7372577363316d386d786e7136684d694b776550624b4a5577765376715a62367330736c3173667a692f3563525a746137586c30772f5a2b74345959397a57594143715232426c786473477a73636878734538476b57736f346c64735a6c614645716f797254416e413d"
                "00"
            ),
            bytes.fromhex("f1d10006d10000010001"),
            # D0 0x0045 repeated three times in the capture
            bytes.fromhex(
                "f1d00045"
                "d1000001"
                "415254454d4953"
                "0002000000"
                "22000000"
                "2d000000"
                "792b444462714d4e4e6e56354c446a7533786c4568647a387975482b69334b63747763627670667a4d73773d"
                "00"
            ),
            bytes.fromhex(
                "f1d00045"
                "d1000001"
                "415254454d4953"
                "0002000000"
                "22000000"
                "2d000000"
                "792b444462714d4e4e6e56354c446a7533786c4568647a387975482b69334b63747763627670667a4d73773d"
                "00"
            ),
            bytes.fromhex(
                "f1d00045"
                "d1000001"
                "415254454d4953"
                "0002000000"
                "22000000"
                "2d000000"
                "792b444462714d4e4e6e56354c446a7533786c4568647a387975482b69334b63747763627670667a4d73773d"
                "00"
            ),
        ]

        for p in FIXTURE_PACKETS:
            sess.send_raw(p)
            time.sleep(0.02)

        # 4) Receive D0 chunk stream; ACK with D1; assemble base64; decode ARTEMIS records
        chunks: Dict[int, bytes] = {}
        start = time.time()
        last_ack = 0.0

        while time.time() - start < max_wait_s:
            got = sess.recv()
            if not got:
                # periodic ACK if we have any chunks
                if chunks and (time.time() - last_ack) > 0.15:
                    sess.send_f1(OP_D1, make_ack_body(list(chunks.keys())))
                    last_ack = time.time()
                continue

            addr, data = got
            if addr[0] != CAMERA_IP:
                continue
            parsed = unpack_f1(data)
            if not parsed:
                continue
            opcode, body, _ = parsed

            if opcode == OP_D0 and len(body) >= 4 and body[0:3] == b"\xD1\x00\x00":
                seq = body[3]              # seq8 confirmed
                payload = body[4:]
                chunks.setdefault(seq, payload)

                if (time.time() - last_ack) > 0.10:
                    sess.send_f1(OP_D1, make_ack_body(list(chunks.keys())))
                    last_ack = time.time()

                # Try assembling whenever we have a run starting at 0x10
                seqs = sorted(chunks.keys())
                if seqs and seqs[0] == 0x10:
                    assembled_b64 = b"".join(chunks[s] for s in seqs)
                    assembled_b64 = b"".join(assembled_b64.split())  # remove whitespace
                    try:
                        assembled = base64.b64decode(assembled_b64, validate=False)
                    except Exception:
                        continue

                    if ARTEMIS in assembled:
                        (out / "assembled_from_chunks.bin").write_bytes(assembled)
                        recs = parse_artemis_records(assembled)
                        if recs:
                            for ver, typ, decoded in recs:
                                (out / f"artemis_v{ver}_type{typ}.bin").write_bytes(decoded)
                            return recs

        raise TimeoutError(f"Refresh did not complete; got chunks={sorted(chunks.keys())}")

    finally:
        sess.close()


if __name__ == "__main__":
    recs = run_refresh_with_connect_fixtures()
    for ver, typ, decoded in recs:
        print(f"ARTEMIS record: ver={ver} type={typ} decoded_len={len(decoded)}")
