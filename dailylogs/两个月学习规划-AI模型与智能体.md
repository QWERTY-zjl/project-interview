# 两个月学习规划：AI 模型与智能体开发

> 制定时间：2026-10-08
> 时间预算：每天 2.5 小时，共 8 周 ≈ 150 小时
> 硬件约束：RTX 4060 8GB（与 MinerU 共存，需注意显存分配）

## 零、三件必学事（本规划的锚点）

1. **自主完成 MiniMind 小模型开发全流程**（预训练 → SFT → 评估 → gguf 导出 → Ollama 部署）
2. **智能体 + 知识库练习**（RAG + 图知识库 GraphRAG + 意图路由）
3. **Ollama 部署表情识别模型**（本地多模态 VLM 方案）

## 一、关键技术决策（含理由）

| 决策 | 结论 | 理由 |
|---|---|---|
| 表情识别本地化路线 | Ollama 跑多模态 VLM（如 `qwen2.5vl:3b` 量化版），**不是** YOLOv8/FER 传统 CV 模型 | Ollama 只能部署 gguf 格式的 LLM/多模态大模型，跑不了传统 CV 模型；VLM 方案与现有 qwen3-vl-flash API 用法一致，改 base_url 即切换 |
| MiniMind 规模 | 26M（时间紧张时）/ 104M（时间富余时） | 官方为消费级显卡设计，4060 单卡可训；训练挂夜不占日间时间 |
| 向量库 | PostgreSQL + pgvector | 已定迁移 PG；向量操作收拢成 `VectorStore` 接口（`upsert` / `search` 两方法），未来切 Milvus 只换实现类；bge embedding 与向量库解耦，零改动 |
| 图数据库 | Neo4j Community Edition（Docker 单容器） | 免费版单机够用；Cypher 是简历技能点；自带 7474 可视化界面便于调试和演示 |
| GraphRAG 框架 | LightRAG（图存储后端接 Neo4j） | 微软原版 graphrag 绑 OpenAI 且重；LightRAG 轻量、支持本地模型 |
| Embedding | bge-small-zh（CPU 可跑） | 免费本地、中文效果好、512 维 |
| 智能体编排 | 意图路由（自研简单路由起步） | 初学者可控；主模型 DashScope qwen + MiniMind 本地兜底 |
| Milvus | 只学不用 | pgvector 在本项目数据规模（≤百万向量）下完全够；用 Milvus Lite 过 API + 跑官方 RAG 教程即可，笔记见《Milvus学习笔记.md》 |

## 二、三阶段计划

### 阶段一（第 1~2 周）：Ollama + 表情识别 VLM 本地化，约 35h

| 内容 | 说明 |
|---|---|
| Ollama 基础（3 天） | 安装、拉模型、REST API、gguf 导入原理——先学它，阶段二三全依赖 |
| VLM 部署（4 天） | `ollama pull qwen2.5vl:3b`，显存压测（与 MinerU 共存情况） |
| 接入面试系统（1 周） | expression_service 增加本地后端：base_url 指向 Ollama，保留 qwen3-vl-flash API 降级链 |
| 对比评估（2 天） | 本地 VLM vs qwen3-vl-flash：识别准确率 / 延迟 / 显存，写一页对比笔记 |

**验收标准**：断网状态下，本地 VLM 能对摄像头抓拍返回情绪 JSON，面试系统表情功能不挂。

### 阶段二（第 3~5 周）：MiniMind 全流程，约 50h

| 内容 | 说明 |
|---|---|
| 跑通官方仓库（第 3 周） | 数据下载/预处理 → 26M 预训练（挂夜跑）→ SFT |
| 逐环节理解（第 4 周，重点） | 不做命令的复制粘贴：读懂 tokenizer、训练循环、loss 曲线、温度采样；换自己语料（面试客服对话风格）再 SFT 一次 |
| 评估 + 导出（第 5 周前半） | 写 10~20 条测试 prompt 对比基座/SFT 前后效果 → 转 gguf → 导入 Ollama |
| 接入系统（第 5 周后半） | 智能体注册为兜底模型（意图路由：简单问题走 MiniMind，复杂走 qwen） |

**验收标准**：`ollama run my-minimind` 能对话；智能体日志能看到简单问题走了自己的模型。

### 阶段三（第 6~8 周）：智能体 + 知识库（含图），约 50h

| 内容 | 说明 |
|---|---|
| RAG（第 6 周） | bge-small-zh + pgvector，向量操作收拢成 VectorStore 接口；文档切分/召回/重排全链路手写 |
| 图知识库（第 7 周） | 先纸上设计 schema（Skill/Question/Position 节点）→ Neo4j 容器 → 学 Cypher → LightRAG 接 Neo4j 做 GraphRAG 问答 |
| 智能体编排（第 8 周） | 意图路由：闲聊/简单→MiniMind，知识问答→RAG，关系型问题→GraphRAG；Docker Compose 打包（app + postgres + neo4j + ollama） |

**验收标准**：一个聊天框，三种问题自动路由到三条链路；全系统 `docker compose up` 一键起。

## 三、图谱增强（阶段三完成后迭代，砍单顺序 4→2→3）

```
建图（技能-题目-岗位，题库天然结构化，成本低，尽早建）→
场景3 报告薄弱知识域定位（2~3天）→
场景1 自适应出题/追问链（1.5~2周，动面试核心流程，系统稳定后再做）→
场景2 多跳问答·模板化（3~5天）→
场景4 客服个性化咨询（1周）
```

- 场景 3：答错题 → 考点 → 知识域，一条 Cypher + 报告 prompt 增强，难度最低先做
- 场景 1：唯一动核心流程的（一次性出 5 题改为逐题动态生成），价值最大、代价也最大
- 场景 2：固定三个 Cypher 模板 + 参数注入，不走通用 GraphRAG
- 场景 4：客服主体完成后才有意义

## 四、时间不足时的降档机制（检查点）

预估偏乐观（初学者时间消耗在环境坑上），用两个检查点自动降档：

- **第 2 周末**：VLM 没跑通 → 表情场景降级为"Ollama 跑通 + 笔记"，直接进阶段二
- **第 5 周末**：MiniMind 没导出 → SFT 改用官方数据（不再自备语料），砍掉 GraphRAG 接入（RAG 主线照做）

**砍单原则**：砍"锦上添花"，不砍主线深度——宁可少做一件事做完，不要三件都半成品。时间只剩一半（75h）时：只保 MiniMind 最小闭环 + RAG 智能体两条主线。

## 五、执行纪律

1. **训练放夜里**：MiniMind 预训练/挂机任务夜里跑；每天 2.5h 花在读代码、写接入、调 prompt 等"人必须在场"的事
2. **schema 先行**：Neo4j 建库前先纸上画清节点与关系类型，schema 返工最痛
3. **接口先行**：VectorStore、LLM 调用都收在接口后面，给未来换实现留门
4. **每阶段以验收标准收尾**：达不到验收标准不进下一阶段（除非触发降档检查点）
