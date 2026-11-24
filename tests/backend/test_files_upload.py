"""Upload endpoint streams chunks and cleans up oversized partial files."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.app.api import files


class FakeUpload:
    def __init__(self, chunks):
        self.filename = "a.jpg"
        self._chunks = list(chunks)
        self.read_sizes = []
        self.closed = False

    async def read(self, size=-1):
        self.read_sizes.append(size)
        return self._chunks.pop(0) if self._chunks else b""

    async def close(self):
        self.closed = True


def test_upload_streams_in_chunks(monkeypatch, tmp_path):
    monkeypatch.setattr(files, "_media_dir", lambda: tmp_path)
    upload = FakeUpload([b"a" * 10, b"b" * 20])

    result = asyncio.run(files.upload_file(upload, SimpleNamespace(id=7)))

    output = tmp_path / result["file_name"]
    assert output.is_file()
    assert output.read_bytes() == b"a" * 10 + b"b" * 20
    assert result["size"] == 30
    assert upload.read_sizes == [files.UPLOAD_CHUNK_SIZE] * 3
    assert upload.closed is True


def test_upload_removes_partial_file_when_over_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(files, "_media_dir", lambda: tmp_path)
    monkeypatch.setattr(files, "MAX_UPLOAD_SIZE", 20)
    upload = FakeUpload([b"a" * 15, b"b" * 15])

    with pytest.raises(HTTPException) as exc:
        asyncio.run(files.upload_file(upload, SimpleNamespace(id=7)))

    assert exc.value.status_code == 400
    assert list(tmp_path.iterdir()) == []
    assert upload.closed is True
