"""End-to-end acceptance run against a REAL local PowerContext Server 1.5.1.

This script is honest by construction:
* It starts its own PowerContext (SQLite mode) and its own app process on
  dedicated ports, with data isolated inside the qoder directory. It never
  touches other tasks' data.
* Every acceptance sample records EXPECTED vs ACTUAL and a pass/fail derived
  from the real responses.
* If a step cannot run (e.g. PowerContext binary not found), it is marked
  NOT RUN rather than faked.

Run:  python tests/verify_samples.py
Output: evidence/verify_report.json, evidence/http_exchange.log
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from powercontext_client import PowerContextClient  # noqa: E402

PC_PORT = int(os.environ.get("VERIFY_PC_PORT", "8791"))
APP_PORT = int(os.environ.get("VERIFY_APP_PORT", "8891"))
PC_URL = "http://127.0.0.1:%d" % PC_PORT
APP_URL = "http://127.0.0.1:%d" % APP_PORT
PC_HOME = ROOT / ".verify-pc-home"
APP_DATA = ROOT / ".verify-data"
EV = ROOT / "evidence"

report = {"started_at": datetime.now(timezone.utc).isoformat(),
          "powercontext_reference_version": "1.5.1",
          "environment": {"os": os.name, "python": sys.version.split()[0],
                          "pc_port": PC_PORT, "app_port": APP_PORT},
          "samples": [], "notes": []}


def log(msg):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg), flush=True)


def find_powercontext_exe():
    if os.environ.get("POWERCONTEXT_BIN") and Path(os.environ["POWERCONTEXT_BIN"]).exists():
        return os.environ["POWERCONTEXT_BIN"]
    cand = ROOT / ".." / ".." / "work" / "venv" / "Scripts" / "powercontext.exe"
    if cand.exists():
        return str(cand.resolve())
    which = shutil.which("powercontext")
    return which


def wait_ready(url, timeout=60.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "/openapi.json", timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def wait_app_ready(timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(APP_URL + "/api/status", timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


def start_pc(fresh=True):
    exe = find_powercontext_exe()
    if not exe:
        report["notes"].append("未找到 powercontext 可执行文件，端到端样例标为 NOT RUN。")
        return None
    if fresh and PC_HOME.exists():
        shutil.rmtree(PC_HOME, ignore_errors=True)
    PC_HOME.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["POWERCONTEXT_HOME"] = str(PC_HOME)
    proc = subprocess.Popen([exe, "server", "run", "--host", "127.0.0.1", "--port", str(PC_PORT)],
                            env=env, stdout=open(EV / "pc.log", "ab"), stderr=subprocess.STDOUT)
    if not wait_ready(PC_URL):
        proc.terminate()
        raise RuntimeError("PowerContext 启动超时")
    log("PowerContext 已就绪：%s (exe=%s)" % (PC_URL, exe))
    return proc


def start_app(fresh=True):
    if fresh and APP_DATA.exists():
        shutil.rmtree(APP_DATA, ignore_errors=True)
    APP_DATA.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update({"POWERCONTEXT_URL": PC_URL, "POWERCONTEXT_TOKEN": "",
                "APP_HOST": "127.0.0.1", "APP_PORT": str(APP_PORT), "RCS_DATA_DIR": str(APP_DATA)})
    proc = subprocess.Popen([sys.executable, str(ROOT / "server.py")], env=env, cwd=str(ROOT),
                            stdout=open(EV / "app.log", "ab"), stderr=subprocess.STDOUT)
    if not wait_app_ready():
        proc.terminate()
        raise RuntimeError("应用启动超时")
    log("应用已就绪：%s" % APP_URL)
    return proc


def stop(proc):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except Exception:
            proc.kill()
        time.sleep(1.5)


def app_get(path):
    req = urllib.request.Request(APP_URL + path, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def app_post(path, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(APP_URL + path, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def sample(name, expected, actual, passed, detail=None):
    report["samples"].append({"name": name, "expected": expected, "actual": actual,
                              "passed": passed, "detail": detail,
                              "checked_at": datetime.now(timezone.utc).isoformat()})
    log("%s: %s" % ("PASS" if passed else "FAIL", name))


def main():
    EV.mkdir(parents=True, exist_ok=True)
    pc = None
    app = None
    restart_ok = False
    try:
        pc = start_pc()
        if pc is None:
            report["verdict"] = "NOT RUN"
            _write()
            return 2
        # capture raw sanitized HTTP exchange as extra evidence
        cap = PowerContextClient(PC_URL, capture=True)
        try:
            cap.health()
        except Exception:
            pass
        app = start_app()

        goal = "比较两种番茄浇水方案"
        st, created = app_post("/api/projects", {"name": "番茄浇水对比（演示）", "goal": goal})
        pid = created.get("project", {}).get("id")
        sample("样例1 创建研究项目并录入目标",
               "返回 201、有项目 id、公开视图不含 scope_id/token",
               {"status": st, "project": created.get("project")},
               st == 201 and bool(pid) and "scope_id" not in (created.get("project") or {}))

        session_payload = {
            "progress": "已完成 A 组浇水记录",
            "attempt": "A 组定时定量浇水 / B 组土壤湿度触发",
            "problem": "B 组传感器故障，数据缺失",
            "next": "更换 B 组电池后补采数据",
        }
        st, saved = app_post("/api/projects/%s/sessions" % pid, session_payload)
        n_rec = len(saved.get("records", [])) if isinstance(saved, dict) else 0
        sample("样例2 保存本次记录并真实写入 PowerContext",
               "返回 201、saved=true、写入若干条记忆记录",
               {"status": st, "saved": saved.get("saved"), "record_count": n_rec},
               st == 201 and bool(saved.get("saved")) and n_rec >= 3)

        # 样例3：模拟重新打开应用（重启 app 进程，保留服务端项目索引），选回同一项目查询"下一步做什么"
        stop(app)
        app = start_app(fresh=False)
        st, rec = app_get("/api/projects/%s/recall?q=%s" % (pid, urllib.parse.quote("下一步做什么")))
        joined = "\n".join(i["text"] for i in rec.get("checklist", {}).get("items", []))
        recalled_next = ("更换" in joined) or ("补采" in joined)
        claims_b_done = ("B 组已完成" in joined) or ("B组已完成" in joined)
        has_citation = any(i.get("cite") for i in rec.get("checklist", {}).get("items", []) if i["source"] in ("next", "problem"))
        sample("样例3 重开应用后按项目召回、含可追溯引用且不得谎称 B 组完成",
               "召回包含更换电池/补采数据；不得出现 B 组已完成；条目带 artifact 引用",
               {"prepared_status": rec.get("prepared_status"), "checklist_text": joined,
                "recalled_next": recalled_next, "claims_b_done": claims_b_done, "has_citation": has_citation},
               rec.get("ok") and recalled_next and (not claims_b_done) and has_citation)

        # 样例4：新建另一个空白项目，不应召回上述实验记录
        st, created2 = app_post("/api/projects", {"name": "空白项目（隔离检查）", "goal": "占位目标"})
        pid2 = created2.get("project", {}).get("id")
        st2, rec2 = app_get("/api/projects/%s/recall?q=%s" % (pid2, urllib.parse.quote("浇水 电池")))
        leaked = ("番茄" in json.dumps(rec2, ensure_ascii=False)) or rec2.get("checklist", {}).get("has_history")
        sample("样例4 项目隔离：空白项目不得召回项目 A 的记录",
               "空白项目无历史记录、不含番茄/电池内容",
               {"prepared_status": rec2.get("prepared_status"), "has_history": rec2.get("checklist", {}).get("has_history"),
                "leaked": bool(leaked)},
               rec2.get("ok") and rec2.get("prepared_status") == "empty" and not leaked)

        # 样例5：停止 PowerContext 后保存必须失败；重启后原记录仍在
        stop(pc)
        pc = None
        st5, fail = app_post("/api/projects/%s/sessions" % pid, {"next": "服务停止期间的写入应失败"})
        refused = (st5 >= 500) and (not fail.get("saved"))
        sample("样例5a 停止 PowerContext 后保存必须如实失败",
               "返回 5xx、saved 不为真、给出不可用信息（不伪造成功）",
               {"status": st5, "body": fail},
               refused)

        # 重启 PowerContext（保留同一数据目录），验证记录仍存在
        pc = start_pc(fresh=False)
        restart_ok = pc is not None
        if restart_ok:
            # app 的 client 每次新建，无需重启 app
            st6, rec6 = app_get("/api/projects/%s/recall?q=%s" % (pid, urllib.parse.quote("补采")))
            persisted = rec6.get("prepared_status") == "ready" or rec6.get("checklist", {}).get("has_history")
            still_next = "补采" in json.dumps(rec6, ensure_ascii=False)
            sample("样例5b 重启 PowerContext 后已有记录仍存在",
                   "重新可达且原记录可召回",
                   {"prepared_status": rec6.get("prepared_status"), "has_history": rec6.get("checklist", {}).get("has_history"),
                    "still_next": still_next},
                   rec6.get("ok") and bool(persisted))
        else:
            sample("样例5b 重启 PowerContext 后已有记录仍存在", "重新可达且原记录可召回",
                   "NOT RUN：PowerContext 未能重启", False)

        overall = all(s["passed"] for s in report["samples"])
        report["verdict"] = "PASS" if overall else "PARTIAL/FAIL"

        # dump sanitized direct HTTP exchange log (no token; scopes masked)
        with open(EV / "http_exchange.log", "w", encoding="utf-8") as f:
            for ex in cap.record:
                f.write(json.dumps(ex.to_dict(), ensure_ascii=False) + "\n")
    except Exception as exc:
        report["verdict"] = "ERROR"
        report["fatal_error"] = str(exc)
        raise
    finally:
        stop(app)
        if pc:
            stop(pc)
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        _write()
    return 0 if report.get("verdict") == "PASS" else 1


def _write():
    (EV / "verify_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    total = len(report["samples"])
    passed = sum(1 for s in report["samples"] if s["passed"])
    log("真实样例结论：%s（%d/%d 通过）；报告见 evidence/verify_report.json" % (report.get("verdict"), passed, total))


if __name__ == "__main__":
    sys.exit(main())
