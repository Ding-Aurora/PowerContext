"""Ad-hoc probe of the REAL local PowerContext 1.5.1 HTTP API.

Run against the server started by scripts/start_powercontext.ps1.
Writes raw (sanitized) request/response shapes to evidence/probe_*.json so the
client layer can be coded against observed reality, not assumptions.
"""
import json
import os
import sys
import urllib.request
import urllib.error
import uuid

BASE = os.environ.get("POWERCONTEXT_URL", "http://127.0.0.1:8777").rstrip("/")
TOKEN = os.environ.get("POWERCONTEXT_TOKEN", "")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EV = os.path.join(HERE, "evidence")
os.makedirs(EV, exist_ok=True)


def call(method, path, payload=None):
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode("utf-8")
            return r.status, json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw
    except Exception as e:  # connection refused etc
        return None, {"connection_error": type(e).__name__, "detail": str(e)}


def dump(name, obj):
    with open(os.path.join(EV, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    print("--", name, "--")
    print(json.dumps(obj, ensure_ascii=False)[:800])
    print()


def main():
    out = {}
    # discover docs/health
    for p in ("/openapi.json", "/health", "/healthz", "/docs", "/v1/health"):
        st, bd = call("GET", p)
        out.setdefault("discovery", {})[p] = {"status": st, "keys": list(bd.keys()) if isinstance(bd, dict) else str(bd)[:120]}
    dump("probe_discovery.json", out["discovery"])

    # create scope
    st, scope = call("POST", "/v1/scopes", {
        "title": "Probe project " + uuid.uuid4().hex[:6],
        "summary": "Ad-hoc API shape probe for the Research Continuation Station",
        "idempotency_key": "probe-" + uuid.uuid4().hex,
    })
    dump("probe_scope_create.json", {"status": st, "body": scope})
    sid = (scope or {}).get("scope_id")
    if not sid:
        print("no scope id; aborting", file=sys.stderr)
        return 1

    # empty prepare before any memory
    st, empty = call("POST", "/v1/context/prepare", {"scope_id": sid, "query": "next step", "max_bytes": 6000})
    dump("probe_prepare_empty.json", {"status": st, "body": empty})

    # remember a progress record
    st, rec = call("POST", "/v1/memory/remember", {
        "scope_id": sid, "kind": "progress",
        "text": "Completed group A watering logs; group B sensor failed; next step: replace batteries and re-collect data.",
        "reason": "session end save",
    })
    dump("probe_remember.json", {"status": st, "body": rec})

    # recall after memory
    st, prep = call("POST", "/v1/context/prepare", {"scope_id": sid, "query": "what should I do next", "max_bytes": 6000})
    dump("probe_prepare_ready.json", {"status": st, "body": prep})

    # search endpoint shape
    st, srch = call("POST", "/v1/memory/search", {"scope_id": sid, "query": "battery", "limit": 5})
    dump("probe_search.json", {"status": st, "body": srch})

    # list entries shape
    st, lst = call("POST", "/v1/memory/entries/list", {"scope_id": sid, "limit": 10})
    dump("probe_entries_list.json", {"status": st, "body": lst})

    # isolation: a fresh scope should not recall project A
    st, scope2 = call("POST", "/v1/scopes", {
        "title": "Blank probe project " + uuid.uuid4().hex[:6],
        "summary": "Isolation check", "idempotency_key": "probe2-" + uuid.uuid4().hex})
    sid2 = (scope2 or {}).get("scope_id")
    st, prep2 = call("POST", "/v1/context/prepare", {"scope_id": sid2, "query": "battery watering", "max_bytes": 6000})
    dump("probe_isolation.json", {"scope2": sid2, "prepare_status": st, "body": prep2})

    print("PROBE DONE. scope_id=", sid, "scope2_id=", sid2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
