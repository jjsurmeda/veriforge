"""UUIDv7 primary keys (TRD §13: time-sortable UUIDs, no extra dependency)."""

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    """RFC 9562 UUIDv7: 48-bit ms timestamp + random bits."""
    ts_ms = time.time_ns() // 1_000_000
    rand_a = int.from_bytes(os.urandom(2), "big") & 0x0FFF
    rand_b = int.from_bytes(os.urandom(8), "big") & 0x3FFFFFFFFFFFFFFF
    value = ts_ms << 80
    value |= 0x7 << 76  # version
    value |= rand_a << 64
    value |= 0b10 << 62  # RFC 4122 variant
    value |= rand_b
    return uuid.UUID(int=value)
