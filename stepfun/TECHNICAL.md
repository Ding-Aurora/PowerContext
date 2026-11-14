# Pocket Seek · 一页技术说明

**目标**：浏览器本地向量化的迷你知识库。文档/查询均在 Web Worker 中运行 Transformers.js 3.8.1；Node 服务只接收向量并调用 seekdb-js 1.4.0，未安装默认 embedding 插件、不调用云端推理 API。

**模型**：Apache-2.0 的 Xenova/all-MiniLM-L6-v2，固定 revision `751bff37182d3f1213fa05d7196b954e230abad9`，384 维 mean pooling + L2 normalize。使用模型仓库公开提供的 INT8 ONNX `model_quantized.onnx`（dtype=q8），对照为 `model.onnx`（fp32），并非自行重新量化。此模型适合英文，中文不是目标质量范围。来源 https://huggingface.co/Xenova/all-MiniLM-L6-v2 。

**端侧后端**：显式请求 WebGPU；无 navigator.gpu、无 adapter 或 WebGPU 模型初始化失败时自动尝试 WASM。界面显示实际后端；强制 WASM 复选框用于验证降级。模型下载由浏览器执行并缓存，主线程负责交互，Worker 负责推理。

**存储检索**：seekdb-js 创建 cosine HNSW(384) + space 全文索引，embeddingFunction=null。upsert 保存 ID、原文、source 元数据与客户端向量。调用 hybridSearch，由 SDK 生成数据库原生 DBMS_HYBRID_SEARCH 查询并在库内 RRF，前后端均不自行融合两路结果。批次写入后统一 refresh_index，成功才显示完成；刷新错误不隐瞒。服务按集合串行读写，同一页面操作期间锁定集合输入；精度后缀防止 fp32/q8 混写。导入采用内容哈希 ID，重复内容幂等更新。数据库文件持久化，进程内队列不充当检索存储。

**优化与评测设计**：批大小 1 对照 8，120 词步长/160 词分段；按完整导入统一刷新；模型复用。固定 12 篇原创英文文本/6 个查询，预热后重复 3 次，记录 Recall@5、向量化/写入/刷新/检索/端到端时间；FP32、q8-WebGPU、q8-WASM 分别运行导出 JSON。比较批大小时必须保持精度和后端一致。端到端计时到响应解析完成，未包含随后浏览器绘制。

**实际验证与缺口**：2026-11-14，Windows、Node 22.5.1：npm 安装、2 项单元测试和 Vite 构建通过。真实 seekdb 读写、浏览器 GPU/WASM 推理、量化文件实际下载体积及 Recall/延迟对比尚未完成，不能宣称题目已全部验收。体积/压缩比与质量变化均待实测，不以估算替代。当前提交是可继续部署验证的源码版本。
