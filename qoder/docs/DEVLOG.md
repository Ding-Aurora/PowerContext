# 开发与调试记录（DEVLOG）

本文件记录真实开发与调试过程。没有运行或无法证明的步骤明确标注。

## 环境

- Windows 11（25H2）、PowerShell 7/5、Python 3.11。
- PowerContext 由官方 pip 包提供，参考版本 1.5.1，安装于 `work/venv`。
- 本应用只用 Python 标准库，前端无构建。

## 关键实现决策

1. 先读 `work/contract.json`（由安装包 OpenAPI 提取）+ 对运行中的真实服务发探针（`devtools/probe_api.py`），拿到实际响应结构后再写客户端，避免凭记忆写错接口。
2. 采用「服务端代理 + 服务端项目索引」：`server.py` 把后端生成的项目 id 映射到 PowerContext scope_id；浏览器只见内部项目 id 和 scope 前缀，永不见 scope_id 全文与 token。项目索引只保存映射，**不保存任何历史记录**（历史完全在 PowerContext）。
3. 历史展示用 `/v1/memory/entries/list`（权威清单，含 artifact/revision），续做清单用 `continuation.py` 从结构化字段确定性生成。
4. 一个会话拆成 4 类原子记忆（progress/attempt/problem/next），每条 text 以 `<session_iso>\t<content>` 编码，便于重开应用后按会话重组。

## 真实调试轨迹

- 探针：确认 `POST /v1/scopes` 返回 `scope_id`；`/v1/context/prepare` 空库返回 `status=empty`；`/v1/memory/remember` 返回 `records[].artifact`；`/v1/memory/entries/list` 返回 `entries`；新 scope 与已有 scope 数据隔离（第二个 scope prepare 返回 empty）。
- 离线单测 `test_unit.py`：**9/9 通过**（含“清单不得谎称 B 组已完成”“token 不出现在错误信息”“连接拒绝必须抛不可用而非成功”）。
- 端到端 `verify_samples.py` 首次运行：样例1、2 通过，样例3 报 404。原因：`app_get` 未处理 HTTPError，且“重开应用”时 `start_app()` 误清空项目索引。修复：`app_get` 捕获 HTTPError；`start_app(fresh=...)` 仅首次清库。
- 端到端第二次运行：样例5b 失败。原因：`start_pc()` 每次重启都 `rm -rf` 数据目录，抹掉了持久化数据。修复：`start_pc(fresh=...)`，重启用 `fresh=False`。
- 端到端第三次运行：**6/6 通过**（见 `evidence/verify_report.json`）。
- 常驻 8777 的 PowerContext 曾因后台终端被中断而掉线；应用在召回时如实返回 HTTP 502「PowerContext 不可用」（正好覆盖需求 #6）。用 `Start-Process` 分离进程恢复后，应用级往返（创建→保存→召回）成功，证据 `evidence/app_api_roundtrip.json`。

## 观察到的真实行为（值得记录）

- 本机 SQLite / 无 Embedding 模式下，`/v1/context/prepare` 即使已有记忆也可能返回 `status=empty`。因此“历史原始记录”和“续做清单”以 `/v1/memory/entries/list` 为准（它确实返回全部已保存记录与引用），`context/prepare` 的内容仅在 `status=ready` 时展示。

## 账号与发布

- Qoder 账号 UID：**未获取**（本次未执行发布）。
- Qoder Sites 公开 URL：**未发布**；展示网站仅本地预览。
- 浏览器 UI 走查截图：**未采集**（用户取消了浏览器自动化步骤，未伪造）。
- 禁止事项遵守：未修改 `gaode/ dify/ stepfun/ minimax/`，未改动既有分支/提交，未执行强制推送。

## 后续复核（Codex）
复跑离线单元测试 9/9 通过；修正安装依赖为 powercontext[cli,server]==1.5.1，补充网站仓库链接。主要应用代码由 Qoder 生成，本次仅交付复核。

