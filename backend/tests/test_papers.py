"""论文检索解析与下载限制。默认不联网：用固定样本与 monkeypatch 验证。"""

from __future__ import annotations

import pytest

from kel.adapters import CompositeRetrieval, PaperRetrieval, RetrievedSource, SearchQuery
from kel.papers import PaperError, PaperRef, download_pdf, parse_arxiv_atom, parse_openalex

ATOM_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.01234v2</id>
    <published>2024-01-02T10:00:00Z</published>
    <title>Retrieval-Augmented
      Generation for Long Documents</title>
    <summary>We study how   retrieval affects long-context reasoning.</summary>
    <author><name>Ada Lovelace</name></author>
    <author><name>Alan Turing</name></author>
    <link href="http://arxiv.org/abs/2401.01234v2" rel="alternate" type="text/html"/>
    <link href="http://arxiv.org/pdf/2401.01234v2" rel="related" title="pdf"
          type="application/pdf"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2402.00001v1</id>
    <title></title>
  </entry>
</feed>
"""

OPENALEX_SAMPLE = {
    "results": [
        {
            "id": "https://openalex.org/W123",
            "doi": "https://doi.org/10.1145/3612345",
            "title": "Interactive Clarification with Expected Information Gain",
            "publication_date": "2023-06-15",
            "cited_by_count": 42,
            "authorships": [{"author": {"display_name": "Grace Hopper"}}],
            "best_oa_location": {
                "pdf_url": "https://example.org/paper.pdf",
                "landing_page_url": "https://example.org/paper",
                "source": {"display_name": "CHI"},
            },
        },
        {"id": "https://openalex.org/W999", "title": ""},
    ]
}


def test_parse_arxiv_collapses_whitespace_and_finds_pdf():
    refs = parse_arxiv_atom(ATOM_SAMPLE)
    assert len(refs) == 1  # 无标题条目被跳过
    ref = refs[0]
    assert ref.identifier == "2401.01234v2"
    assert ref.title == "Retrieval-Augmented Generation for Long Documents"
    assert ref.authors == ["Ada Lovelace", "Alan Turing"]
    assert ref.pdf_url.endswith("2401.01234v2")
    assert ref.locator == "arxiv:2401.01234v2"
    assert "retrieval affects" in ref.summary


def test_parse_arxiv_rejects_garbage():
    with pytest.raises(PaperError):
        parse_arxiv_atom("<not xml")


def test_parse_openalex_extracts_doi_and_venue():
    refs = parse_openalex(OPENALEX_SAMPLE)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.identifier == "10.1145/3612345"
    assert ref.venue == "CHI"
    assert ref.citations == 42
    assert ref.locator == "openalex:10.1145/3612345"


def test_download_requires_https():
    ref = PaperRef(source="arxiv", identifier="1", title="t", pdf_url="http://x/y.pdf")
    with pytest.raises(PaperError, match="https"):
        download_pdf(ref)


def test_download_without_pdf_url_is_rejected():
    ref = PaperRef(source="openalex", identifier="10.1/x", title="t", pdf_url=None)
    with pytest.raises(PaperError):
        download_pdf(ref)


def test_paper_retrieval_disabled_makes_no_request(monkeypatch):
    def explode(*_args, **_kwargs):  # pragma: no cover - 不应被调用
        raise AssertionError("未启用时不得联网")

    monkeypatch.setattr("kel.papers.search", explode)
    adapter = PaperRetrieval(enabled=False)
    import asyncio

    assert asyncio.run(adapter.search(SearchQuery(text="rag", limit=3))) == []


def test_paper_retrieval_maps_refs_to_primary_sources(monkeypatch):
    refs = parse_arxiv_atom(ATOM_SAMPLE)
    monkeypatch.setattr("kel.papers.search", lambda query, limit: refs)
    import asyncio

    results = asyncio.run(PaperRetrieval().search(SearchQuery(text="rag", limit=3)))
    assert [r.locator for r in results] == ["arxiv:2401.01234v2"]
    assert results[0].tier == "primary"
    assert results[0].version == "2024-01-02"


def test_paper_retrieval_failure_degrades_to_empty(monkeypatch):
    def fail(query, limit):
        raise PaperError("无法访问 arXiv")

    monkeypatch.setattr("kel.papers.search", fail)
    import asyncio

    adapter = PaperRetrieval()
    assert asyncio.run(adapter.search(SearchQuery(text="rag"))) == []
    assert adapter.last_error == "无法访问 arXiv"


class _Fake:
    def __init__(self, items: list[RetrievedSource], boom: bool = False) -> None:
        self.items = items
        self.boom = boom

    async def search(self, query: SearchQuery) -> list[RetrievedSource]:
        if self.boom:
            raise RuntimeError("backend down")
        return self.items


def test_composite_prefers_local_and_survives_backend_failure():
    import asyncio

    local = _Fake([RetrievedSource("本地", "attachment:a.md:#0", "x", "primary")])
    broken = _Fake([], boom=True)
    remote = _Fake(
        [
            RetrievedSource("论文", "arxiv:1", "y", "primary"),
            RetrievedSource("重复", "attachment:a.md:#0", "z", "primary"),
        ]
    )
    composite = CompositeRetrieval([local, broken, remote])
    results = asyncio.run(composite.search(SearchQuery(text="q", limit=5)))
    assert [r.locator for r in results] == ["attachment:a.md:#0", "arxiv:1"]


def test_composite_reserves_slots_for_local_sources():
    """外部检索的摘要不能把用户刚导入的资料挤出来源列表。"""
    import asyncio

    local = _Fake(
        [
            RetrievedSource(f"本地{i}", f"attachment:paper.pdf:p{i}#0", "x", "primary")
            for i in range(6)
        ]
    )
    remote = _Fake(
        [RetrievedSource(f"论文{i}", f"openalex:{i}", "y", "primary") for i in range(10)]
    )
    results = asyncio.run(
        CompositeRetrieval([local, remote]).search(SearchQuery(text="q", limit=6))
    )
    local_hits = [r for r in results if r.locator.startswith("attachment:")]
    assert len(local_hits) >= 3  # 60% 席位留给本地
    assert len(results) == 6


def test_local_retrieval_falls_back_to_recent_attachment_on_language_mismatch():
    """中文提问 + 英文论文时词面匹配为零，仍须返回刚导入的资料。"""
    import asyncio

    from kel.adapters import LocalChunkRetrieval

    chunks = [
        {
            "attachment_id": "att_old",
            "locator": "attachment:old.md:#0",
            "text": "unrelated english text",
            "filename": "old.md",
        },
        *[
            {
                "attachment_id": "att_new",
                "locator": f"attachment:paper.pdf:p{i}#0",
                "text": f"Retrieval augmented generation page {i}",
                "filename": "paper.pdf",
            }
            for i in range(4)
        ],
    ]
    results = asyncio.run(
        LocalChunkRetrieval(chunks).search(SearchQuery(text="用刚导入的论文说明机制", limit=3))
    )
    assert results, "不能返回空来源"
    assert all(r.locator.startswith("attachment:paper.pdf") for r in results)


def test_local_retrieval_still_prefers_term_matches():
    import asyncio

    from kel.adapters import LocalChunkRetrieval

    chunks = [
        {
            "attachment_id": "att_1",
            "locator": "attachment:a.md:#0",
            "text": "生成器 惰性求值 说明",
            "filename": "a.md",
        },
        {
            "attachment_id": "att_2",
            "locator": "attachment:b.md:#0",
            "text": "完全无关的内容",
            "filename": "b.md",
        },
    ]
    results = asyncio.run(
        LocalChunkRetrieval(chunks).search(SearchQuery(text="惰性求值", limit=2))
    )
    assert results[0].locator == "attachment:a.md:#0"
