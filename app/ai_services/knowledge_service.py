"""
岗位面试知识库服务模块
====================
本模块负责知识库的「加载」与「检索」两件事：
    1. load_kb(position_name)    —— 按岗位加载知识库条目（app/knowledge/*.json）
    2. search_kb(entries, text)  —— 混合打分检索，返回最相关的 top_k 条

【知识库是什么】（RAG 通俗版）
    知识库 = 一份结构化存放的岗位考点资料（app/knowledge/ 下的 JSON 文件）。
    RAG（Retrieval-Augmented Generation，检索增强生成）= 大模型出题前，
    先来这里检索（Retrieval）相关考点，把结果拼进提示词（Augmented）再出题
    （Generation）——让题目有真实依据，而不是模型凭记忆编（可能过时、可能幻觉）。

【检索方式：pgvector 向量检索 + 关键词保底】
    1. 向量检索（PG 模式）：查询文本与条目文本各经 text-embedding 模型变成
       一串数字（1024 维向量），条目向量预先存进 PostgreSQL 的 kb_embeddings
       表（pgvector 扩展），检索就是一条 SQL——ORDER BY embedding <=> 查询向量
       按余弦距离排序取最近 top3。"锁的坑"也能对上"线程安全与锁"，
       这是字面匹配做不到的。条目内容由 build_embeddings.py 离线向量化入库；
    2. 关键词检索（保底）：条目 keywords/topic 在查询文本中每命中一个词 +1。
       在 SQLite 回退模式 / 向量表为空 / 查询向量化失败时自动生效。

【设计原则】
    1. 职责分离：本模块只负责"加载与检索"，怎么用检索结果由各智能体服务自己
       决定（与追问智能体"只返回决策、写入由 API 层做"同一思路）；
    2. 静默降级（三级兜底）：pgvector 不可用/向量化调用失败 → 退化为关键词
       检索；知识库文件缺失/检索零命中 → 返回空列表由调用方回退通用考点
       ——知识库是增强项不是必需项，面试主流程永不因它阻断；
    3. 依赖最小：向量检索复用项目已有的 PostgreSQL（装 pgvector 扩展即可，
       镜像 pgvector/pgvector:pg16），不引入 Milvus 等独立向量数据库服务；
       Python 侧不装 pgvector 适配包——向量以文本字面量 '%s::vector' 传入。
"""

import json
import logging
from pathlib import Path

from openai import OpenAI

from app.config.config import DASHSCOPE_API_KEY, DASHSCOPE_BASE_URL, EMBEDDING_MODEL
from app.db.db_pool import db_pool
# 向量检索走项目统一的连接池（backend 属性区分 PG/SQLite 双轨；
# 只 import config 与 db 模块，无循环依赖）

logger = logging.getLogger(__name__)

# Path(__file__) 是本文件的路径；resolve() 转成绝对路径，parents[1] 从
# app/ai_services/ 回到 app/ 目录 —— 即知识库文件固定放 app/knowledge/ 下。
# 用「相对本文件的路径」而不是写死盘符，换电脑/换目录都能跑。
KB_DIR = Path(__file__).resolve().parents[1] / "knowledge"

# 中文岗位名 → 知识库文件名的映射表（精确匹配，优先级最高）。
# 数据库里 interview_types 表的岗位名是中文（如"后端开发面试"），
# 而知识库文件用英文命名（python_backend.json），需要这层映射对上。
# 注意：key 统一小写，查询时也会 lower() 后再查，避免「Python后端」匹配不上。
POSITION_FILE_MAP = {
    "后端开发面试": "python_backend",
    "python后端": "python_backend",
    "python后端开发": "python_backend",
    "python 后端": "python_backend",
    "前端开发面试": "frontend",
    "前端": "frontend",
    "数据分析面试": "data_analysis",
    "数据分析": "data_analysis",
    "产品经理面试": "product_manager",
    "产品经理": "product_manager",
    "医学面试": "medical",
    "医学": "medical",
    "机械面试": "mechanical",
    "机械": "mechanical",
    "机械工程师面试": "mechanical",
    "金融面试": "finance",
    "金融": "finance",
    "化学面试": "chemistry",
    "化学": "chemistry",
    "生物面试": "biology",
    "生物": "biology",
}

# 关键词包含规则（全等匹配失败后的兜底）：岗位名只要"包含"该词即命中。
# 【为什么需要】实测岗位名可能是短名——数据库/前端传「后端」而不是
# 「后端开发面试」，全等映射枚举不完各种写法，包含式匹配一劳永逸。
# 规则按顺序尝试，第一条命中的生效；顺序即优先级：
# 「数据分析」排在「数据」前（更具体的词先命中）、「python数据分析」
# 会命中「数据分析」而非 python_backend；「行为面试」等不含上述词，
# 走最后一级岗位名当文件名的兜底。
POSITION_SUBSTR_RULES = [
    ("后端", "python_backend"),
    ("前端", "frontend"),
    ("数据分析", "data_analysis"),
    ("产品", "product_manager"),
    ("医学", "medical"),
    ("临床", "medical"),
    ("医疗", "medical"),
    ("医药", "medical"),
    ("机械", "mechanical"),
    ("金融", "finance"),
    ("银行", "finance"),
    ("证券", "finance"),
    ("化学", "chemistry"),
    ("化工", "chemistry"),
    ("生物", "biology"),
    ("数据", "data_analysis"),
    ("python", "python_backend"),
]


def _resolve_kb_name(position_name: str) -> str:
    """把岗位名解析成知识库文件名（不含 .json 后缀）。

    三级匹配：全等映射 → 关键词包含 → 岗位名本身当文件名试。
    都查不到时返回的文件名大概率不存在，load_kb 会按「无知识库」处理。
    """
    key = position_name.strip().lower()
    kb_name = POSITION_FILE_MAP.get(key)
    if not kb_name:
        for token, name in POSITION_SUBSTR_RULES:
            if token in key:
                kb_name = name
                break
    # 兜底：调用方直接传英文名（如 "python_backend"）也能工作
    return kb_name or key


def load_kb(position_name: str) -> list:
    """加载指定岗位的知识库条目。

    position_name 是岗位名（interview_types.name，如"后端开发面试"或短名
    "后端"），先经映射解析成文件名（python_backend.json）再读取。
    文件不存在 / JSON 损坏时返回空列表——调用方按「没有检索结果」处理，
    出题主流程不中断（静默降级，不抛异常）。
    """
    if not position_name:
        return []
    kb_name = _resolve_kb_name(position_name)
    kb_file = KB_DIR / f"{kb_name}.json"

    if not kb_file.exists():
        logger.info(f"[KB] 岗位「{position_name}」暂无知识库文件，按无知识库处理")
        return []

    try:
        # encoding="utf-8" 必须显式指定：Windows 默认编码是 GBK，中文会乱码
        with open(kb_file, "r", encoding="utf-8") as f:
            entries = json.load(f)
        # isinstance 再拦一道：万一文件内容不是数组（比如误存了对象），也当空库
        return entries if isinstance(entries, list) else []
    except Exception as e:
        # JSON 半截/编码错误等所有异常：记警告并返回空列表，绝不向上抛
        logger.warning(f"[KB] 知识库文件读取/解析失败（已降级为无知识库）: {e}")
        return []


# DashScope 客户端懒加载单例（与 question_service 同款模式：
# 模块导入时不创建，首次真正调 embedding 时才建，避免未配 key 时炸服务）
_client = None


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=DASHSCOPE_API_KEY,
            base_url=DASHSCOPE_BASE_URL,
            timeout=5.0,
            # ↑ 5 秒超时：向量化只是出题链路的"加餐"，卡住会拖慢整场面试开场的
            #   出题体验，宁可超时失败降级为关键词检索，也不让候选人干等
        )
    return _client


def embed_query(text: str):
    """把查询文本变成向量（调百炼 text-embedding 模型）。

    成功返回 [1024个浮点数]；任何失败（未配 key / 网络超时 / 配额用尽）返回
    None——调用方把 None 传给 search_kb_vector 即自动退化为关键词检索。
    """
    if not text or not DASHSCOPE_API_KEY:
        return None
    try:
        resp = _get_client().embeddings.create(model=EMBEDDING_MODEL, input=[text])
        return resp.data[0].embedding
    except Exception as e:
        logger.warning(f"[KB] 查询向量化失败（本次退化为关键词检索）: {e}")
        return None


def vector_to_pgtext(vec: list) -> str:
    """把 Python 浮点列表转成 pgvector 接受的文本表示 '[0.1,0.2,...]'。

    pgvector 支持从文本字面量强转（SQL 里 %s::vector），因此无需安装
    pgvector 的 Python 适配包——零新增 pip 依赖。
    与 build_embeddings.py 中的同名函数保持一致（入库/检索同一种格式）。
    """
    return "[" + ",".join(f"{v:.6f}" for v in vec) + "]"


# 向量检索的最低语义相关度（用 pgvector 的余弦"距离"表达）：
# pgvector 的 <=> 是余弦距离（1 - 余弦相似度），越小越相关。
# 相似度 0.3 门槛 → 距离 < 0.7：低于它的条目与查询"话不投机"，
# 硬凑进 top3 只会往出题 prompt 里塞无关考点，宁缺毋滥。
MAX_COSINE_DISTANCE = 0.7


def search_kb_vector(position_name: str, query_vec: list, entries: list, top_k: int = 3):
    """pgvector 向量检索：库里查最相似的 top3，再映射回条目 dict。

    前置条件（任一不满足即返回 None，调用方退化为关键词检索）：
    - PG 模式（db_pool.backend == "postgresql"）：SQLite 没有 VECTOR 类型和
      <=> 操作符，vector_to_pgtext 生成的 SQL 在 SQLite 兼容层会变成 ?::vector
      直接语法错误，所以入口处就拦住；
    - query_vec 非 None（embed_query 成功）。

    条目内容仍以 JSON 文件为唯一数据源——向量表只存 (id, 向量)，
    检索先在库里按距离选出 id，再回已加载的条目列表里挑出对应 dict，
    避免"向量库里冗余一份条目内容"的双源不一致问题。

    返回命中条目列表（可能为空=库里没向量/全被距离门槛淘汰）；
    返回 None 表示"向量检索这条路走不通"，请走关键词。
    连接任何异常同样返回 None——pgvector 是增强项，绝不阻断出题。
    """
    if not query_vec or db_pool.backend != "postgresql" or not entries:
        return None

    conn = None
    try:
        kb_name = _resolve_kb_name(position_name)
        vec_str = vector_to_pgtext(query_vec)
        conn = db_pool.get_connection()
        cur = conn.cursor()
        # <=> 是 pgvector 的余弦距离操作符（1-相似度），升序 = 最相似在前；
        # WHERE 距离 < 0.7 相当于相似度 > 0.3 的"宁缺毋滥"门槛；
        # %s::vector 把文本参数强转为向量类型参与距离计算
        cur.execute(
            '''
            SELECT id FROM kb_embeddings
            WHERE kb_name = %s
              AND embedding <=> %s::vector < %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            ''',
            (kb_name, vec_str, MAX_COSINE_DISTANCE, vec_str, top_k),
        )
        rows = cur.fetchall()
        if not rows:
            return []
        # 保序映射：按库里的相似度顺序（rows 顺序）从条目列表取对应 dict
        by_id = {e.get("id", ""): e for e in entries if isinstance(e, dict)}
        return [by_id[r["id"]] for r in rows if r["id"] in by_id]
    except Exception as e:
        # 表还没建（没跑过入库脚本）/ 扩展缺失 / 连接问题：统统降级关键词
        logger.warning(f"[KB] pgvector 检索不可用（已降级为关键词检索）: {e}")
        return None
    finally:
        if conn is not None:
            db_pool.return_connection(conn)


def search_kb(entries: list, text: str, top_k: int = 3) -> list:
    """关键词检索（保底路径）：按命中数打分返回 top_k 条。

    pgvector 不可用时（SQLite 回退 / 查询向量化失败 / 向量表未建）由调用方
    走到这里。打分规则：条目 keywords/topic 在查询文本中每命中一个词 +1，
    纯字面匹配——简历技能栈越长命中的词越多，得分越高。
    零命中返回空列表，由调用方决定是否回退为通用考点。
    """
    if not entries or not text:
        return []

    lower_text = text.lower()  # 查询文本转小写一次，循环里反复用（避免重复转换）
    scored = []
    for entry in entries:
        # 需要匹配的词 = 关键词列表 + 知识点名，全部拼在一起检查
        terms = entry.get("keywords", []) + [entry.get("topic", "")]
        # sum(...) 对每个词数一遍是否命中后求和，就是这条目的得分；
        # `if term` 跳过空字符串（空串 in 任何文本恒为 True，会虚加分）
        score = sum(1 for term in terms if term and term.lower() in lower_text)
        if score > 0:
            scored.append((score, entry))

    # 按得分从高到低排序；key=lambda pair: pair[0] 表示按元组第一项（分数）排
    scored.sort(key=lambda pair: pair[0], reverse=True)
    # 切片 [:top_k] 取前 N 条，丢弃分数只返回条目本身
    return [entry for _, entry in scored[:top_k]]


def build_kb_hint(hits: list) -> str:
    """把检索命中的条目格式化成可拼进提示词的文本块。

    每条一行「- 考点名：核心问题」，只注入考点与问法参考而非答案原文，
    既控制 token 用量，又避免模型照抄导致题目雷同。
    空命中返回空串，调用方据此跳过注入。
    """
    return "\n".join(
        f"- {e.get('topic', '')}：{e.get('core_question', '')}"
        for e in hits
        if isinstance(e, dict)
    )
