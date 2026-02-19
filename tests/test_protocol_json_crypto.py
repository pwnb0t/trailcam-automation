import os
import sys
import unittest


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.protocol import (  # noqa: E402
    build_artemis_record,
    decrypt_artemis_json,
    decrypt_cmd_b64,
    decrypt_payload_b64_bytes,
    encrypt_cmd_json,
)


class TestProtocolJsonCrypto(unittest.TestCase):
    def test_encrypt_then_decrypt_cmd_b64_roundtrip(self):
        obj = {"cmdId": 768, "pageNo": 0, "itemCntPerPage": 48, "token": 123456}
        b64 = encrypt_cmd_json(obj)
        dec = decrypt_cmd_b64(b64)
        self.assertIsNotNone(dec)
        self.assertEqual(dec["cmdId"], 768)
        self.assertEqual(dec["pageNo"], 0)
        self.assertEqual(dec["itemCntPerPage"], 48)
        self.assertEqual(dec["token"], 123456)

    def test_decrypt_payload_b64_bytes_tolerates_null_suffix(self):
        obj = {"cmdId": 0, "result": 0, "token": 98765}
        b64 = encrypt_cmd_json(obj) + b"\x00garbage"
        dec = decrypt_payload_b64_bytes(b64)
        self.assertIsNotNone(dec)
        self.assertEqual(dec["cmdId"], 0)
        self.assertEqual(dec["token"], 98765)

    def test_decrypt_artemis_json_from_d1_wrapped_body(self):
        obj = {"cmdId": 773, "result": 0, "delRet": 0}
        payload_b64 = encrypt_cmd_json(obj)
        art = build_artemis_record(payload_b64, ver=2, typ=4)
        body = b"\xD1\x00\x00\x01" + art
        out = decrypt_artemis_json(body)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["cmdId"], 773)
        self.assertEqual(out[0]["delRet"], 0)


if __name__ == "__main__":
    unittest.main()

