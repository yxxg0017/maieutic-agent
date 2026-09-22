"""论文检索与下载。

只使用无需密钥的公开 API：arXiv（Atom）与 OpenAlex（JSON）。
两者都只接收检索词，不接收用户的本地文件内容。
下载限制大小与类型，落盘后复用 `ingest` 切片，来源等级为 primary。
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx

ARXIV_API = "https://export.arxiv.org/api/query"
OPENALEX_API = "https://api.openalex.org/works"
USER_AGENT = "maieutic-agent/0.1 (local research assistant)"
MAX_PDF_BYTES = 40 * 1024 * 1024
ATOM = "{http://www.w3.org/2005/Atom}"


class PaperError(RuntimeError):
    """检索或下载失败。消息面向用户，不含密钥或内部路径。"""


@dataclass
class PaperRef:
    source: str  # "arxiv" | "openalex"
    identifier: str  # arXiv id 或 DOI
    title: str
    authors: list[str] = field(default_factory=list)
    published: str = ""
    summary: str = ""
    pdf_url: str | None = None
    landing_url: str | None = None
    venue: str = ""
    citations: int | None = None

    @property
    def locator(self) -> str:
        return f"{self.source}:{self.identifier}"

    @property
    def filename(self) -> str:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", self.identifier)[:80]
        return f"{self.source}_{safe}.pdf"

    def one_line(self) -> str:
        authors = "、".join(self.authors[:3]) + ("等" if len(self.authors) > 3 else "")
        bits = [self.published[:10], authors, self.venue]
        meta = " · ".join(b for b in bits if b)
        return f"{self.title}\n{meta}"


def _client(timeout: float) -> httpx.Client:
    return httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


def _text(node: Any, tag: str) -> str:
    found = node.find(f"{ATOM}{tag}")
    return (found.text or "").strip() if found is not None else ""


def parse_arxiv_atom(payload: str) -> list[PaperRef]:
    """解析 arXiv Atom 响应。字段缺失时跳过该条，不猜测。"""
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise PaperError("arXiv 返回内容无法解析") from exc

    refs: list[PaperRef] = []
    for entry in root.findall(f"{ATOM}entry"):
        raw_id = _text(entry, "id")
        identifier = raw_id.rsplit("/abs/", 1)[-1] if "/abs/" in raw_id else raw_id
        title = " ".join(_text(entry, "title").split())
        if not identifier or not title:
            continue
        pdf_url = None
        for link in entry.findall(f"{ATOM}link"):
            if link.get("title") == "pdf" or link.get("type") == "application/pdf":
                pdf_url = link.get("href")
        refs.append(
            PaperRef(
                source="arxiv",
                identifier=identifier,
                title=title,
                authors=[
                    _text(author, "name")
                    for author in entry.findall(f"{ATOM}author")
                    if _text(author, "name")
                ],
                published=_text(entry, "published"),
                summary=" ".join(_text(entry, "summary").split()),
                pdf_url=pdf_url or f"https://arxiv.org/pdf/{identifier}",
                landing_url=raw_id or None,
            )
        )
    return refs


def parse_openalex(payload: dict[str, Any]) -> list[PaperRef]:
    """解析 OpenAlex works 响应。只保留有标题的条目。"""
    refs: list[PaperRef] = []
    for work in payload.get("results", []):
        title = (work.get("title") or work.get("display_name") or "").strip()
        doi = (work.get("doi") or "").replace("https://doi.org/", "")
        identifier = doi or (work.get("id") or "").rsplit("/", 1)[-1]
        if not title or not identifier:
            continue
        best = work.get("best_oa_location") or work.get("primary_location") or {}
        venue = ((best.get("source") or {}).get("display_name")) or ""
        refs.append(
            PaperRef(
                source="openalex",
                identifier=identifier,
                title=title,
                authors=[
                    (author.get("author") or {}).get("display_name", "")
                    for author in (work.get("authorships") or [])[:8]
                    if (author.get("author") or {}).get("display_name")
                ],
                published=work.get("publication_date") or "",
                summary=work.get("abstract") or "",
                pdf_url=best.get("pdf_url"),
                landing_url=best.get("landing_page_url") or work.get("id"),
                venue=venue,
                citations=work.get("cited_by_count"),
            )
        )
    return refs


RETRY_STATUS = (406, 429, 500, 502, 503, 504)
RETRY_DELAY_S = 5.0  # arXiv 对突发请求返回 406，需要数秒级礼让间隔


def _get_with_retry(
    client: httpx.Client, url: str, attempts: int = 3, delay: float = RETRY_DELAY_S
) -> httpx.Response:
    """arXiv 对突发请求会返回 406；按指数退避重试，仍失败才报错。"""
    last: httpx.Response | None = None
    for attempt in range(attempts):
        response = client.get(url)
        if response.status_code not in RETRY_STATUS:
            response.raise_for_status()
            return response
        last = response
        if attempt < attempts - 1:
            time.sleep(delay * (1 + 2 * attempt))  # 5s、15s
    assert last is not None
    last.raise_for_status()
    return last


def arxiv_url(query: str, limit: int = 8) -> str:
    """构造 arXiv 查询 URL。

    arXiv 对 `search_query` 中被百分号编码的冒号返回 406，因此 `:` 必须保持原样。
    """
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max(1, min(limit, 50)),
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    return f"{ARXIV_API}?{urlencode(params, safe=':')}"


def search_arxiv(query: str, limit: int = 8, timeout: float = 20.0) -> list[PaperRef]:
    try:
        with _client(timeout) as client:
            response = _get_with_retry(client, arxiv_url(query, limit))
            return parse_arxiv_atom(response.text)
    except httpx.HTTPError as exc:
        raise PaperError("无法访问 arXiv") from exc


def search_openalex(query: str, limit: int = 8, timeout: float = 20.0) -> list[PaperRef]:
    params = {
        "search": query,
        "per-page": max(1, min(limit, 50)),
        "sort": "relevance_score:desc",
    }
    try:
        with _client(timeout) as client:
            response = _get_with_retry(
                client, f"{OPENALEX_API}?{urlencode(params)}"
            )
            return parse_openalex(response.json())
    except httpx.HTTPError as exc:
        raise PaperError("无法访问 OpenAlex") from exc
    except ValueError as exc:
        raise PaperError("OpenAlex 返回内容无法解析") from exc


@dataclass
class SearchOutcome:
    """检索结果与各来源的失败原因。任一来源失败不影响其他来源。"""

    refs: list[PaperRef] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


def search_with_outcome(query: str, limit: int = 8) -> SearchOutcome:
    outcome = SearchOutcome()
    seen: set[str] = set()

    for name, fetch in (("arxiv", search_arxiv), ("openalex", search_openalex)):
        if len(outcome.refs) >= limit:
            break
        try:
            found = fetch(query, limit=limit - len(outcome.refs))
        except PaperError as exc:
            outcome.errors[name] = str(exc)
            continue
        for ref in found:
            key = ref.title.lower()
            if key in seen:
                continue
            seen.add(key)
            outcome.refs.append(ref)
    outcome.refs = outcome.refs[:limit]
    return outcome


def search(query: str, limit: int = 8) -> list[PaperRef]:
    """arXiv 优先（可直接拿到 PDF），OpenAlex 补充非预印本。

    arXiv 对突发请求限流较严；它失败时仍返回 OpenAlex 的结果，只有两者都失败才报错。
    """
    outcome = search_with_outcome(query, limit)
    if not outcome.refs and outcome.errors:
        raise PaperError("；".join(outcome.errors.values()))
    return outcome.refs


def download_pdf(ref: PaperRef, timeout: float = 60.0) -> bytes:
    """下载 PDF。仅允许 https，限制大小，校验内容类型。"""
    url = ref.pdf_url
    if not url:
        raise PaperError(f"该条目没有可下载的 PDF：{ref.locator}")
    if not url.startswith("https://"):
        raise PaperError("仅允许通过 https 下载")
    try:
        with _client(timeout) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > MAX_PDF_BYTES:
                        raise PaperError("PDF 超过大小上限，未保存")
                    chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise PaperError("下载失败") from exc

    data = b"".join(chunks)
    if not data.startswith(b"%PDF") and "pdf" not in content_type:
        raise PaperError("下载内容不是 PDF，已丢弃")
    return data
