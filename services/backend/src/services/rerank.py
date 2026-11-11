"""Optional DashScope reranking, preserving original documents on failure."""
from dataclasses import dataclass, field
import logging
import math
import os
import time
from urllib.parse import urlsplit

import httpx
from langchain_core.documents import Document

from src import config

logger = logging.getLogger(__name__)


@dataclass
class RerankResult:
    documents: list[Document]
    status: str
    reason: str | None
    elapsed_ms: float
    scores: list[float] = field(default_factory=list)
    usage_tokens: int | None = None

    def diagnostics(self) -> dict:
        return {"status": self.status, "reason": self.reason, "elapsed_ms": self.elapsed_ms,
                "scores": self.scores, "usage_tokens": self.usage_tokens}


class Reranker:
    def __init__(self, *, transport=None):
        self.transport = transport

    def rerank(self, query: str, documents: list[Document]) -> RerankResult:
        start = time.perf_counter()

        def finish(status, reason=None, ordered=None, scores=None, usage=None):
            if status == "fallback":
                # Do not log provider bodies, request text, endpoints or credentials.
                logger.warning("Rerank fallback: %s", reason)
            return RerankResult(list(documents) if ordered is None else ordered, status, reason,
                                (time.perf_counter() - start) * 1000, scores or [], usage)

        if len(documents) < 2:
            return finish("skipped", "insufficient_candidates")
        ids = [document.id for document in documents]
        if not all(ids) or len(set(ids)) != len(ids):
            return finish("fallback", "invalid_candidates")
        key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
        if not key or key == "your_dashscope_api_key_here":
            return finish("fallback", "not_configured")
        try:
            url = urlsplit(config.rerank_url)
            url.port
        except ValueError:
            return finish("fallback", "invalid_endpoint")
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
            return finish("fallback", "invalid_endpoint")
        try:
            sizes = [len(document.page_content.encode("utf-8")) for document in documents]
            query_size = len(query.encode("utf-8"))
        except UnicodeError:
            return finish("fallback", "invalid_text")
        if (not query.strip() or len(documents) > 500 or not all(sizes)
                or max(query_size, *sizes) > 4000
                or query_size * len(documents) + sum(sizes) > 120000):
            return finish("fallback", "input_budget")
        timeout = httpx.Timeout(config.rerank_timeout, connect=min(1.0, config.rerank_timeout))
        try:
            with httpx.Client(timeout=timeout, follow_redirects=False, transport=self.transport) as client:
                response = client.post(config.rerank_url,
                    headers={"Authorization": "Bearer " + key},
                    json={"model": config.rerank_model,
                          "input": {"query": query, "documents": [d.page_content for d in documents]},
                          "parameters": {"top_n": len(documents), "return_documents": False}})
        except httpx.TimeoutException:
            return finish("fallback", "timeout")
        except (httpx.HTTPError, httpx.InvalidURL):
            return finish("fallback", "transport_error")
        if response.status_code != 200:
            return finish("fallback", "http_" + str(response.status_code))
        try:
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("code"):
                return finish("fallback", "provider_error")
            results = payload["output"]["results"]
            if not isinstance(results, list) or len(results) != len(documents):
                raise ValueError("Incomplete ranking")
            scored = {}
            for item in results:
                index, score = item["index"], item["relevance_score"]
                if (type(index) is not int or not 0 <= index < len(documents) or index in scored
                        or type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1):
                    raise ValueError("Invalid ranking")
                scored[index] = float(score)
            order = sorted(scored, key=lambda index: (-scored[index], index))
            usage_data = payload.get("usage")
            usage = usage_data.get("total_tokens") if isinstance(usage_data, dict) else None
            if type(usage) is not int or usage < 0:
                usage = None
        except (KeyError, TypeError, ValueError, AttributeError):
            return finish("fallback", "invalid_response")
        return finish("success", ordered=[documents[index] for index in order],
                      scores=[scored[index] for index in order], usage=usage)
