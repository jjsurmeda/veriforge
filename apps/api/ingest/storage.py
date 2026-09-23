"""Object storage for originals (TRD §9.1 step 1: store to S3).

Stage 1 runs the local-disk implementation; slice 9 adds an S3 adapter
behind this same interface and infra/cdk points at it (CLAUDE.md build
order — no AWS SDK calls before then).
"""

import asyncio
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from config import get_settings


class ObjectStore(Protocol):
    async def put(self, key: str, data: bytes) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...


class LocalObjectStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, key: str) -> Path:
        path = (self._root / key).resolve()
        if not path.is_relative_to(self._root.resolve()):
            raise ValueError(f"unsafe storage key: {key!r}")
        return path

    async def put(self, key: str, data: bytes) -> None:
        path = self._path(key)

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        await asyncio.to_thread(write)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, True)


@lru_cache
def get_object_store() -> ObjectStore:
    return LocalObjectStore(Path(get_settings().object_storage_dir))


def document_key(collection_id: object, sha256: str) -> str:
    return f"{collection_id}/{sha256}"
