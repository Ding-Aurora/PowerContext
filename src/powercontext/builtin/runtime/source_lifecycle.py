"""Persist Source availability and propagate it to dependent evidence."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import insert, select, update

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.persistence.tables import SOURCE_LIFECYCLE_TABLE
from powercontext.builtin.sources.journal import validate_scope_id
from powercontext.errors import PowerContextError
from powercontext.sources import SourceRef

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

    from powercontext.builtin.persistence.database import AsyncDatabase
    from powercontext.builtin.runtime.application import BuiltinRuntime

Reference = SourceRef | MemoryCitation | ArtifactRef
Policy = Literal["all", "any"]


class SourceLifecycleError(ValueError):
    """An invalid lifecycle transition or reference."""


class SourceLifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    node_id: str
    revision: int = Field(gt=0)
    sequence: int = Field(gt=0)
    available: bool
    reason: str

    @field_validator("node_id", "reason")
    @classmethod
    def _nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Lifecycle event identity and reason must not be blank")
        return value


class _Node(BaseModel):
    reference: Reference
    parents: tuple[str, ...] = ()
    policy: Policy = "all"
    revision: int | None = None
    event: SourceLifecycleEvent | None = None
    available: bool = True


class _Graph(BaseModel):
    nodes: dict[str, _Node] = Field(default_factory=dict)

    def propagate(self) -> None:
        # Parents are registered first; JSON storage retains registration order.
        for node in self.nodes.values():
            if node.parents:
                supported = (self.nodes[parent].available for parent in node.parents)
                node.available = all(supported) if node.policy == "all" else any(supported)

    def active_ids(self) -> list[str]:
        return sorted(key for key, node in self.nodes.items() if node.available)


async def _load(connection: AsyncConnection, scope: str) -> _Graph | None:
    table = SOURCE_LIFECYCLE_TABLE
    raw = await connection.scalar(select(table.c.graph).where(table.c.scope_id == scope))
    return None if raw is None else _Graph.model_validate_json(raw)


async def excluded_topic_ids(connection: AsyncConnection, scope: str) -> frozenset[str]:
    graph = await _load(connection, scope)
    if graph is None:
        return frozenset()
    return frozenset(
        node.reference.artifact_id for node in graph.nodes.values()
        if not node.available and isinstance(node.reference, ArtifactRef)
    )


class SourceLifecycleApplication:
    def __init__(self, runtime: BuiltinRuntime, database: AsyncDatabase | None) -> None:
        self._runtime = runtime
        self._database = database

    def for_scope(self, scope_id: str, /) -> _ScopedSourceLifecycle:
        if self._database is None:
            raise SourceLifecycleError("Source lifecycle requires durable relational storage")
        return _ScopedSourceLifecycle(self._runtime, self._database, validate_scope_id(scope_id))


class _ScopedSourceLifecycle:
    def __init__(self, runtime: BuiltinRuntime, database: AsyncDatabase, scope: str) -> None:
        self._runtime = runtime
        self._database = database
        self._scope = scope

    async def register_source(self, node_id: str, source_ref: SourceRef, *, revision: int) -> None:
        if not isinstance(source_ref, SourceRef) or type(revision) is not int or revision < 1:
            raise SourceLifecycleError("Invalid Source reference or lifecycle revision")
        await self._register(node_id, _Node(reference=source_ref, revision=revision))

    async def register_memory(self, node_id: str, citation: MemoryCitation, *, parents: tuple[str, ...],
                              policy: Policy) -> None:
        if not isinstance(citation, MemoryCitation):
            raise SourceLifecycleError("Expected an exact Memory citation")
        await self._register_derived(node_id, citation, parents, policy)

    async def register_topic(self, node_id: str, artifact_ref: ArtifactRef, *, parents: tuple[str, ...],
                             policy: Policy) -> None:
        if not isinstance(artifact_ref, ArtifactRef) or artifact_ref.family != "topic-memory":
            raise SourceLifecycleError("Expected an exact Topic Memory reference")
        await self._register_derived(node_id, artifact_ref, parents, policy)

    async def _register_derived(self, node_id: str, reference: MemoryCitation | ArtifactRef,
                                parents: tuple[str, ...], policy: Policy) -> None:
        if not parents or any(not isinstance(parent, str) for parent in parents) or len(set(parents)) != len(parents):
            raise SourceLifecycleError("Derived nodes need distinct parents")
        if policy not in ("all", "any"):
            raise SourceLifecycleError("Unknown lifecycle support policy")
        await self._register(node_id, _Node(reference=reference, parents=parents, policy=policy))

    async def _register(self, node_id: str, node: _Node) -> None:
        if not isinstance(node_id, str) or not node_id.strip():
            raise SourceLifecycleError("Lifecycle node ID must not be blank")
        async with self._write_scope():
            current = await self._read()
            graph = current or _Graph()
            if (old := graph.nodes.get(node_id)) is not None:
                if old.model_dump(exclude={"event", "available"}) != node.model_dump(exclude={"event", "available"}):
                    raise SourceLifecycleError("Lifecycle node already has a different binding")
                return
            if node_id in node.parents or any(parent not in graph.nodes for parent in node.parents):
                raise SourceLifecycleError("Lifecycle parents must already be registered")
            await self._check_reference(node.reference)
            graph.nodes[node_id] = node
            graph.propagate()
            await self._reconcile_memory(graph, "Register Source dependency")
            await self._save(graph, create=current is None)

    async def apply(self, event: SourceLifecycleEvent) -> list[str]:
        async with self._write_scope():
            graph = await self._read()
            node = None if graph is None else graph.nodes.get(event.node_id)
            if graph is None or node is None or not isinstance(node.reference, SourceRef) or node.revision != event.revision:
                raise SourceLifecycleError("Unknown Source or lifecycle revision mismatch")
            if node.event == event:
                return graph.active_ids()
            if node.event is not None and event.sequence <= node.event.sequence:
                raise SourceLifecycleError("Lifecycle event sequence is stale or conflicting")
            node.event = event
            node.available = event.available
            graph.propagate()
            # Commit the event only after native writes succeed. Retrying reconciles
            # current Memory state, including transitions already written before failure.
            await self._reconcile_memory(graph, event.reason)
            await self._save(graph)
            return graph.active_ids()

    async def resolve(self, node_id: str, *, purpose: Literal["generation", "audit"]) -> Reference:
        graph = await self._read()
        node = None if graph is None else graph.nodes.get(node_id)
        if node is None or purpose not in ("generation", "audit"):
            raise SourceLifecycleError("Unknown lifecycle node or resolution purpose")
        if purpose == "generation" and not node.available:
            raise SourceLifecycleError("Lifecycle node is unavailable for generation")
        return node.reference

    async def _check_reference(self, reference: Reference) -> None:
        from powercontext.builtin.runtime.models import GetMemoryEntryRequest

        records = self._runtime.records.for_scope(self._scope)
        try:
            if isinstance(reference, SourceRef):
                await records.get_source(reference.source_type, reference.source_id)
            elif isinstance(reference, MemoryCitation):
                await self._runtime.memory.for_scope(self._scope).get(GetMemoryEntryRequest(citation=reference))
            else:
                await records.get_artifact_revision(reference.family, reference.artifact_id, reference.revision)
        except (PowerContextError, LookupError, ValueError) as exc:
            raise SourceLifecycleError("Lifecycle reference cannot be read in this scope") from exc

    async def _reconcile_memory(self, graph: _Graph, reason: str) -> None:
        desired = {}
        for node in graph.nodes.values():
            if isinstance(node.reference, MemoryCitation):
                desired[(node.reference.entry_id, node.reference.entry_version_id)] = node.available
        if not desired:
            return
        async with self._runtime._context(self._scope) as context:
            service = context.artifacts.memory
            head = await service.head(context.artifacts.memory_artifact_id)
            entries = {(entry.entry_id, entry.entry_version_id): entry for entry in await service.entries(head)}
            if not desired.keys() <= entries.keys():
                raise SourceLifecycleError("A registered Memory entry version is no longer current")
            states = {(entry.entry_id, entry.entry_version_id): entry.state for entry in head.content.manifest.entries}
            withdrawn = tuple(entries[key] for key, available in desired.items() if not available and states[key] == "active")
            restored = tuple(entries[key] for key, available in desired.items() if available and states[key] != "active")
            if withdrawn:
                head = await service.forget(head, entries=withdrawn, reason=reason)
            if restored:
                await service.reactivate(head, entries=restored, reason=reason)

    async def _read(self) -> _Graph | None:
        async with self._database.transaction() as connection:
            return await _load(connection, self._scope)

    @asynccontextmanager
    async def _write_scope(self):
        async with self._runtime._scoped_operation(self._scope), self._runtime._locked(self._scope):
            yield

    async def _save(self, graph: _Graph, *, create: bool = False) -> None:
        table = SOURCE_LIFECYCLE_TABLE
        statement = (insert(table).values(scope_id=self._scope) if create
                     else update(table).where(table.c.scope_id == self._scope))
        async with self._database.transaction() as connection:
            await connection.execute(statement.values(graph=graph.model_dump_json().encode("utf-8")))
