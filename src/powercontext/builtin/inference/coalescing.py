"""Share overlapping embedding requests and cache successful vectors."""

from __future__ import annotations

import asyncio
import math
from collections import OrderedDict
from dataclasses import dataclass

from powercontext.builtin.inference.models import EmbeddingResult, EmbeddingVector, InferenceUsage
from powercontext.builtin.inference.protocols import EmbeddingModel


@dataclass(frozen=True, slots=True)
class _VectorResult:
    vector: EmbeddingVector
    batch: object | None = None
    usage: InferenceUsage | None = None


def _observe_failure(future: asyncio.Future[_VectorResult]) -> None:
    # An abandoned request can still fail after its last caller was cancelled.
    if not future.cancelled():
        future.exception()


def _total_usage(batches: dict[object, InferenceUsage]) -> InferenceUsage:
    inputs = [usage.input_tokens for usage in batches.values() if usage.input_tokens is not None]
    outputs = [usage.output_tokens for usage in batches.values() if usage.output_tokens is not None]
    return InferenceUsage(
        requests=sum(usage.requests for usage in batches.values()),
        input_tokens=sum(inputs) if inputs else None,
        output_tokens=sum(outputs) if outputs else None,
    )


class CoalescingEmbeddingModel:
    """Wrap an EmbeddingModel for concurrent callers on one async event loop."""

    def __init__(
        self,
        model: EmbeddingModel,
        *,
        max_batch_size: int = 64,
        coalesce_ms: float = 5.0,
        cache_size: int = 1024,
    ) -> None:
        if type(max_batch_size) is not int or max_batch_size < 1:
            raise ValueError("max_batch_size must be a positive integer")
        if type(cache_size) is not int or cache_size < 0:
            raise ValueError("cache_size must be a non-negative integer")
        if type(coalesce_ms) not in (int, float) or not math.isfinite(coalesce_ms) or coalesce_ms < 0:
            raise ValueError("coalesce_ms must be a finite non-negative duration")
        self._model = model
        self._max_batch_size = max_batch_size
        self._delay = coalesce_ms / 1000
        self._cache_size = cache_size
        self._cache: OrderedDict[str, EmbeddingVector] = OrderedDict()
        self._inflight: dict[str, asyncio.Future[_VectorResult]] = {}
        self._queued: list[str] = []
        self._flush_handle: asyncio.Handle | None = None
        self._workers: set[asyncio.Task[None]] = set()

    @property
    def profile(self):
        return self._model.profile

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        loop = asyncio.get_running_loop()
        resolved: dict[str, _VectorResult] = {}
        pending: dict[str, asyncio.Future[_VectorResult]] = {}
        for text in dict.fromkeys(texts):
            if text in self._cache:
                self._cache.move_to_end(text)
                resolved[text] = _VectorResult(self._cache[text])
                continue
            future = self._inflight.get(text)
            if future is None:
                future = loop.create_future()
                future.add_done_callback(_observe_failure)
                self._inflight[text] = future
                self._queued.append(text)
            pending[text] = future
        if self._queued and self._flush_handle is None:
            self._flush_handle = (
                loop.call_later(self._delay, self._dispatch) if self._delay else loop.call_soon(self._dispatch)
            )
        if pending:
            completed = await asyncio.gather(*(asyncio.shield(future) for future in pending.values()))
            resolved.update(zip(pending, completed, strict=True))
        batches = {
            result.batch: result.usage
            for result in resolved.values()
            if result.batch is not None and result.usage is not None
        }
        return EmbeddingResult(vectors=tuple(resolved[text].vector for text in texts), usage=_total_usage(batches))

    def _dispatch(self) -> None:
        self._flush_handle = None
        queued, self._queued = self._queued, []
        for offset in range(0, len(queued), self._max_batch_size):
            texts = tuple(queued[offset:offset + self._max_batch_size])
            task = asyncio.create_task(self._run_batch(texts))
            self._workers.add(task)
            task.add_done_callback(self._workers.discard)

    async def _run_batch(self, texts: tuple[str, ...]) -> None:
        try:
            result = await self._model.embed(texts)
            if len(result.vectors) != len(texts):
                raise ValueError("Embedding provider returned the wrong number of vectors")
        except asyncio.CancelledError:
            for text in texts:
                self._inflight.pop(text).cancel()
            raise
        except Exception as exc:
            for text in texts:
                self._inflight.pop(text).set_exception(exc)
        else:
            batch = object()
            for text, vector in zip(texts, result.vectors, strict=True):
                if self._cache_size:
                    self._cache[text] = vector
                    self._cache.move_to_end(text)
                    if len(self._cache) > self._cache_size:
                        self._cache.popitem(last=False)
                self._inflight.pop(text).set_result(_VectorResult(vector, batch, result.usage))
