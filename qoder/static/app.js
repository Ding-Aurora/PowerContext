"use strict";

const API = {
  status: "/api/status",
  projects: "/api/projects",
  project: (id) => `/api/projects/${id}`,
  recall: (id) => `/api/projects/${id}/recall`,
  sessions: (id) => `/api/projects/${id}/sessions`,
};

let currentProject = null;

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};

async function jget(url) {
  const r = await fetch(url);
  return r.json();
}
async function jsend(url, method, body) {
  const r = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  return { status: r.status, data: await r.json() };
}

async function refreshStatus() {
  const box = $("#status");
  try {
    const s = await jget(API.status);
    const pc = s.powercontext || {};
    if (pc.reachable) {
      box.className = "status ok";
      box.textContent = `PowerContext 已连接 · v${pc.version || "?"}`;
    } else {
      box.className = "status bad";
      box.textContent = "PowerContext 不可用：" + (pc.detail || "连接失败");
    }
  } catch (e) {
    box.className = "status bad";
    box.textContent = "无法读取后端状态";
  }
}

async function loadProjects() {
  const { projects } = await jget(API.projects);
  const list = $("#projectList");
  list.innerHTML = "";
  if (!projects.length) {
    list.appendChild(el("li", "muted", "还没有项目"));
    return;
  }
  projects.forEach((p) => {
    const li = el("li", "project-item");
    li.textContent = p.name;
    if (currentProject && currentProject.id === p.id) li.classList.add("active");
    li.onclick = () => selectProject(p);
    list.appendChild(li);
  });
}

async function selectProject(p) {
  currentProject = p;
  $("#emptyState").classList.add("hidden");
  $("#workbench").classList.remove("hidden");
  $("#projTitle").textContent = p.name;
  $("#projGoalText").textContent = "研究目标：" + (p.goal || "");
  $("#scopeNote").textContent = "数据分区 scope：" + p.scope + "（后端保存，仅显示前缀）";
  $("#newProjectForm").classList.add("hidden");
  await loadProjects();
  await doRecall();
}

function escapeChecklist(container, checklist) {
  container.innerHTML = "";
  if (!checklist.has_history) {
    container.appendChild(el("p", "muted", checklist.headline));
    container.appendChild(el("p", "hint", checklist.note));
    return;
  }
  container.appendChild(el("p", "check-head", checklist.headline));
  const ul = el("ul", "check-items");
  checklist.items.forEach((it) => {
    const li = el("li", "src-" + it.source);
    li.appendChild(el("span", "check-text", it.text));
    if (it.cite && it.cite.artifact_id) {
      const c = el("span", "cite",
        `来源 ${it.cite.artifact_id}·r${it.cite.revision}`);
      c.title = `${it.cite.family}/${it.cite.artifact_id} rev ${it.cite.revision}`;
      li.appendChild(c);
    }
    ul.appendChild(li);
  });
  container.appendChild(ul);
  container.appendChild(el("p", "hint", checklist.note));
}

function renderHistory(container, sessions) {
  container.innerHTML = "";
  if (!sessions.length) {
    container.appendChild(el("p", "muted", "这个项目还没有保存过记录。"));
    return;
  }
  sessions.forEach((s) => {
    const block = el("div", "session");
    block.appendChild(el("div", "session-time", s.session || "未知时间"));
    Object.entries(s.fields).forEach(([kind, text]) => {
      const line = el("div", "record");
      line.appendChild(el("span", "rec-label", labelOf(kind)));
      line.appendChild(el("span", "rec-text", text));
      const cite = (s.citations || []).find((c) => c.kind === kind);
      if (cite && cite.artifact_id) {
        line.appendChild(el("span", "rec-cite", `#${cite.artifact_id} r${cite.revision}`));
      }
      block.appendChild(line);
    });
    container.appendChild(block);
  });
}

function labelOf(kind) {
  return { progress: "本次进展", attempt: "已尝试方法", problem: "遇到的问题", next: "下一步" }[kind] || kind;
}

async function doRecall() {
  if (!currentProject) return;
  const q = $("#recallQuery").value || "下一步做什么";
  const container = $("#checklist");
  const hist = $("#history");
  container.innerHTML = "";
  container.appendChild(el("p", "muted", "召回中…"));
  try {
    const res = await jget(`${API.recall(currentProject.id)}?q=${encodeURIComponent(q)}`);
    if (!res.ok) {
      container.innerHTML = "";
      container.appendChild(el("p", "result bad", res.message || "召回失败"));
      hist.innerHTML = "";
      hist.appendChild(el("p", "result bad", "PowerContext 不可用，无法显示历史（不伪造）。"));
      return;
    }
    escapeChecklist(container, res.checklist);
    renderHistory(hist, res.sessions);
  } catch (e) {
    container.innerHTML = "";
    container.appendChild(el("p", "result bad", "召回请求失败：" + e.message));
  }
}

async function saveSession(ev) {
  ev.preventDefault();
  if (!currentProject) return;
  const out = $("#saveResult");
  out.className = "result";
  out.textContent = "保存中…";
  const body = {
    progress: $("#progress").value,
    attempt: $("#attempt").value,
    problem: $("#problem").value,
    next: $("#next").value,
  };
  const { status, data } = await jsend(API.sessions(currentProject.id), "POST", body);
  if (status === 201 && data.ok && data.saved) {
    out.className = "result ok";
    out.textContent = `已真实写入 PowerContext（${data.records.length} 条记忆）。`;
    $("#sessionForm").reset();
    await doRecall();
  } else {
    out.className = "result bad";
    out.textContent = (data && data.message) || "保存失败，记录未存入。";
  }
}

async function createProject(ev) {
  ev.preventDefault();
  const body = { name: $("#projName").value, goal: $("#projGoal").value };
  const { status, data } = await jsend(API.projects, "POST", body);
  if (status === 201 && data.ok) {
    $("#newProjectForm").reset();
    $("#newProjectForm").classList.add("hidden");
    await loadProjects();
    selectProject(data.project);
  } else {
    alert((data && data.message) || (data && data.error) || "创建失败");
  }
}

function wire() {
  $("#newProjectBtn").onclick = () => $("#newProjectForm").classList.toggle("hidden");
  $("#cancelNew").onclick = () => { $("#newProjectForm").classList.add("hidden"); $("#newProjectForm").reset(); };
  $("#newProjectForm").onsubmit = createProject;
  $("#sessionForm").onsubmit = saveSession;
  $("#recallBtn").onclick = doRecall;
  $("#recallQuery").addEventListener("keydown", (e) => { if (e.key === "Enter") doRecall(); });
}

(async function init() {
  wire();
  await refreshStatus();
  await loadProjects();
  setInterval(refreshStatus, 15000);
})();
