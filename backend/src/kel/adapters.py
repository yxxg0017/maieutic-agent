"""模型与检索适配层。

LangGraph 节点只依赖这里的 Protocol，不直接依赖任何供应商 SDK。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class ModelError(RuntimeError):
    """模型调用失败。错误信息不得包含密钥或原始请求。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class ModelRequest:
    system: str
    user: str
    temperature: float = 0.4
    max_tokens: int = 2048
    timeout_s: float = 60.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelEvent:
    kind: str  # "delta" | "done"
    text: str = ""


class ChatModelAdapter(Protocol):
    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]: ...

    async def structured(self, request: ModelRequest, schema: type[T]) -> T: ...


@dataclass
class SearchQuery:
    text: str
    limit: int = 5


@dataclass
class RetrievedSource:
    title: str
    locator: str
    snippet: str
    tier: str = "secondary"
    version: str | None = None


class RetrievalAdapter(Protocol):
    async def search(self, query: SearchQuery) -> list[RetrievedSource]: ...


# ------------------------------------------------------------------ OpenAI 兼容


class OpenAICompatibleAdapter:
    """任何 OpenAI-compatible /chat/completions 服务。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._client = client

    def _http(self, timeout: float) -> httpx.AsyncClient:
        return self._client or httpx.AsyncClient(timeout=timeout)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _body(self, request: ModelRequest, *, stream: bool, json_mode: bool) -> dict:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": stream,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        return body

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        client = self._http(request.timeout_s)
        owns_client = self._client is None
        try:
            async with client.stream(
                "POST",
                f"{self._base_url}/chat/completions",
                headers=self._headers(),
                json=self._body(request, stream=True, json_mode=False),
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise ModelError(
                        "model_http_error",
                        f"模型服务返回 {response.status_code}",
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {}).get("content")
                    if delta:
                        yield ModelEvent(kind="delta", text=delta)
            yield ModelEvent(kind="done")
        except httpx.HTTPError as exc:  # 网络层错误统一脱敏
            raise ModelError("model_unreachable", "无法连接模型服务") from exc
        finally:
            if owns_client:
                await client.aclose()

    async def structured(self, request: ModelRequest, schema: type[T]) -> T:
        client = self._http(request.timeout_s)
        owns_client = self._client is None
        last_error: Exception | None = None
        instruction = (
            f"{request.system}\n\n只输出满足以下 JSON Schema 的 JSON 对象，不要额外文本：\n"
            f"{json.dumps(schema.model_json_schema(), ensure_ascii=False)}"
        )
        try:
            for attempt in range(3):  # 最多重试两次
                try:
                    response = await client.post(
                        f"{self._base_url}/chat/completions",
                        headers=self._headers(),
                        json=self._body(
                            ModelRequest(
                                system=instruction,
                                user=request.user,
                                temperature=request.temperature,
                                max_tokens=request.max_tokens,
                            ),
                            stream=False,
                            json_mode=True,
                        ),
                    )
                    if response.status_code >= 400:
                        raise ModelError(
                            "model_http_error", f"模型服务返回 {response.status_code}"
                        )
                    content = response.json()["choices"][0]["message"]["content"]
                    return schema.model_validate_json(content)
                except (ValidationError, json.JSONDecodeError, KeyError) as exc:
                    last_error = exc
                except httpx.HTTPError as exc:
                    last_error = exc
                    if attempt == 2:
                        raise ModelError("model_unreachable", "无法连接模型服务") from exc
            raise ModelError("model_invalid_output", "模型结构化输出校验失败") from last_error
        finally:
            if owns_client:
                await client.aclose()


# ------------------------------------------------------------------ 离线可测适配器


class ScriptedAdapter:
    """确定性适配器。用于测试、离线模式与缺少密钥时的降级。

    `structured` 按 `ModelRequest.metadata["contract"]` 查找预设响应；未命中时
    抛出 `ModelError`，以便节点走显式降级路径而不是编造内容。
    """

    def __init__(
        self,
        structured_responses: dict[str, Any] | None = None,
        stream_text: str = "（离线模式）未配置模型服务，以下为本地可用信息摘要。",
    ) -> None:
        self.structured_responses = structured_responses or {}
        self.stream_text = stream_text
        self.calls: list[tuple[str, str]] = []

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        self.calls.append((request.metadata.get("contract", "stream"), request.user))
        for piece in self.stream_text.split("。"):
            if piece:
                yield ModelEvent(kind="delta", text=piece + "。")
        yield ModelEvent(kind="done")

    async def structured(self, request: ModelRequest, schema: type[T]) -> T:
        contract = request.metadata.get("contract", "")
        self.calls.append((contract, request.user))
        if contract not in self.structured_responses:
            raise ModelError("model_unavailable", f"无预设响应：{contract}")
        payload = self.structured_responses[contract]
        if callable(payload):
            payload = payload(request)
        return schema.model_validate(payload)


class LocalChunkRetrieval:
    """仅检索本地附件切片，不发出任何网络请求。

    中文没有空格，因此同时使用拉丁词和 CJK 二元组作为匹配项。
    """

    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self._chunks = chunks

    @staticmethod
    def _terms(text: str) -> list[str]:
        lowered = text.lower()
        latin = [t for t in re.findall(r"[a-z0-9_]{2,}", lowered)]
        cjk_runs = re.findall(r"[\u4e00-\u9fff]{2,}", lowered)
        bigrams = [
            run[i : i + 2] for run in cjk_runs for i in range(len(run) - 1)
        ]
        return latin + bigrams

    async def search(self, query: SearchQuery) -> list[RetrievedSource]:
        terms = self._terms(query.text)
        scored: list[tuple[int, dict[str, Any]]] = []
        for chunk in self._chunks:
            text = chunk["text"].lower()
            score = sum(text.count(term) for term in terms)
            if score:
                scored.append((score, chunk))
        if not scored:
            # 跨语言提问（中文问题 + 英文论文）时词面匹配为零。用户既然导入了资料，
            # 就不能返回空让流程退化成"无来源"，而是给出最近导入资料的开头片段。
            scored = [(0, chunk) for chunk in self._recent_chunks(query.limit)]
        scored.sort(key=lambda item: (-item[0], item[1]["locator"]))
        return [
            RetrievedSource(
                title=chunk.get("filename", chunk["locator"]),
                locator=chunk["locator"],
                snippet=chunk["text"][:600],
                tier="primary",
            )
            for _, chunk in scored[: query.limit]
        ]

    def _recent_chunks(self, limit: int) -> list[dict[str, Any]]:
        """最近导入附件的前若干片段。chunks 按导入顺序排列，取末尾的附件。"""
        if not self._chunks:
            return []
        last_attachment = self._chunks[-1]["attachment_id"]
        same = [c for c in self._chunks if c["attachment_id"] == last_attachment]
        return same[: max(1, limit)]


class PaperRetrieval:
    """论文检索。会把检索词发往 arXiv / OpenAlex，因此必须由用户显式启用。

    摘要来自论文自身，算 `primary`；但"拿到摘要"不等于"读过全文"，
    需要全文时由用户执行下载命令，下载后才作为附件切片进入检索。
    """

    def __init__(self, enabled: bool = True, limit: int = 6) -> None:
        self.enabled = enabled
        self.limit = limit
        self.last_error: str | None = None

    async def search(self, query: SearchQuery) -> list[RetrievedSource]:
        if not self.enabled:
            return []
        import asyncio

        from .papers import PaperError, search as search_papers

        try:
            refs = await asyncio.to_thread(
                search_papers, query.text, min(query.limit, self.limit)
            )
        except PaperError as exc:
            self.last_error = str(exc)
            return []
        return [
            RetrievedSource(
                title=ref.title,
                locator=ref.locator,
                snippet=(ref.summary or ref.one_line())[:600],
                tier="primary",
                version=ref.published[:10] or None,
            )
            for ref in refs
        ]


class CompositeRetrieval:
    """本地资料优先并保留固定席位，再补外部来源；单个后端失败不影响其他后端。

    不保留席位时，外部检索的摘要会把用户刚导入的资料挤出来源列表。
    """

    def __init__(self, backends: list[RetrievalAdapter], local_share: float = 0.6) -> None:
        self._backends = backends
        self._local_share = local_share

    async def search(self, query: SearchQuery) -> list[RetrievedSource]:
        budget = max(query.limit, 1)
        reserved = max(1, int(budget * self._local_share))
        results: list[RetrievedSource] = []
        seen: set[str] = set()
        for index, backend in enumerate(self._backends):
            quota = reserved if index == 0 else budget - len(results)
            if quota <= 0:
                break
            try:
                found = await backend.search(SearchQuery(text=query.text, limit=quota))
            except Exception:
                continue  # 降级由调用方通过来源为空来感知
            for item in found[:quota]:
                if item.locator in seen:
                    continue
                seen.add(item.locator)
                results.append(item)
        return results[:budget]
