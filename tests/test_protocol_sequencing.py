import os
import struct
import sys
import unittest


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.protocol import (  # noqa: E402
    make_ack_body_seq_list16,
    make_ack_body_seq_window16,
    parse_artemis_records_strict,
    unpack_f1,
)


class TestProtocolSequencing(unittest.TestCase):
    def test_make_ack_body_seq_list16_sorts_and_dedupes(self):
        body = make_ack_body_seq_list16(0x03, [10, 2, 10, 1])
        self.assertEqual(body[:4], bytes([0xD1, 0x03, 0x00, 0x03]))
        self.assertEqual(body[4:], struct.pack(">HHH", 1, 2, 10))

    def test_make_ack_body_seq_window16_keeps_last_seen_unique_order(self):
        # Last-seen unique values are [1, 3, 2] in stable order.
        body = make_ack_body_seq_window16(0x02, [1, 2, 1, 3, 2])
        self.assertEqual(body[:4], bytes([0xD1, 0x02, 0x00, 0x03]))
        self.assertEqual(body[4:], struct.pack(">HHH", 1, 3, 2))

    def test_unpack_f1_valid_packet(self):
        pkt = bytes([0xF1, 0xD0, 0x00, 0x04, 0xD1, 0x02, 0x00, 0x01])
        parsed = unpack_f1(pkt)
        self.assertIsNotNone(parsed)
        opcode, body, blen = parsed
        self.assertEqual(opcode, 0xD0)
        self.assertEqual(blen, 4)
        self.assertEqual(body, b"\xD1\x02\x00\x01")

    def test_parse_artemis_records_strict_no_overlap_false_positive(self):
        # Payload contains embedded ARTEMIS marker bytes; strict parser must not
        # split on these embedded bytes.
        payload = b"abcARTEMIS\x00xyz"
        rec = (
            b"ARTEMIS\x00"
            + struct.pack("<I", 4)
            + struct.pack("<I", 2)
            + struct.pack("<I", len(payload))
            + payload
        )
        records = parse_artemis_records_strict(rec)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0][0], 4)
        self.assertEqual(records[0][1], 2)
        self.assertEqual(records[0][2], payload)


if __name__ == "__main__":
    unittest.main()

