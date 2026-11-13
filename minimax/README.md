# 规有所依：SDD 工程上下文模块

本项目基于 OceanBase `2026-competition-ecosystem` 分支
`d647275c308e09b7b623f322a26f5c4e85734fb0`，资产均位于 `minimax/`。

**当前状态：实现与本地验证，不是已完成的比赛验收。** 尚未提供 MiniMax
凭据及 seekdb/OceanBase 服务，因此没有真实模型修改记录及数据库验收记录，
不能据此声称六项全部通过或获得 20 分。业务文件当前保留修改前版本，真实
MiniMax 运行后产生修改后快照和差异。不存在预制的模型响应或伪造成功日志。

## 环境与初始化

Python 3.11；PowerContext 1.2.0（官方 Python client + 同进程 HTTP ASGI server）；
PyMySQL 1.1.2（seekdb/OceanBase MySQL 协议）；pytest 8.4.2；MiniMax HTTPS
Chat Completions API，默认模型 MiniMax-M2.5，可通过环境变量调整。

```bash
cd minimax
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

参照 `.env.example` 设置进程环境变量。配置文件不会自动加载。
不要提交真实凭据。使用既有 seekdb/OceanBase 服务，或在装有 Docker 的机器上
运行 `docker compose up -d`。该 compose 配置需要在目标环境实测，当前没有
进行容器验证。通过 MySQL 客户端连接管理员账号，执行：

```sql
CREATE DATABASE IF NOT EXISTS sdd CHARACTER SET utf8mb4;
```

建议给本示例单独数据库和账号；`ingest` 会事务替换其 `sdd_documents` 表内容，
不适合多个工程共享同一张表。数据库连接通过 `SDD_DB_*` 环境变量设置。

## 验证样例与调用入口

任务：商品列表增加 `status` 筛选。有效值为 None、active、archived；分类与
状态取交集；缺少状态的旧数据不匹配显式状态；非法值即使对空列表也报错。
保留分类筛选、输入顺序、不修改输入及浅复制行为。初始数据在测试 fixture 中。

必须来源：

* `demo/specs/catalog.md`：CAT-001 原有约束、CAT-002 新需求、CAT-003 验证规则。
* `demo/catalog.py::list_products`：待改代码。
* `demo/tests/test_catalog.py`：目标功能及兼容性测试。

```bash
python -m sdd ingest
python -m sdd context
python -m sdd develop
```

`ingest` 导入当前规格、代码和测试并记录哈希；`context` 使用数据库实际查询结果
形成含来源、行号、内容和 PowerContext 历史状态的 JSON。
`develop` 先运行修改前测试，要求功能失败但回归通过，再将上下文发送给真实
MiniMax，保存候选代码、请求内容（不含凭据）、响应 ID、用量、差异及状态。
不保存模型私有推理内容。模型输出不是可信代码，应先检查 `.sdd/after.py`
和 `.sdd/change.patch`；然后复制候选并运行：

```bash
cp .sdd/after.py demo/catalog.py
python -m sdd verify
python -m sdd ingest
python -m sdd resume
```

Windows 复制命令：`Copy-Item .sdd/after.py demo/catalog.py`。
`verify` 要求测试文件哈希与修改前一致，运行同一套测试，将结果写入
PowerContext。每条命令均为新进程；`resume` 创建新的 PowerContext 服务实例，
打开持久化数据库并将既有任务进度、待办和验证结果加入后续上下文。

`--run-dir PATH` 可指定独立运行目录，所有步骤必须使用同一个目录。
重置时从 `.sdd/before.py` 恢复 `demo/catalog.py`，使用新的运行目录，再执行
`ingest`。不要覆盖已有验收证据。

## 规格更新验收

在 `demo/specs/catalog.md` 增加一个唯一标记或修改规格条目，再执行 `ingest`
和 `context`，检查来源内容和 sha256 随之变化。未重新导入的源文件变化会报错，
防止把过期数据库内容当成当前上下文。真正改变业务行为时，应同步更新任务测试，
并从新的基线开始一次开发流程；不得在同一次修改前后对比中改变测试预期。

## 证据和提交

`.sdd/` 默认忽略，避免意外上传任务数据。完成真实运行后，将审查过的下列文件
复制到 `evidence/live/` 并提交：`ingest.json`、`database-query.json`、
`context.json`、`minimax.json`、`before.py`、`after.py`、`change.patch`、
`tests-before.json`、`tests-after.json`、两个 XML 测试报告、`state-written.json`、
`state-verified.json`，以及保存的 `resume` 输出。测试 JSON 记录命令、退出码、
代码和测试 SHA-256，可精确对应快照。不要提交状态数据库或任何密钥。

## 一页技术说明

调用链：任务 JSON → seekdb/OceanBase 查询 → 带来源的规格/代码/测试上下文
→ PowerContext 既有进度 → MiniMax 生成候选 → 相同测试验证 → PowerContext
持久化验证结果 → 新进程恢复并再次构造上下文。

数据库存储文档全文和内容哈希，采用参数化 SQL 词项匹配；这适合本例的小规模
工程，不宣称支持大仓库语义检索。重新导入是原子替换，删除的资料不会继续命中。
必要来源是验收校验条件，不直接塞入查询结果；检索漏项会明确失败。

PowerContext 使用本地 SQLite 作为其官方持久化后端；工程资料的存储和检索
独立使用 seekdb/OceanBase。恢复不是读取自制 JSON 冒充 PowerContext，实际调用
官方 create_scope / remember_memory / search_memory 接口。ASGI 在进程内调用，
无对外暴露的未认证服务。

MiniMax 只负责目标代码生成；适配器只允许写候选快照，人工检查后再应用到单个
业务文件。测试文件不由模型改写。生成不保证一次通过，失败会记录并要求修复，
不会自动把失败标为成功。

本例业务代码、测试及适配模块为新编写。PowerContext 使用方式参考官方
`examples/jupyter/01_memory_across_sessions.ipynb` 和 `_tutorial.py`（Apache-2.0）；
本地 ASGI 生命周期集成用于避免额外常驻服务。开发使用了 OpenAI Codex；
只有真实运行 `develop` 后，才能声称 MiniMax 参与目标修改。
