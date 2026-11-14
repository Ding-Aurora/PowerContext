# Pocket Seek 运行说明

## 启动

需要 Node.js 22、当前 Chrome/Edge、Hugging Face 模型下载网络。默认 seekdb 内嵌模式使用官方 @seekdb/js-bindings 原生库，首次运行可能需要下载平台二进制，支持范围以 SDK 说明为准。

```
npm ci
npm test
npm run build
npm start
```

打开 http://localhost:5173 。服务仅绑定本机，不是公网多租户产品。`npm start` 使用 Vite 中间件提供页面。`.npmrc` 的 legacy-peer-deps 避免可选默认 embedding 插件的 workspace 依赖解析问题；后端不需要也不执行任何 embedding 模型。

如嵌入式库无法下载，可使用已经部署的 seekdb server：设置 `SEEKDB_HOST`、`SEEKDB_PORT`(2881)、`SEEKDB_USER`、`SEEKDB_PASSWORD`、`SEEKDB_DATABASE`(test)，再启动。切勿把密码提交到 GitHub。数据库须支持 DBMS_HYBRID_SEARCH 和 dbms_index_manager.refresh，建议 seekdb 1.4；数据库环境仍待实机验证。部署参考 https://www.oceanbase.ai/docs/deploy-overview/ 。

## 体验

1. 加载默认 q8 模型，检查实际后端提示。首次模型下载可能较慢。
2. 知识库输入 demo，上传 .txt/.md 或粘贴英文文档，点击导入。等待“完成”，若失败先解决错误再查询。
3. 输入自然语言问题，查看按数据库返回顺序显示的原文结果。
4. 同一知识库追加新文本再查询；换另一个名字查询应看不到原集合内容，再切回 demo。
5. 勾选强制 WASM 并重新加载，重复完整流程。也应在真实禁用 WebGPU 的浏览器环境测试自动降级。

这是本地单用户应用，未提供登录、授权、并发多进程协调。上传的是原文与向量，并非隐私数据不离设备的远程部署方案；默认所有服务运行在本机。

## 性能质量复现

固定同一设备/浏览器；依次运行 fp32、q8（GPU）、q8（强制 WASM）。每次加载后点“运行固定评测”，然后导出 JSON。固定测试集定义在 shared.js，全部原创，无需外部数据。每次自动创建独立测试集合，避免残留污染。每个查询重复 3 次，记录原始耗时和 Recall@5。将相同配置的原始数据取中位数，不选择最快一次。

模型首次下载和加载一起记录为 loadMs；再次加载的缓存热启动应单独记录。浏览器开发者工具 Network 可检查仅下载模型文件、无云推理请求。按同一 revision 下载 onnx/model.onnx 与 onnx/model_quantized.onnx，以文件字节数分别记录 fp32/q8 体积，压缩比为前者除以后者；共享 tokenizer/config 文件应按同口径纳入或明确排除。不能用 HTTP 压缩传输大小混同比较模型体积。

批处理单项比较：保持 dtype、后端与数据相同，只将批大小 1 改为 8，重复评测。导入时间拆为 embeddingMs/writeMs/refreshMs；查询拆为 embeddingMs/searchMs/endToEndMs。界面记录不自动宣称性能提升。

## 验证状态

已通过依赖安装、2 项单元测试、前端构建。尚未通过真实浏览器与 seekdb 全链路测量，未提供伪造数据。提交正式评测前必须完成以上步骤，并把导出的日志、浏览器/设备/seekdb 版本及模型体积填入技术说明。

## 代码入口

- worker.js：浏览器模型和后端选择
- server.mjs：seekdb 写入、刷新与库内混合检索
- main.js：状态隔离、导入/查询、评测与导出
- shared.js：分段与固定语料/查询/相关性标签
- package-lock.json：依赖锁定；TECHNICAL.md：一页说明

依赖来自 seekdb-js、Transformers.js、Express、Vite；模型使用公开量化版本，未复用其他参赛作品。原始库许可见相应 npm 包。
