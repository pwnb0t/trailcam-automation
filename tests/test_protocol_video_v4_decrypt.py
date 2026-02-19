import os
import sys
import unittest

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.constants import AES_CMD_IV, AES_CMD_KEY  # noqa: E402
from src.protocol import (  # noqa: E402
    V4_PAGE_AES_CBC_PREFIX_LEN,
    V4_PAGE_SIZE,
    decrypt_v4_media_data_pages,
)


def _aes_cbc_encrypt(data: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(AES_CMD_KEY), modes.CBC(AES_CMD_IV), backend=default_backend())
    enc = cipher.encryptor()
    return enc.update(data) + enc.finalize()


def _build_stream_ciphertext_from_plaintext(plain: bytes) -> bytes:
    """Build synthetic ver=4 media data using native page-prefix encryption behavior."""
    out = bytearray(plain)
    for off in range(0, len(out), V4_PAGE_SIZE):
        # Match native behavior: only encrypt when remaining bytes > 0x5f.
        if (len(out) - off) <= 0x5F:
            continue
        prefix = bytes(out[off : off + V4_PAGE_AES_CBC_PREFIX_LEN])
        out[off : off + V4_PAGE_AES_CBC_PREFIX_LEN] = _aes_cbc_encrypt(prefix)
    return bytes(out)


class TestProtocolVideoV4Decrypt(unittest.TestCase):
    def test_decrypt_v4_pages_skips_short_tail_pages(self):
        # Tail remainder is 0x50 (< 0x60). Native behavior does not decrypt this tail.
        plain = bytes((i % 251) for i in range(V4_PAGE_SIZE + 0x50))
        cipher = _build_stream_ciphertext_from_plaintext(plain)
        dec = decrypt_v4_media_data_pages(cipher)
        self.assertEqual(dec, plain)

    def test_decrypt_v4_pages_decrypts_boundary_tail_of_exactly_0x60(self):
        # Tail remainder is exactly 0x60; this must be decrypted.
        plain = bytes(((i * 7) % 256) for i in range(V4_PAGE_SIZE + 0x60))
        cipher = _build_stream_ciphertext_from_plaintext(plain)
        dec = decrypt_v4_media_data_pages(cipher)
        self.assertEqual(dec, plain)

    def test_decrypt_v4_pages_handles_small_buffer_without_changes(self):
        # Entire payload is <= 0x5f: no decrypt work should happen.
        plain = bytes(range(0x40))
        dec = decrypt_v4_media_data_pages(plain)
        self.assertEqual(dec, plain)


if __name__ == "__main__":
    unittest.main()

