"""导入解析：类型白名单、大小限制与定位符。"""

from __future__ import annotations

import pytest

from kel.ingest import MAX_BYTES, IngestError, store_attachment


def test_text_is_chunked_with_locators(tmp_path):
    record, chunks = store_attachment(
        session_id="sess_1",
        filename="notes.md",
        data=("段落一\n\n" + "段落二\n\n" + "x" * 3000).encode(),
        attachments_dir=tmp_path,
    )
    assert record["sha256"] and record["size"] > 0
    assert len(chunks) >= 2
    assert all(c["locator"].startswith("attachment:notes.md:") for c in chunks)


def test_unsupported_suffix_is_rejected(tmp_path):
    with pytest.raises(IngestError):
        store_attachment(
            session_id="s", filename="a.docx", data=b"x", attachments_dir=tmp_path
        )


def test_oversized_file_is_rejected(tmp_path):
    with pytest.raises(IngestError):
        store_attachment(
            session_id="s",
            filename="a.txt",
            data=b"x" * (MAX_BYTES + 1),
            attachments_dir=tmp_path,
        )


def test_same_content_is_stored_once(tmp_path):
    first, _ = store_attachment(
        session_id="s", filename="a.txt", data=b"hello", attachments_dir=tmp_path
    )
    second, _ = store_attachment(
        session_id="s", filename="a.txt", data=b"hello", attachments_dir=tmp_path
    )
    assert first["stored_path"] == second["stored_path"]
