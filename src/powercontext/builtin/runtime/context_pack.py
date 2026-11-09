"""Canonical wire packs for incremental transmission of prepared context."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass

_PACK = "powercontext.context-pack.v1"
_DELTA = "powercontext.context-pack-delta.v1"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


class ContextPackError(ValueError):
    """A context pack or delta violates the wire contract."""


def _wire(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _unique_fields(pairs: list[tuple[str, object]]) -> dict:
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ContextPackError("Duplicate context wire field")
    return fields


def _read(data: bytes, schema: str, fields: set[str]) -> dict:
    try:
        payload = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_fields)
    except (UnicodeError, ValueError, AttributeError, RecursionError) as exc:
        raise ContextPackError("Invalid context wire JSON") from exc
    if not isinstance(payload, dict) or payload.keys() != fields | {"schema"} or payload["schema"] != schema:
        raise ContextPackError("Unexpected context wire schema")
    return payload


def _encode(items: tuple[bytes, ...]) -> list[str]:
    if not isinstance(items, tuple) or any(not isinstance(item, bytes) for item in items):
        raise ContextPackError("Context chunks must be a tuple of bytes")
    return [base64.b64encode(item).decode("ascii") for item in items]


def _decode(items: object) -> tuple[bytes, ...]:
    if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
        raise ContextPackError("Context wire chunks must be a Base64 string array")
    try:
        decoded = tuple(base64.b64decode(item, validate=True) for item in items)
    except (ValueError, binascii.Error) as exc:
        raise ContextPackError("Invalid context Base64") from exc
    if _encode(decoded) != items:
        raise ContextPackError("Noncanonical context Base64")
    return decoded


@dataclass(frozen=True, slots=True)
class ContextPack:
    items: tuple[bytes, ...]
    digest: str
    byte_count: int

    @classmethod
    def build(cls, items: tuple[bytes, ...]) -> ContextPack:
        payload = {"schema": _PACK, "items": _encode(items)}
        digest = "sha256:" + hashlib.sha256(_wire(payload)).hexdigest()
        # The wire length includes its own decimal representation.
        fixed = len(_wire({**payload, "digest": digest, "byte_count": 0})) - 1
        count = fixed + 1
        while count != fixed + len(str(count)):
            count = fixed + len(str(count))
        return cls(items, digest, count)

    @classmethod
    def from_content(cls, content: str, *, chunk_bytes: int = 512) -> ContextPack:
        if type(chunk_bytes) is not int or chunk_bytes < 1:
            raise ContextPackError("chunk_bytes must be a positive integer")
        try:
            data = content.encode("utf-8")
        except (UnicodeError, AttributeError) as exc:
            raise ContextPackError("Context content must be valid UTF-8 text") from exc
        items = []
        start = 0
        while start < len(data):
            end = min(start + chunk_bytes, len(data))
            # Keep line endings stable when later context appends new lines.
            newline = data.rfind(b"\n", start, end)
            if newline != -1:
                end = newline + 1
            while end < len(data) and end > start and data[end] & 0xC0 == 0x80:
                end -= 1
            if end == start:
                raise ContextPackError("chunk_bytes cannot hold the next UTF-8 character")
            items.append(data[start:end])
            start = end
        return cls.build(tuple(items))

    def to_bytes(self) -> bytes:
        return _wire({"schema": _PACK, "items": _encode(self.items), "digest": self.digest,
                      "byte_count": self.byte_count})

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPack:
        payload = _read(data, _PACK, {"items", "digest", "byte_count"})
        pack = cls.build(_decode(payload["items"]))
        count = payload["byte_count"]
        if payload["digest"] != pack.digest or type(count) is not int or count != pack.byte_count or count != len(data):
            raise ContextPackError("Context pack digest or byte count does not match")
        return pack


@dataclass(frozen=True, slots=True)
class ContextPackDelta:
    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack) -> ContextPackDelta:
        prefix = 0
        for old, new in zip(base.items, target.items):
            if old != new:
                break
            prefix += 1
        return cls(base.digest, target.digest, prefix, target.items[prefix:])

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())

    def _validate(self) -> None:
        if type(self.prefix_items) is not int or self.prefix_items < 0:
            raise ContextPackError("Context delta prefix must be a non-negative integer")
        for digest in (self.base_digest, self.target_digest):
            if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
                raise ContextPackError("Invalid context delta digest")

    def to_bytes(self) -> bytes:
        self._validate()
        return _wire({"schema": _DELTA, "base_digest": self.base_digest, "target_digest": self.target_digest,
                      "prefix_items": self.prefix_items, "appended": _encode(self.appended)})

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPackDelta:
        payload = _read(data, _DELTA, {"base_digest", "target_digest", "prefix_items", "appended"})
        delta = cls(payload["base_digest"], payload["target_digest"], payload["prefix_items"],
                    _decode(payload["appended"]))
        delta._validate()
        return delta


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta) -> ContextPack:
    delta._validate()
    if base != ContextPack.build(base.items) or delta.base_digest != base.digest:
        raise ContextPackError("Context delta base digest does not match")
    if delta.prefix_items > len(base.items):
        raise ContextPackError("Context delta prefix exceeds its base")
    target = ContextPack.build(base.items[:delta.prefix_items] + delta.appended)
    if target.digest != delta.target_digest:
        raise ContextPackError("Context delta target digest does not match")
    return target
