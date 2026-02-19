from __future__ import annotations

from enum import StrEnum


class SyncStatus(StrEnum):
    PENDING = "pending"
    DOWNLOAD = "download"
    VERIFY = "verify"
    CLEAR = "clear"
    ORGANIZE = "organize"
    STAGED = "staged"
    DONE = "done"
    ERROR = "error"

