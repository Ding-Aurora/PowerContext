"""Domain logic: encode research sessions into PowerContext memory and build a
traceable continuation checklist.

No model, no external key. The checklist is produced by a deterministic
template that only re-states what the user actually recorded, and every item
carries a citation back to the atomic-memory artifact it came from. It can
never claim progress that was not saved in a ``progress`` field.
"""
from __future__ import annotations

from typing import Dict, List, Optional

# The four structured fields a session captures (task requirement #2).
FIELD_KINDS = ["progress", "attempt", "problem", "next"]

FIELD_LABELS_ZH = {
    "progress": "本次进展",
    "attempt": "已尝试方法",
    "problem": "遇到的问题",
    "next": "下一步",
}

SEP = "\t"  # record text is "<session_iso>\t<content>"; field name lives in `kind`


def encode_session(session_iso: str, fields: Dict[str, str]) -> List[dict]:
    """Split a session into one memory write per non-empty field."""
    writes = []
    for kind in FIELD_KINDS:
        raw = (fields.get(kind) or "").strip()
        if not raw:
            continue
        writes.append({
            "kind": kind,
            "text": session_iso + SEP + raw,
            "reason": "research-continuation session %s" % session_iso,
        })
    return writes


def _split_text(text: str) -> (str, str):
    if SEP in text:
        head, _, rest = text.partition(SEP)
        return head, rest
    return "", text


def group_entries(entries: List[dict]) -> List[dict]:
    """Rebuild ordered sessions from raw atomic-memory entries.

    Returns newest-first list of sessions:
    ``{session, fields{kind: text}, citations[{kind, family, artifact_id, revision, state}]}``
    """
    buckets: Dict[str, dict] = {}
    for e in entries:
        art = e.get("artifact", {}) or {}
        kind = e.get("kind", "")
        session, content = _split_text(e.get("text", ""))
        key = session or "unknown"
        b = buckets.setdefault(key, {"session": key, "fields": {}, "citations": []})
        # last write wins per (session, kind); records are append-only revisions
        b["fields"][kind] = content
        b["citations"].append({
            "kind": kind,
            "label": FIELD_LABELS_ZH.get(kind, kind),
            "family": art.get("family"),
            "artifact_id": art.get("artifact_id"),
            "revision": art.get("revision"),
            "state": e.get("state"),
        })
    sessions = sorted(buckets.values(), key=lambda s: s["session"], reverse=True)
    return sessions


def _bullets(content: str) -> List[str]:
    lines = [ln.strip(" -•\t") for ln in (content or "").splitlines()]
    return [ln for ln in lines if ln]


def build_checklist(goal: str, sessions: List[dict]) -> dict:
    """Deterministic continuation list with provenance. Never invents facts."""
    items: List[dict] = []
    latest = sessions[0] if sessions else None

    if not latest:
        return {
            "has_history": False,
            "headline": "还没有保存过这个项目的记录",
            "items": [],
            "note": "打开应用后先填写一次进展并保存，续做清单会依据真实记录生成。",
        }

    if goal:
        items.append({"text": "研究目标：%s" % goal, "source": "project", "cite": None})

    cited = _bullets(latest["fields"].get("next"))
    for b in cited:
        items.append({"text": b, "source": "next", "cite": _find_cite(latest, "next")})

    blocked = _bullets(latest["fields"].get("problem"))
    for b in blocked:
        items.append({"text": "待解决：%s" % b, "source": "problem", "cite": _find_cite(latest, "problem")})

    done = _bullets(latest["fields"].get("progress"))
    for b in done:
        items.append({"text": "上次已完成（勿重复）：%s" % b, "source": "progress", "cite": _find_cite(latest, "progress")})

    headline = "欢迎回来，继续「%s」" % (latest["session"] or "最近一次记录")
    note = "以下条目直接摘自你保存的原始记录，未使用任何模型推断。"
    return {"has_history": True, "headline": headline, "items": items, "note": note,
            "latest_session": latest["session"]}


def _find_cite(session: dict, kind: str) -> Optional[dict]:
    for c in session.get("citations", []):
        if c.get("kind") == kind:
            return {"family": c.get("family"), "artifact_id": c.get("artifact_id"), "revision": c.get("revision")}
    return None


def render_prepared_content(prepare_body: dict) -> Optional[str]:
    """Extract the plain recall text from a /v1/context/prepare response."""
    if not isinstance(prepare_body, dict):
        return None
    if prepare_body.get("status") != "ready":
        return None
    return prepare_body.get("content")
