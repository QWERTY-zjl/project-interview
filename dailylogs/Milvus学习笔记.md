# Milvus 向量数据库学习笔记

> 记录时间：2026-10-08
> 定位：AI 原生场景的开源向量数据库，理解概念 + 知道何时该用即可，当前项目不引入

## 一、Milvus 是什么

- 开源向量数据库（Apache 2.0 协议），由 Zilliz 开发维护，GitHub 47k+ stars，全球最流行的开源向量数据库
- 专门解决一个问题：**在海量高维向量中快速找到"最相似"的 K 个**（相似度搜索）
- 典型场景：RAG 知识库、语义搜索、推荐系统、AI Agent 记忆、以图搜图

### 为什么需要专门的向量数据库

文本/图片经过 embedding 模型变成一串数字（如 1536 维向量），判断"语义是否相似"就是算向量间距离。数据量小可以暴力算，但百万级以上暴力计算慢到不可用——必须用专门索引（近似最近邻搜索 ANN）。向量数据库 = 存向量 + 建向量索引 + 高效检索。

## 二、三种部署形态（重要）

| 形态 | 怎么跑 | 适用 | 依赖负担 |
|---|---|---|---|
| **Milvus Lite** | `pip install pymilvus`，作为库嵌入 Python 进程 | 学习、原型、小项目（百万级以下） | 零，和 SQLite 的思路一样 |
| **Standalone** | Docker 单容器 | 生产/测试，百万~千万级 | 一条 docker run |
| **Distributed** | Kubernetes + Helm | 企业级，亿级向量、高 QPS | etcd + MinIO + 消息队列等一组组件 |

学习从 Lite 开始：**同一个 API（pymilvus），三种形态通用**，代码不用改，只换连接串。

## 三、核心概念（对照关系型数据库理解）

| Milvus 概念 | 类比关系型数据库 | 说明 |
|---|---|---|
| Collection | 表 | 存放向量的容器 |
| Schema | 表结构 | 定义字段：标量字段（id、text）+ **vector 字段（必填，指定维度）** |
| Entity | 行/记录 | 一条数据 = 标量字段 + 向量 |
| Index | 索引 | 向量专用索引，见下表 |
| Metric Type | — | 相似度度量：余弦相似度（最常用）/ L2 欧氏距离 / 内积 |

### 常用索引类型（按规模/资源选）

| 索引 | 特点 | 场景 |
|---|---|---|
| **HNSW** | 基于图，查询快、召回率高，内存占用大 | 默认首选 |
| **IVF_FLAT** | 聚类分桶，内存小、精度可调 | 资源有限 |
| **IVF_PQ** | 乘积量化压缩，内存省 8~16 倍 | 超大规模省内存 |
| **DiskANN** | 磁盘索引 | 向量总量超内存 |
| **GPU 索引** | CUDA 加速，亚毫秒延迟 | 超高 QPS |

## 四、基本工作流（三步）

```
1. 向量化：调 embedding 模型把文本/图片变成向量
   （DashScope text-embedding-v3、开源 sentence-transformers 等）
2. 插入：insert（标量字段 + 向量）进 Collection
3. 检索：search（查询向量 + topK），返回最相似的 K 条及相似度分数
```

最小代码示例（Milvus Lite）：

```python
from pymilvus import MilvusClient

client = MilvusClient("milvus_demo.db")      # 本地文件，和 SQLite 一样简单
client.create_collection(collection_name="demo", dimension=4)

client.insert(collection_name="demo", data=[
    {"id": 1, "vector": [0.1, 0.2, 0.3, 0.4], "text": "Vue3 性能优化"},
    {"id": 2, "vector": [0.9, 0.8, 0.7, 0.6], "text": "MySQL 索引原理"},
])

results = client.search(
    collection_name="demo",
    data=[[0.1, 0.2, 0.3, 0.35]],            # 查询向量
    limit=2,                                  # topK
    output_fields=["text"],
)
```

真实场景中 `vector` 列的值来自 embedding 模型的输出，而不是手写数字。

## 五、Milvus vs pgvector（选型结论）

| 维度 | pgvector | Milvus |
|---|---|---|
| 本质 | PostgreSQL 的扩展插件 | 独立的专用向量数据库 |
| 适用数据量 | ≤500 万条 | 千万~百亿级 |
| 运维复杂度 | 极低（跟着 PG 走） | Standalone 低 / Distributed 高 |
| 混合检索 | SQL 一条语句搞定（向量+标量过滤） | 支持但不如 SQL 直观 |
| 典型场景 | 已有 PG 的中小项目、RAG/MVP 默认选择 | 亿级规模、超高 QPS、GPU 加速 |

**共识**：小规模/已有 PG → pgvector；亿级/超高并发 → Milvus。两者不是竞争关系，是不同规模阶段的工具。

## 六、学习路径建议

```
第 1 步：Milvus Lite（pip install，本地跑通增删改查）—— 半天
第 2 步：接一个真实小 demo，比如给面试系统做"相似题目推荐"：
        题目文本 → embedding → 存 Milvus Lite → 搜相似题 —— 1~2 天
第 3 步：跑一个 RAG 教程（官方文档有完整中文教程）—— 1~2 天
第 4 步：Docker 起 Standalone，体验和生产一致的单机部署 —— 半天
（Distributed 企业级架构知道概念即可，用不到不用学）
```

## 七、官方资源

- 官方文档（中文）：https://milvus.io/docs
- Milvus Lite 介绍：https://milvus.io/docs/milvus_lite.md
- RAG 教程：https://milvus.io/docs/build-rag-with-milvus.md
- 向量库基准测试工具 VectorDBBench：https://github.com/zilliztech/VectorDBBench
- pymilvus SDK（pip 包名）：`pip install pymilvus`
