"""Flows package shim.

Phase 1 split: keep behavior identical by housing the historical implementation
in flows.legacy and re-exporting the same API from src.flows.
"""

from .legacy import *  # noqa: F401,F403
from .legacy import _collect_media_entries, _is_photo_entry, _is_video_entry, _parse_artemis_v4_payload_header
