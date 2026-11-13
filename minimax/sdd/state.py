"""Persistent task memory using the pinned PowerContext server and client."""

import asyncio
import json
from pathlib import Path

import httpx
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime.config import ExternalSkillsConfig, InferenceConfig, RuntimeConfig
from powercontext.client import PowerContextClient
from powercontext.http import CreateScopeRequest, RememberMemoryRequest, SearchMemoryRequest
from powercontext.server.factory import create_server_app
from powercontext.server.settings import (
    AccessControlConfig, BearerAuthConfig, HttpConfig, McpConfig,
    MetricsConfig, ServerSettings, TracingConfig,
)


async def memory_operation(directory: Path, task_id: str, record=None):
    directory.mkdir(parents=True, exist_ok=True)
    settings = ServerSettings(
        workspace=directory,
        database=SQLiteConfig(url=f"sqlite+aiosqlite:///{(directory / 'memory.db').as_posix()}"),
        http=HttpConfig(host="127.0.0.1"),
        auth=BearerAuthConfig(enabled=False), access=AccessControlConfig(mode="disabled"),
        inference=InferenceConfig(),
        runtime=RuntimeConfig(schedule_seconds=None, experience_schedule_seconds=None),
        external_skills=ExternalSkillsConfig(), mcp=McpConfig(enabled=False),
        metrics=MetricsConfig(enabled=False), tracing=TracingConfig(enabled=False),
    )
    app = create_server_app(settings=settings, scheduler_path=directory / "scheduler.db")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as http:
            async with PowerContextClient("http://localhost", http_client=http) as client:
                scope = await client.create_scope(CreateScopeRequest(
                    title=task_id, summary="SDD task progress and verification", idempotency_key=task_id,
                ))
                if record is not None:
                    saved = await client.remember_memory(RememberMemoryRequest(
                        scope_id=scope.scope_id, kind="fact",
                        text="sdd_progress " + json.dumps(record, ensure_ascii=False),
                        reason="Persist task progress for a later process",
                    ))
                    return saved.model_dump(mode="json")
                found = await client.search_memory(SearchMemoryRequest(
                    scope_id=scope.scope_id, query="sdd_progress", mode="fts",
                ))
                return found.model_dump(mode="json")


def state(directory, task_id, record=None):
    return asyncio.run(memory_operation(directory, task_id, record))
