"""资料导入与解析。不执行文件中的脚本、宏或嵌入对象。"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

MAX_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 300
CHUNK_CHARS = 1200
TEXT_SUFFIXES = {
    ".txt", ".md", ".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go", ".java",
    ".c", ".h", ".cpp", ".cs", ".json", ".toml", ".yaml", ".yml", ".sql", ".sh",
}


class IngestError(ValueError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _chunk(text: str) -> list[str]:
    paragraphs = re.split(r"\n\s*\n", text)
    chunks: list[str] = []
    buffer = ""
    for paragraph in paragraphs:
        if len(buffer) + len(paragraph) + 2 > CHUNK_CHARS and buffer:
            chunks.append(buffer.strip())
            buffer = ""
        buffer += paragraph.strip() + "\n\n"
    if buffer.strip():
        chunks.append(buffer.strip())
    return [c for c in chunks if c]


def parse_pdf(path: Path) -> list[tuple[str, str]]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if len(reader.pages) > MAX_PDF_PAGES:
        raise IngestError(f"PDF 页数超过上限 {MAX_PDF_PAGES}")
    out: list[tuple[str, str]] = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        for index, chunk in enumerate(_chunk(text)):
            out.append((f"p{page_number}#{index}", chunk))
    return out


def parse_text(path: Path) -> list[tuple[str, str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return [(f"#{i}", chunk) for i, chunk in enumerate(_chunk(text))]


def store_attachment(
    *,
    session_id: str,
    filename: str,
    data: bytes,
    attachments_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """保存原始文件并解析为切片。返回 (attachment 记录, chunks)。"""
    if len(data) > MAX_BYTES:
        raise IngestError(f"文件超过上限 {MAX_BYTES // (1024 * 1024)}MB")
    suffix = Path(filename).suffix.lower()
    if suffix != ".pdf" and suffix not in TEXT_SUFFIXES:
        raise IngestError(f"MVP 不支持的文件类型：{suffix or '未知'}")

    digest = sha256_bytes(data)
    session_dir = attachments_dir / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    stored_path = session_dir / f"{digest}{suffix}"
    if not stored_path.exists():
        stored_path.write_bytes(data)

    attachment_id = f"att_{digest[:16]}"
    try:
        pieces = parse_pdf(stored_path) if suffix == ".pdf" else parse_text(stored_path)
    except IngestError:
        raise
    except Exception as exc:
        raise IngestError("文件解析失败") from exc

    chunks = [
        {
            "chunk_id": f"{attachment_id}:{locator}",
            "ordinal": ordinal,
            "locator": f"attachment:{filename}:{locator}",
            "text": text,
        }
        for ordinal, (locator, text) in enumerate(pieces)
    ]
    record = {
        "attachment_id": attachment_id,
        "session_id": session_id,
        "filename": filename,
        "mime": "application/pdf" if suffix == ".pdf" else "text/plain",
        "size": len(data),
        "sha256": digest,
        "stored_path": str(stored_path),
    }
    return record, chunks
