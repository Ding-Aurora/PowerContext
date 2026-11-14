# 验证样例与真实运行证据（VALIDATION）

原则：预期结果与实际结果分开写；没有运行的步骤标为未验证；不伪造证据。

## 一、真实端到端验收（已运行）

执行命令：`python tests/verify_samples.py`
脚本自动在独立端口启动真实 PowerContext 1.5.1（SQLite 模式，数据隔离在 `.verify-pc-home`）和应用（`.verify-data`），跑通任务书样例 1–5。
结论：**PASS，6/6 通过**（`VERIFY_EXIT=0`）。机器可读报告：`evidence/verify_report.json`。

| 样例 | 预期 | 实际（真实） | 结果 |
|---|---|---|---|
| 1 创建研究项目并录入目标 | 返回 201、有项目 id、公开视图不含 scope_id/token | 201；项目公开视图仅含掩码 scope 前缀 | PASS |
| 2 保存进展/已尝试/问题/下一步 | 真实写入，201、saved=true、≥3 条记忆 | saved=true，写入 4 条原子记忆 | PASS |
| 3 重开应用按项目召回 | 召回含“更换电池/补采”，不得谎称“B 组已完成”，条目带 artifact 引用 | 召回清单含下一步与待解决项，带 artifact/revision 引用，未出现“B 组已完成” | PASS |
| 4 项目隔离 | 空白项目无历史、不含番茄/电池内容 | 空白项目 `prepared_status=empty`、`has_history=false` | PASS |
| 5a 停止 PowerContext 后保存 | 返回 5xx、saved 非真、如实报不可用 | 停止服务后保存返回 502、saved=false、含连接拒绝信息 | PASS |
| 5b 重启后已有记录仍在 | 重新可达且原记录可召回 | 重启（保留数据目录）后原记录仍可召回 | PASS |

脱敏 HTTP 记录：`evidence/http_exchange.log`（token 已替换为 `[REDACTED]`，scope 仅前缀）。
运行日志：`evidence/app.log`、`evidence/pc.log`。

## 二、离线单元测试（已运行）

`python tests/test_unit.py` → **9/9 通过**。覆盖：字段编码、会话分组与排序、续做清单不编造（“B 组已完成”永不出现）、已完成项标为“勿重复”、token 脱敏、连接拒绝必须抛“不可用”而非成功。

## 三、应用级 HTTP 往返（已运行，常驻服务）

在常驻 PowerContext（8777）+ 应用（8688）上执行 创建→保存→召回，证据 `evidence/app_api_roundtrip.json`。
观察：浏览器拿到的 scope 显示为 `scp_69ag…`（仅前缀）；续做清单正确生成并带引用。

## 四、未验证 / 未采集（如实标注）

- 浏览器 UI 走查与界面截图：**未采集**（用户取消浏览器自动化步骤，未伪造）。
- Qoder Sites 公开 URL：**未发布**，仅本地预览。
- Qoder 账号 UID、开发录屏：**未获取**。
- 多用户并发 / 公网部署 / 真实模型生成：本演示不涉及，未验证。

## 五、结论

核心功能（PowerContext 真实记忆读写、项目切换隔离、重开召回、异常如实处理、可追溯原始记录与续做清单）已在真实服务上验证通过。公开 URL、UID、UI 截图与录屏未获取，**不能据此宣称赛事全部验收通过**。
