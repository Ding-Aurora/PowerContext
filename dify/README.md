# 离谱典当铺：会记仇的掌柜

玩家带来“一罐周一的困意”或“一把只会把人送回周一的伞”，与嘴碎掌柜进行虚构交易。下一次打开应用，掌柜会从 PowerContext 读取旧账，引用之前的物品、回礼及约定。开始游戏即同意保存虚构互动；请勿输入个人敏感信息。

## 技术分工与交付状态

- Dify Workflow：输入、存档标识生成、HTTP 记忆调用、LLM 角色互动、保存确认和结果输出。
- PowerContext 1.5.1：SQLite 持久化显式记忆，通过 `/v1/scopes`、`/v1/context/prepare`、`/v1/memory/remember` 接入。不需要 seekdb、Embedding 或 Rerank。
- 模型：默认 OpenAI `gpt-4o-mini`，在 Dify 安装官方 OpenAI 模型供应商插件并配置自己的 Key；也可以在唯一 LLM 节点重新选择平台已有聊天模型。
- DSL：`pawnshop.yml`，格式 0.3.0，目标 Dify 1.6.0 自部署。无需自定义插件、配套后端或初始化数据。
- 验证范围见 `evidence.json`。尚未完成真实 Dify 导入和模型端到端试玩，不能将本材料视为已通过赛事验收；必须在实际 Dify 环境执行下述步骤补齐证据。

## 部署

建议 Linux x86_64，Python 3.11，Dify 按其官方 Docker Compose 部署。资源建议 4 核 CPU、8GB 内存、20GB 可用磁盘，模型使用外部 API。Windows 本地 PowerContext 仅作为接口验证环境；正式演示建议 Linux。

1. 部署 Dify：克隆 `https://github.com/langgenius/dify`，切换 `1.6.0`，进入 `docker`，复制 `.env.example` 为 `.env`，按官方说明设置必需配置后 `docker compose up -d`。打开 Web 控制台创建管理员账号。Dify 本身使用其默认数据库，本作品的指定技术作用由 PowerContext 记忆功能承担。
2. 在独立目录创建虚拟环境，执行 `python -m pip install -r requirements.txt`。启动 `powercontext server run --host 0.0.0.0 --port 8000`。启动选项以随包 `--help` 为准；保持进程运行，保留其数据目录，重启不能清空数据。不要开放到公网。
3. `PC_URL` 必须是 Dify API/worker 容器能访问的地址。Docker Desktop 可使用 `http://host.docker.internal:8000`；Linux 可给 API/worker/相关代理配置 `extra_hosts: ["host.docker.internal:host-gateway"]`，或填同一私有网络中 PowerContext 机器的地址。不是浏览器本机的 localhost。确保 Dify SSRF 代理允许该指定私有地址，按部署的代理访问控制配置允许目标，不要全局关闭安全限制。
4. 当前 DSL 的 HTTP 节点面向受信任的单管理员演示网络，默认不携带鉴权头。若 PowerContext 开启 Bearer 鉴权，在 Dify 新建 secret 环境变量 `PC_TOKEN`，在三个 HTTP 请求节点中添加 `Authorization:Bearer {{#env.PC_TOKEN#}}`。Token 不得写入 DSL 提交版本，不得传给模型。
5. 在 Dify 工作室“导入 DSL 文件”选择 `pawnshop.yml`。只有这一个 DSL，没有导入顺序依赖。在环境变量中更改 `PC_URL`。在模型供应商中安装官方 OpenAI 插件（`langgenius/openai`，来源 Dify Marketplace），配置 Key，打开“会记仇的掌柜”节点并重新选择可用模型。插件具体安装版本由工作区选择，导出最终 DSL 时应记录该版本；此提交尚未锁定插件版本。
6. 运行预览，输入 `action` 和 `save_slot`，确认所有节点成功后发布工作流，使用 Dify 自带运行页面作为入口。不需要独立前端。若使用 API，固定 `user`，相同用户与存档代号共同决定账本；更换 user 会创建不同账本。

## 玩法和验证样例

每轮填写相同 `save_slot` 延续剧情。更换一个未使用过的代号可恢复空白状态，无需删除已有数据。存档隔离使用 Dify 的 `sys.user_id` 与存档代号生成哈希；这不是独立的多租户权限系统，公开商用需可信网关与服务端授权。

| 步骤 | 输入 | 检查内容 |
|---|---|---|
| 1 | 新存档 `review-日期-随机数`；“我把一把只会把人送回周一的伞典当给你，请成交。” | 四段输出：旧账回声、本轮奇遇、柜台收据、下步选择；收据说明已成交并给出虚构回礼；末尾明确已存档 |
| 2 | 退出运行页面后重新打开，使用同一用户与存档；“你还记得我上次典当的东西吗？它有什么副作用？” | HTTP 召回节点返回 ready，content 含上轮物品；掌柜提及周一的伞及实际旧约定，不把追问写成新成交 |
| 3 | 同存档；“我只问价：一罐周一的困意值什么？暂时不要成交。” | 收据为仅报价，不声称成交；产生两个不同选择 |
| 4 | 使用全新存档；“你记得我之前卖的伞吗？” | HTTP 召回 empty；掌柜不能声称此账本记得旧交易 |
| 5 | 临时停止自己的演示 PowerContext 再运行 | HTTP 节点失败或代码节点提示不可读取，不编造成功存档。恢复服务后重试 |

两条工作流不要同时写同一账本。写入请求默认不自动重试，避免重复记忆；网络中断可能出现“已写入但响应丢失”，需查看 PowerContext 数据确认再重试。

## 自动验证与证据

`python verify.py` 校验 DSL 图引用、执行代码节点的关键逻辑，并对正在运行的真实 PowerContext 创建随机独立测试 scope、写入一条固定的人工测试交易，再读取验证。人工交易只是接口测试夹具，不是实际 LLM 输出。脚本将响应写入 `evidence.json`，不会输出令牌。

环境变量 `POWERCONTEXT_URL` 默认 `http://127.0.0.1:8000`；开启鉴权时配置 `POWERCONTEXT_TOKEN`。测试会留下随机独立的验证账本，不修改玩家账本。

真实 Dify 验证后，请额外保存第 1、2 轮输出、HTTP 节点响应及节点执行截图，记录 Dify 和模型插件实际版本。只有完成这些才能补齐赛题要求的“实际运行结果”证据。开放式文本不要求逐字一致，但必须遵守上表事实与流程约束。

## 已知边界

- 这是荒诞文字共创，不是严格数值经济系统。模型可能产生不一致剧情，应以收据和真实召回为依据。
- 记忆召回固定公共标记 `pawnledger`，仅在当前 scope 内检索，最大 6000 字节；大量历史可能截断，不承诺无限历史或每次完整召回。试玩建议每存档 10 轮以内。
- HTTP 非成功响应会中止或标记未保存。若保存请求直接超时，Dify 会中止，不会进入成功收据节点。
- PowerContext 不可用就不伪造旧账；无模型服务无法生成本轮角色反馈。

## 来源

原创工作流与角色提示词，无复用第三方游戏或数据。接入依据官方 PowerContext API 快速开始与真实安装包：
- https://powercontext.oceanbase.io/zh/docs/develop/api-quickstart/
- https://github.com/oceanbase/powercontext
- https://docs.dify.ai/en/cloud/use-dify/nodes/http-request
- https://github.com/langgenius/dify/tree/1.6.0
