"""Score Memory candidates through a caller-owned asynchronous HTTP client."""

from __future__ import annotations

import math
from heapq import nsmallest
from typing import TYPE_CHECKING

from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision, _validate_bounds
from powercontext.builtin.inference import InferenceUsage

if TYPE_CHECKING:
    import httpx

    from powercontext.builtin.artifacts.memory.models import MemoryHit


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError("HTTP reranker response contains duplicate JSON fields")
    return fields


def _batch_scores(payload: object, expected: set[int]) -> dict[int, int | float]:
    if not isinstance(payload, dict) or payload.keys() != {"scores"} or not isinstance(payload["scores"], list):
        raise ValueError("HTTP reranker response must contain only a scores array")
    scores: dict[int, int | float] = {}
    for item in payload["scores"]:
        if not isinstance(item, dict) or item.keys() != {"rank", "score"}:
            raise ValueError("HTTP reranker score must contain exactly rank and score")
        rank, score = item["rank"], item["score"]
        if type(rank) is not int or rank not in expected or rank in scores:
            raise ValueError("HTTP reranker returned an invalid or repeated batch rank")
        if type(score) not in (int, float) or (type(score) is float and not math.isfinite(score)):
            raise ValueError("HTTP reranker score must be a finite number")
        scores[rank] = score
    if scores.keys() != expected:
        raise ValueError("HTTP reranker did not score every rank in the batch")
    return scores


class HTTPMemoryReranker:
    """Select original Memory ranks using comparable scores across HTTP batches."""

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = "http-cross-encoder-v1",
    ) -> None:
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError("rerank batch_size must be a positive integer")
        self._endpoint = endpoint
        self._client = client
        self._batch_size = batch_size
        self.policy_id = policy_id

    async def rerank(
        self,
        query: str,
        candidates: tuple[MemoryHit, ...],
        limit: int,
    ) -> MemoryRerankDecision:
        if type(limit) is not int:
            raise ValueError("rerank limit must be an integer")
        _validate_bounds(len(candidates), limit)
        scores: dict[int, int | float] = {}
        requests = 0
        for start in range(0, len(candidates), self._batch_size):
            end = min(start + self._batch_size, len(candidates))
            ranks = range(start + 1, end + 1)
            response = await self._client.post(
                self._endpoint,
                json={
                    "query": query,
                    "candidates": [{"rank": rank, "text": candidates[rank - 1].text} for rank in ranks],
                },
            )
            requests += 1
            response.raise_for_status()
            scores.update(_batch_scores(response.json(object_pairs_hook=_unique_fields), set(ranks)))

        ordered = nsmallest(limit, scores, key=lambda rank: (-scores[rank], rank))
        return MemoryRerankDecision(selected_ranks=tuple(ordered), usage=InferenceUsage(requests=requests))
