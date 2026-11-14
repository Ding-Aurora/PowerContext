"""Research Continuation Station - server-side proxy + static web UI.

Standard library only (no web framework). The browser talks ONLY to this
server; PowerContext credentials live here and are never sent to the client or
written to logs. A tiny on-disk project index maps a backend-chosen project id
to its PowerContext scope_id, because "项目标识由可信后端选择". The actual
records still live entirely in PowerContext memory - this file stores no
history and is not a substitute for memory.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import continuation
from config import load_settings, mask_scope, redact
from powercontext_client import (
    PowerContextClient, PowerContextError, PowerContextHTTPError, PowerContextUnavailable,
)

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DATA_DIR = Path(os.environ.get("RCS_DATA_DIR") or (ROOT / "data"))
PROJECTS_FILE = DATA_DIR / "projects.json"

SETTINGS = load_settings()
DATA_DIR.mkdir(parents=True, exist_ok=True)


def client():
    return PowerContextClient(SETTINGS.powercontext_url, SETTINGS.powercontext_token)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# ---- project index (server-side, holds scope mapping) ----------------------

def load_projects() -> list:
    if not PROJECTS_FILE.exists():
        return []
    return json.loads(PROJECTS_FILE.read_text(encoding="utf-8")).get("projects", [])


def save_projects(projects: list) -> None:
    tmp = PROJECTS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"projects": projects}, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, PROJECTS_FILE)


def find_project(pid: str):
    for p in load_projects():
        if p["id"] == pid:
            return p
    return None


def project_public(p: dict) -> dict:
    """Project view for the browser: no scope_id, no token."""
    return {"id": p["id"], "name": p["name"], "goal": p.get("goal", ""),
            "created_at": p.get("created_at"), "scope": mask_scope(p.get("scope_id", ""))}


class Handler(BaseHTTPRequestHandler):
    server_version = "ResearchContinuationStation/1.0"

    # ---- helpers ----
    def _send(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _static(self, rel: str):
        rel = rel.lstrip("/") or "index.html"
        if rel == "":
            rel = "index.html"
        target = (STATIC / rel).resolve()
        if not str(target).startswith(str(STATIC.resolve())) or not target.exists():
            self.send_error(404, "not found")
            return
        ctype = {".html": "text/html", ".js": "text/javascript",
                 ".css": "text/css", ".json": "application/json"}.get(target.suffix, "application/octet-stream")
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if target.suffix in (".html", ".js", ".css") else ""))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):  # never log headers/tokens
        line = fmt % args
        if any(secret and secret in line for secret in [SETTINGS.powercontext_token]):
            line = redact(line)
        super().log_message("%s", line)

    # ---- routing ----
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/status":
            return self._status()
        if path == "/api/projects":
            return self._send(200, {"projects": [project_public(p) for p in load_projects()]})
        parts = [s for s in path.split("/") if s]
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "projects" and parts[3] == "recall":
            q = parse_qs(parsed.query).get("q", ["下一步做什么"])[0]
            return self._recall(parts[2], q)
        if path.startswith("/api/"):
            return self._send(404, {"ok": False, "error": "unknown endpoint"})
        return self._static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        parts = [s for s in path.split("/") if s]
        if path == "/api/projects":
            return self._create_project()
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "projects" and parts[3] == "sessions":
            return self._save_session(parts[2])
        return self._send(404, {"ok": False, "error": "unknown endpoint"})

    # ---- endpoints ----
    def _status(self):
        c = client()
        try:
            info = c.health()
            return self._send(200, {"ok": True, "powercontext": {"reachable": True,
                          "version": info.get("version"), "url": SETTINGS.powercontext_url}})
        except PowerContextUnavailable as exc:
            return self._send(200, {"ok": False, "powercontext": {"reachable": False,
                          "url": SETTINGS.powercontext_url, "detail": str(exc)}})

    def _create_project(self):
        try:
            body = self._read_json()
        except Exception:
            return self._send(400, {"ok": False, "error": "invalid JSON body"})
        name = (body.get("name") or "").strip()
        goal = (body.get("goal") or "").strip()
        if not name or not goal:
            return self._send(400, {"ok": False, "error": "项目名称和研究目标都不能为空"})
        c = client()
        idem = "rcs-" + uuid.uuid4().hex
        try:
            scope = c.create_scope(name, goal, idem)
        except PowerContextError as exc:
            return self._send(502, {"ok": False, "error": "powercontext_unavailable",
                                    "message": "无法连接 PowerContext，项目未创建：%s" % str(exc)})
        pid = uuid.uuid4().hex[:12]
        project = {"id": pid, "name": name, "goal": goal,
                   "scope_id": scope["scope_id"], "created_at": now_iso()}
        projects = load_projects()
        projects.append(project)
        save_projects(projects)
        return self._send(201, {"ok": True, "project": project_public(project)})

    def _save_session(self, pid: str):
        project = find_project(pid)
        if not project:
            return self._send(404, {"ok": False, "error": "project not found"})
        try:
            body = self._read_json()
        except Exception:
            return self._send(400, {"ok": False, "error": "invalid JSON body"})
        fields = {k: body.get(k, "") for k in continuation.FIELD_KINDS}
        if all(not (v or "").strip() for v in fields.values()):
            return self._send(400, {"ok": False, "error": "至少填写一项记录内容"})
        session_iso = (body.get("session") or "").strip() or now_iso()
        writes = continuation.encode_session(session_iso, fields)
        c = client()
        saved = []
        try:
            for w in writes:
                res = c.remember(project["scope_id"], w["kind"], w["text"], w["reason"])
                for rec in res.get("records", []):
                    art = rec.get("artifact", {})
                    saved.append({"kind": rec.get("kind"), "state": rec.get("state"),
                                  "family": art.get("family"), "artifact_id": art.get("artifact_id"),
                                  "revision": art.get("revision")})
        except PowerContextError as exc:
            # Nothing is claimed as successful: honest failure (task #3, #6).
            return self._send(502, {"ok": False, "error": "powercontext_unavailable",
                                    "saved": False,
                                    "message": "PowerContext 保存失败，本次记录未存入：%s" % str(exc)})
        return self._send(201, {"ok": True, "saved": True, "session": session_iso,
                                "records": saved})

    def _recall(self, pid: str, query: str):
        project = find_project(pid)
        if not project:
            return self._send(404, {"ok": False, "error": "project not found"})
        c = client()
        try:
            entries = c.list_entries(project["scope_id"])
            prepare = c.prepare_context(project["scope_id"], query)
        except PowerContextError as exc:
            return self._send(502, {"ok": False, "error": "powercontext_unavailable",
                                    "message": "PowerContext 不可用，无法召回历史：%s" % str(exc)})
        sessions = continuation.group_entries(entries)
        checklist = continuation.build_checklist(project.get("goal", ""), sessions)
        return self._send(200, {
            "ok": True,
            "project": project_public(project),
            "checklist": checklist,
            "sessions": sessions,
            "prepared_status": prepare.get("status"),
            "prepared_content": continuation.render_prepared_content(prepare),
        })


def main():
    host, port = SETTINGS.app_host, SETTINGS.app_port
    httpd = ThreadingHTTPServer((host, port), Handler)
    print("研究续航站 serving on http://%s:%d  -> PowerContext %s" % (host, port, SETTINGS.powercontext_url))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


if __name__ == "__main__":
    main()
