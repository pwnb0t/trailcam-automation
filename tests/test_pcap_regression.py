import binascii
import os
import shutil
import struct
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.flows.video_download import _parse_artemis_v4_payload_header  # noqa: E402
from src.protocol import parse_artemis_records_strict, unpack_f1  # noqa: E402


def _tshark_rows(pcap: Path, display_filter: str) -> list[bytes]:
    cmd = [
        "tshark",
        "-r",
        str(pcap),
        "-Y",
        display_filter,
        "-T",
        "fields",
        "-e",
        "data",
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or "tshark failed")
    out: list[bytes] = []
    for line in p.stdout.splitlines():
        hexs = line.strip()
        if not hexs:
            continue
        try:
            out.append(binascii.unhexlify(hexs))
        except Exception:
            continue
    return out


def _assemble_d0_subtype_stream_seq16(pcap: Path, subtype: int, camera_ip: str = "192.168.43.1") -> bytes:
    rows = _tshark_rows(pcap, f"ip.src=={camera_ip} && udp && data")
    seq_to_chunk: dict[int, bytes] = {}
    for pkt in rows:
        parsed = unpack_f1(pkt)
        if not parsed:
            continue
        opcode, body, _ = parsed
        if opcode != 0xD0 or len(body) < 4 or body[0] != 0xD1 or body[1] != subtype:
            continue
        seq16 = struct.unpack(">H", body[2:4])[0]
        # Keep first-seen packet for deterministic reconstruction.
        if seq16 not in seq_to_chunk:
            seq_to_chunk[seq16] = body[4:]
    if not seq_to_chunk:
        return b""
    return b"".join(seq_to_chunk[s] for s in sorted(seq_to_chunk))


def _largest_jpeg_from_artemis_payloads(blob: bytes) -> bytes | None:
    best: bytes | None = None
    for _ver, _typ, payload in parse_artemis_records_strict(blob):
        data = payload[72:] if len(payload) >= 75 and payload[72:75] == b"\xff\xd8\xff" else payload
        soi = data.find(b"\xff\xd8\xff")
        eoi = data.rfind(b"\xff\xd9")
        if soi == -1 or eoi == -1 or eoi <= soi:
            continue
        jpg = data[soi : eoi + 2]
        if best is None or len(jpg) > len(best):
            best = jpg
    return best


@unittest.skipUnless(shutil.which("tshark"), "tshark is required for pcap regression tests")
class TestPcapRegression(unittest.TestCase):
    def test_photo_download_pcap_extracts_large_jpeg(self):
        pcap = REPO_ROOT / "pcap" / "trailcam_10-connect-thru-download-photo.pcap"
        self.assertTrue(pcap.exists(), f"fixture pcap missing: {pcap}")

        assembled = _assemble_d0_subtype_stream_seq16(pcap, subtype=0x03)
        self.assertGreater(len(assembled), 100000, "expected non-trivial subtype=0x03 stream")

        jpg = _largest_jpeg_from_artemis_payloads(assembled)
        self.assertIsNotNone(jpg, "no JPEG found in photo download stream")
        assert jpg is not None
        self.assertTrue(jpg.startswith(b"\xff\xd8\xff"))
        self.assertTrue(jpg.endswith(b"\xff\xd9"))
        self.assertGreater(len(jpg), 800_000, "photo payload unexpectedly small")

    def test_video_download_pcap_v4_record_profile(self):
        pcap = REPO_ROOT / "pcap" / "trailcam_8-3-view-and-download-video.pcap"
        self.assertTrue(pcap.exists(), f"fixture pcap missing: {pcap}")

        assembled = _assemble_d0_subtype_stream_seq16(pcap, subtype=0x02)
        self.assertGreater(len(assembled), 1_000_000, "expected non-trivial subtype=0x02 stream")

        v_cnt = 0
        a_cnt = 0
        for ver, _typ, payload in parse_artemis_records_strict(assembled):
            if ver != 4:
                continue
            hdr = _parse_artemis_v4_payload_header(payload)
            if not hdr:
                continue
            if hdr["data_len_off"] == 16 and hdr["width"] and hdr["height"]:
                v_cnt += 1
            elif hdr["data_len_off"] == 20 and hdr["width"] == 0 and hdr["height"] == 0:
                a_cnt += 1

        # Known-good profile for this capture.
        self.assertEqual(v_cnt, 304)
        self.assertEqual(a_cnt, 157)


if __name__ == "__main__":
    unittest.main()
