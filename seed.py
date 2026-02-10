import base64
from typing import Dict, List, Optional

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from constants import AES_CMD_IV, AES_CMD_KEY, CONNECT_D0_PACKETS
from protocol import decrypt_cmd_b64, parse_artemis_records


def get_seed_thumbnail_reqs() -> Optional[List[Dict]]:
    seq8_chunks: Dict[int, bytes] = {}
    for pkt in CONNECT_D0_PACKETS:
        if len(pkt) < 8 or pkt[0] != 0xF1 or pkt[1] != 0xD0:
            continue
        blen = int.from_bytes(pkt[2:4], "big")
        body = pkt[4 : 4 + blen]
        if len(body) < 4 or body[0] != 0xD1 or body[1] != 0x00:
            continue
        seq8 = body[3]
        seq8_chunks[seq8] = body[4:]

    if not seq8_chunks:
        return None

    assembled = b"".join(seq8_chunks[k] for k in sorted(seq8_chunks))
    for _ver, _typ, payload in parse_artemis_records(assembled):
        obj = decrypt_cmd_b64(payload)
        if obj and obj.get("cmdId") == 772 and "thumbnailReqs" in obj:
            return obj["thumbnailReqs"]

        if payload.find(b"{") == -1:
            try:
                import re

                allowed = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
                b64 = bytearray()
                for ch in payload:
                    if ch in allowed:
                        b64.append(ch)
                    elif b64:
                        break
                if not b64:
                    continue

                plaintext = None
                for trim in range(4):
                    cand = bytes(b64[: len(b64) - trim]) if trim else bytes(b64)
                    pad = (-len(cand)) % 4
                    cand = cand + b"=" * pad
                    try:
                        ct = base64.b64decode(cand)
                    except Exception:
                        continue
                    if len(ct) % 16 != 0:
                        ct = ct[: len(ct) - (len(ct) % 16)]
                    if not ct:
                        continue
                    cipher = Cipher(
                        algorithms.AES(AES_CMD_KEY),
                        modes.CBC(AES_CMD_IV),
                        backend=default_backend(),
                    )
                    pt = cipher.decryptor().update(ct) + cipher.decryptor().finalize()
                    plaintext = pt.decode("utf-8", errors="ignore")
                    break

                if not plaintext:
                    continue

                reqs = []
                for m in re.finditer(
                    r'\{"fileType":(\d+),"dirNum":(\d+),"mediaNum":(\d+)\}',
                    plaintext,
                ):
                    reqs.append(
                        {
                            "fileType": int(m.group(1)),
                            "dirNum": int(m.group(2)),
                            "mediaNum": int(m.group(3)),
                        }
                    )
                if reqs:
                    return reqs
            except Exception:
                continue
    return None
