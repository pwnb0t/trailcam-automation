"""Legacy flows shim.

Phase 2: implementation split into focused modules while preserving the legacy
import surface used by callers/tests.
"""

from src.protocol import unpack_f1

from src.flows.common import _media_dir_path, _media_file_path, _session_media_root
from src.flows.media_list import (
    _collect_media_entries,
    _is_photo_entry,
    _is_video_entry,
    fetch_media_list_page,
    normalize_media_entry,
)
from src.flows.photo_download import (
    download_photo_to_out,
    download_photo_to_out_item,
    send_photo_download_flow,
)
from src.flows.video_download import (
    _is_sentinel_video_frame,
    _order_seq16_from_anchor,
    _parse_artemis_v4_payload_header,
    _seq16_forward_delta,
    _seq16_missing_from_anchor,
    send_video_download_flow,
    send_video_download_flow_item,
)

__all__ = [
    "_media_dir_path",
    "_media_file_path",
    "_session_media_root",
    "send_photo_download_flow",
    "download_photo_to_out_item",
    "download_photo_to_out",
    "_parse_artemis_v4_payload_header",
    "_is_sentinel_video_frame",
    "_seq16_forward_delta",
    "_order_seq16_from_anchor",
    "_seq16_missing_from_anchor",
    "send_video_download_flow_item",
    "send_video_download_flow",
    "_collect_media_entries",
    "normalize_media_entry",
    "_is_video_entry",
    "_is_photo_entry",
    "fetch_media_list_page",
]
