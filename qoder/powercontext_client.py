"""Thin, honest HTTP client for the PowerContext 1.5.1 API.

Design rules enforced here:
* Every read/write goes to the real PowerContext server. There is no in-process
  array or cache standing in for memory.
* Failures are raised as typed exceptions with sanitized messages (the bearer
  token never appears in a message).
* Optional HTTP exchange records are collected for evidence, always redacted.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, List, Optional

from config import redact


class PowerContextError(Exception):
    """Base class for all PowerContext client failures."""


class PowerContextUnavailable(PowerContextError):
    """Server unreachable / connection refused / timeout. Nothing was written."""


class PowerContextHTTPError(PowerContextError):
    """Server answered with a non-2xx status."""

    def __init__(self, status: int, detail: Any):
        super().__init__("PowerContext returned HTTP %s" % status)
        self.status = status
        self.detail = detail


@dataclass
class Exchange:
    """A single sanitized request/response record for evidence files."""
    method: str
    path: str
    request: Any
    status: Optional[int]
    response: Any

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "path": self.path,
            "request": self.request,
            "status": self.status,
            "response": self.response,
        }


@dataclass
class PowerContextClient:
    base_url: str
    token: str = ""
    timeout: float = 60.0
    record: List[Exchange] = field(default_factory=list)
    capture: bool = False

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.token:
            h["Authorization"] = "Bearer " + self.token
        return h

    def _call(self, method: str, path: str, payload: Optional[dict]) -> Any:
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.base_url + path, data=data,
                                     headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
                parsed = json.loads(body) if body else None
                status = resp.status
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = raw
            status = exc.code
            self._maybe_record(method, path, payload, status, parsed)
            raise PowerContextHTTPError(status, parsed)
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            self._maybe_record(method, path, payload, None, {"connection_error": str(reason)})
            raise PowerContextUnavailable(redact("PowerContext service is unreachable: %r" % (reason,)))
        except Exception as exc:  # defensive: never leak headers here
            self._maybe_record(method, path, payload, None, {"error": str(exc)})
            raise PowerContextUnavailable(redact(str(exc)))
        self._maybe_record(method, path, payload, status, parsed)
        if status >= 300:
            raise PowerContextHTTPError(status, parsed)
        return parsed

    def _maybe_record(self, method, path, payload, status, parsed):
        if not self.capture:
            return
        safe_req = json.loads(redact(json.dumps(payload, ensure_ascii=False))) if payload is not None else None
        safe_resp = json.loads(redact(json.dumps(parsed, ensure_ascii=False, default=str))) if isinstance(parsed, (dict, list)) else redact(str(parsed))
        self.record.append(Exchange(method, path, safe_req, status, safe_resp))

    # ---- API surface used by the app ---------------------------------------

    def health(self) -> dict:
        """Return whether the real server is reachable and its advertised version.

        Reads the OpenAPI document (no memory is touched). Raises
        PowerContextUnavailable if the server is down.
        """
        doc = self._call("GET", "/openapi.json", None)
        version = None
        if isinstance(doc, dict):
            version = (doc.get("info") or {}).get("version")
        return {"reachable": True, "version": version}

    def create_scope(self, title: str, summary: str, idempotency_key: str) -> dict:
        return self._call("POST", "/v1/scopes", {
            "title": title, "summary": summary, "idempotency_key": idempotency_key,
        })

    def remember(self, scope_id: str, kind: str, text: str, reason: str) -> dict:
        return self._call("POST", "/v1/memory/remember", {
            "scope_id": scope_id, "kind": kind, "text": text, "reason": reason,
        })

    def list_entries(self, scope_id: str, limit: int = 100) -> List[dict]:
        body = self._call("POST", "/v1/memory/entries/list", {
            "scope_id": scope_id, "limit": limit,
        })
        return (body or {}).get("entries", [])

    def prepare_context(self, scope_id: str, query: str, max_bytes: int = 8000) -> dict:
        return self._call("POST", "/v1/context/prepare", {
            "scope_id": scope_id, "query": query, "max_bytes": max_bytes,
        })
