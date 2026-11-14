# 证据汇总（真实运行，未伪造）

生成时间：2026-11-14（本地）。所有结论均可由下列原始文件复核。

## 已运行并通过

| 项目 | 命令 | 结果 | 原始证据 |
|---|---|---|---|
| 离线单元测试 | `python tests/test_unit.py` | 9/9 通过 | 终端输出（见 docs/VALIDATION.md） |
| 端到端验收（真实 PowerContext 1.5.1） | `python tests/verify_samples.py` | PASS，6/6，VERIFY_EXIT=0 | `verify_report.json` |
| 应用级 HTTP 往返（常驻服务） | 创建→保存→召回 | 成功，scope 仅前缀暴露 | `app_api_roundtrip.json` |
| 服务不可用时行为 | 停止 PC 后保存 | HTTP 502、saved=false、如实报不可用 | `verify_report.json`（样例5a） |

## 脱敏 HTTP 记录

- `http_exchange.log`：真实请求/响应；token 已替换 `[REDACTED]`，scope 仅前缀。
- `probe_*.json`：开发期对真实服务的接口探针结果。

## 日志

- `app.log` / `pc.log`：端到端验收进程日志。
- `app_8688.out/.err`、`pc_8777.out/.err`：常驻服务日志（可见真实的 502 记录与恢复过程）。

## 未采集 / 未获取（如实标注）

- 浏览器 UI 截图：未采集（本机无 playwright，未安装；此前浏览器自动化步骤被取消）。不伪造。
- 公开 URL / 账号 UID / 开发录屏：未发布、未获取。
