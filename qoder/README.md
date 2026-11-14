# 研究续航站（Research Continuation Station）

为学习和科研用户解决「隔几天回来，忘记上次进展、失败尝试和下一步」的问题。
用户保存一次学习/实验记录，下次打开能看到**有依据**的进度回顾和续做清单。
所有历史记录通过 **PowerContext 持久化上下文**读写，不使用进程内数组或浏览器
localStorage 充当记忆。

- 后端：Python 标准库 `http.server`（无第三方 Web 框架），服务端代理 PowerContext。
- 前端：轻量原生 HTML/CSS/JS，无构建步骤。
- 记忆后端：PowerContext 1.5.1（本机 SQLite 轻量模式，无需 seekdb / Embedding / Rerank）。
- 续做清单：**结构化输入 + 确定性模板**生成，不调用任何模型、无需模型密钥，绝不编造未发生的进展。

## 目录

```
qoder/
├── config.py               # 读取 .env；token 脱敏工具；scope 前缀掩码
├── powercontext_client.py  # PowerContext HTTP 客户端（真实读写、异常分类、脱敏 HTTP 证据）
├── continuation.py         # 会话编码/分组 + 确定性续做清单（带来源引用）
├── server.py               # 静态页 + /api 代理 + 服务端项目索引
├── static/                 # index.html / app.js / styles.css（前端）
├── scripts/                # start_powercontext.ps1 / start_app.ps1
├── tests/                  # test_unit.py（离线单测）、verify_samples.py（真实端到端验收）
├── devtools/probe_api.py   # 真实 API 结构探针（开发期使用）
├── data/                   # 服务端项目索引 projects.json（运行期生成，已被 .gitignore 忽略）
├── evidence/               # 真实运行证据（脱敏）
├── docs/                   # DEVLOG / VALIDATION
└── site/                   # Qoder Sites 展示网站（静态，本地预览，暂不发布）
```

## 快速开始

前置：本机安装 Python 3.11+，并准备 PowerContext 1.5.1 服务（见下）。

1) 启动 PowerContext（SQLite 轻量模式，数据目录隔离在本目录 `.pc-home`）

```powershell
# 方式 A：使用本仓库脚本（自动定位 work/venv 里的 powercontext，或用 PATH 中的）
powershell -ExecutionPolicy Bypass -File scripts\start_powercontext.ps1

# 方式 B：手动。先 pip 安装官方包，再以前台方式启动：
#   python -m pip install powercontext[cli,server]==1.5.1
#   $env:POWERCONTEXT_HOME = "<本目录>\.pc-home"
#   powercontext server run --host 127.0.0.1 --port 8777
```

保持该进程运行。`--port` 默认 8777（可用 `$env:PC_PORT` 改）。不要开放到公网。

2) 配置（可选）

```powershell
copy .env.example .env
# 编辑 .env：POWERCONTEXT_URL / POWERCONTEXT_TOKEN / APP_HOST / APP_PORT
# 本地演示可保持默认；token 留空。token 只被后端读取，绝不发给浏览器或写入日志。
```

3) 启动研究续航站应用

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_app.ps1
# 或：python server.py
```

打开 http://127.0.0.1:8688/ 。

## 使用

- 新建项目（名称 + 研究目标）→ 选中项目 → 填写本次进展/已尝试方法/遇到的问题/下一步 →「保存到 PowerContext」。
- 只有真实写入成功后才提示成功；服务不可用会如实报错（HTTP 502，且不落“已保存”）。
- 关闭再重新打开应用，选回同一项目，在召回框输入“下一步做什么”，即可看到带来源引用的续做清单与可追溯原始记录。
- 项目切换：项目 A 的记录不会出现在项目 B（服务端按 scope 隔离召回）。

## 测试

```powershell
# 离线单元测试（无需 PowerContext，9 项）
python tests\test_unit.py

# 真实端到端验收（自动启动独立端口的 PowerContext + 应用，跑样例 1–5）
# 需要本机可用的 powercontext 可执行（默认探测 work/venv 或 PATH，可用 POWERCONTEXT_BIN 覆盖）
python tests\verify_samples.py
```

产物：`evidence/verify_report.json`（逐条预期/实际）、`evidence/http_exchange.log`（脱敏 HTTP 记录）、`evidence/app.log`、`evidence/pc.log`。

## 安全与边界

- PowerContext 凭据只保存在服务端进程（环境变量 / `.env`），不下发浏览器、不写日志/证据；证据中 token 统一替换为 `[REDACTED]`，scope_id 只显示前缀。
- **scope_id 是数据分区，不是授权**。本演示版仅支持单人本地使用，不宣称多租户隔离；公网/多人使用需另加可信鉴权。
- PowerContext 不可用时：保存/召回如实失败，不伪造历史或成功提示。
- 续做清单由模板生成，仅复述用户保存的内容并附 artifact/revision 引用，不推断未发生的进展。

## 验收状态（详见 docs/VALIDATION.md）

- 真实端到端样例 1–5：已在真实 PowerContext 1.5.1 上运行，**6/6 通过**（见 `evidence/verify_report.json`）。
- 离线单元测试：**9/9 通过**。
- 应用级 HTTP 往返（创建→保存→召回）已对真实服务跑通，见 `evidence/app_api_roundtrip.json`。
- 浏览器 UI 走查截图：**未采集**（未验证，不伪造）。
- 公开网站 URL / 账号 UID / Qoder 开发录屏：**未获取**，发布前不得标注为已通过全部验收。

## 来源

- PowerContext API 速查：https://powercontext.oceanbase.io/zh/docs/develop/api-quickstart/
- PowerContext 仓库：https://github.com/oceanbase/powercontext （参考版本 1.5.1，接口以本机安装包 OpenAPI 为准）
