import base64
import json
import struct
from typing import Dict, List, Optional, Tuple

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from constants import AES_CMD_IV, AES_CMD_KEY


def unpack_f1(pkt: bytes) -> Optional[Tuple[int, bytes, int]]:
    if len(pkt) < 4 or pkt[0] != 0xF1:
        return None
    opcode = pkt[1]
    blen = struct.unpack("!H", pkt[2:4])[0]
    if len(pkt) < 4 + blen:
        return None
    body = pkt[4 : 4 + blen]
    return opcode, body, blen


def make_ack_body_seq8_with_subtype(subtype: int, seqs8: List[int]) -> bytes:
    seqs = sorted(set(seqs8))
    count = len(seqs) & 0xFF
    seq16 = b"".join(struct.pack(">H", s) for s in seqs)
    return bytes([0xD1, subtype & 0xFF, 0x00, count]) + seq16


def make_ack_body_seq8_window(subtype: int, seqs8_ordered: List[int]) -> bytes:
    count = min(len(seqs8_ordered), 0xFF)
    seq16 = b"".join(struct.pack(">H", s & 0xFFFF) for s in seqs8_ordered[-count:])
    return bytes([0xD1, subtype & 0xFF, 0x00, count]) + seq16


def make_ack_body_seq8(seqs8: List[int]) -> bytes:
    return make_ack_body_seq8_with_subtype(0x00, seqs8)


def make_ack_body_seq16(seqs16: List[int]) -> bytes:
    seqs = sorted(set(seqs16))
    count = len(seqs) & 0xFF
    seq16 = b"".join(struct.pack(">H", s) for s in seqs)
    return bytes([0xD1, 0x04, 0x00, count]) + seq16


def parse_artemis_records(assembled: bytes):
    out = []
    pos = 0
    while True:
        i = assembled.find(b"ARTEMIS\x00", pos)
        if i == -1:
            break
        if i + 20 > len(assembled):
            break
        ver = int.from_bytes(assembled[i + 8 : i + 12], "little")
        typ = int.from_bytes(assembled[i + 12 : i + 16], "little")
        ln = int.from_bytes(assembled[i + 16 : i + 20], "little")
        payload = assembled[i + 20 : i + 20 + ln]
        out.append((ver, typ, payload))
        pos = i + 1
    return out


def parse_artemis_records_strict(assembled: bytes):
    """Parse ARTEMIS records by advancing to the end of each record.

    The download data channels can contain repeated/multiple ARTEMIS records back-to-back.
    Using an overlapping scan (pos=i+1) can create false matches and corrupt extraction.
    """
    out = []
    pos = 0
    while True:
        i = assembled.find(b"ARTEMIS\x00", pos)
        if i == -1:
            break
        if i + 20 > len(assembled):
            break
        ver = int.from_bytes(assembled[i + 8 : i + 12], "little")
        typ = int.from_bytes(assembled[i + 12 : i + 16], "little")
        ln = int.from_bytes(assembled[i + 16 : i + 20], "little")
        j = i + 20 + ln
        if ln <= 0 or j > len(assembled):
            pos = i + 1
            continue
        payload = assembled[i + 20 : j]
        out.append((ver, typ, payload))
        pos = j
    return out


def _pad16(b: bytes) -> bytes:
    pad = (-len(b)) % 16
    if pad:
        b += b"\x00" * pad
    return b


def encrypt_cmd_json(obj: Dict) -> bytes:
    js = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    pt = _pad16(js)
    cipher = Cipher(algorithms.AES(AES_CMD_KEY), modes.CBC(AES_CMD_IV), backend=default_backend())
    enc = cipher.encryptor()
    ct = enc.update(pt) + enc.finalize()
    return base64.b64encode(ct)


def decrypt_cmd_b64(b64: bytes) -> Optional[Dict]:
    def try_decode(candidate: bytes) -> Optional[Dict]:
        try:
            ct = base64.b64decode(candidate)
        except Exception:
            return None
        if len(ct) % 16 != 0:
            ct = ct[: len(ct) - (len(ct) % 16)]
            if not ct:
                return None
        cipher = Cipher(algorithms.AES(AES_CMD_KEY), modes.CBC(AES_CMD_IV), backend=default_backend())
        dec = cipher.decryptor()
        pt = dec.update(ct) + dec.finalize()
        pt = pt.rstrip(b"\x00")
        start = pt.find(b"{")
        end = pt.rfind(b"}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            return json.loads(pt[start : end + 1].decode("utf-8", errors="replace"))
        except Exception:
            return None

    try:
        allowed = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
        cleaned = bytearray()
        for ch in b64:
            if ch in allowed:
                cleaned.append(ch)
            elif cleaned:
                break
        b64 = bytes(cleaned).strip()
        if not b64:
            return None
    except Exception:
        return None

    candidates = [b64]
    if b"=" in b64:
        candidates.append(b64[: b64.rfind(b"=") + 1])
    if len(b64) % 4 != 0:
        candidates.append(b64[: len(b64) - (len(b64) % 4)])

    for cand in candidates:
        obj = try_decode(cand)
        if obj:
            return obj

    try:
        import re

        for m in re.findall(rb"[A-Za-z0-9+/=]{32,}", b64):
            extra = [m]
            if b"=" in m:
                extra.append(m[: m.rfind(b"=") + 1])
            for cand in extra:
                obj = try_decode(cand)
                if obj:
                    return obj
    except Exception:
        pass
    return None


def decrypt_payload_b64_bytes(payload: bytes) -> Optional[Dict]:
    # Similar to decrypt_cmd_b64 but works on raw ARTEMIS payload bytes
    try:
        if b"\x00" in payload:
            payload = payload.split(b"\x00", 1)[0]
        allowed = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
        cleaned = bytearray()
        for ch in payload:
            if ch in allowed:
                cleaned.append(ch)
            elif cleaned:
                break
        if not cleaned:
            return None
        b64 = bytes(cleaned)
        pad = (-len(b64)) % 4
        b64 += b"=" * pad
        ct = base64.b64decode(b64)
    except Exception:
        return None
    if len(ct) % 16 != 0:
        ct = ct[: len(ct) - (len(ct) % 16)]
        if not ct:
            return None
    cipher = Cipher(algorithms.AES(AES_CMD_KEY), modes.CBC(AES_CMD_IV), backend=default_backend())
    dec = cipher.decryptor()
    pt = dec.update(ct) + dec.finalize()
    pt = pt.rstrip(b"\x00")
    start = pt.find(b"{")
    end = pt.rfind(b"}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(pt[start : end + 1].decode("utf-8", errors="replace"))
    except Exception:
        return None


def build_artemis_record(payload_b64: bytes, ver: int, typ: int) -> bytes:
    header = b"ARTEMIS\x00"
    header += struct.pack("<I", ver)
    header += struct.pack("<I", typ)
    header += struct.pack("<I", len(payload_b64))
    return header + payload_b64


def decrypt_artemis_json(body: bytes) -> List[Dict]:
    out: List[Dict] = []
    if len(body) >= 4 and body[0] == 0xD1:
        body = body[4:]
    records = parse_artemis_records(body)
    for _ver, _typ, payload in records:
        obj = decrypt_cmd_b64(payload)
        if obj:
            out.append(obj)
    return out
