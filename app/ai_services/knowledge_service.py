"""
岗位面试知识库服务模块
====================
本模块负责知识库的「加载」与「检索」两件事：
    1. load_kb(position_name)    —— 按岗位加载知识库条目（app/knowledge/*.json）
    2. search_kb(entries, text)  —— 按关键词命中数打分，返回最相关的 top_k 条

【知识库是什么】（RAG 通俗版）
    知识库 = 一份结构化存放的岗位考点资料（app/knowledge/ 下的 JSON 文件）。
    RAG（Retrieval-Augmented Generation，检索增强生成）= 大模型出题前，
    先来这里检索（Retrieval）相关考点，把结果拼进提示词（Augmented）再出题
    （Generation）——让题目有真实依据，而不是模型凭记忆编（可能过时、可能幻觉）。

【设计原则】
    1. 职责分离：本模块只负责"加载与检索"，怎么用检索结果由各智能体服务自己
       决定（与追问智能体"只返回决策、写入由 API 层做"同一思路）；
    2. 静默降级：知识库文件缺失、JSON 损坏、检索零命中，统统不抛异常、返回空
       列表——知识库是增强项不是必需项，面试主流程永不因它阻断；
    3. 不引入新依赖：纯 JSON 文件 + Python 标准库，无向量库、无新框架。
       条目自带关键词标签、总量几十条级，关键词检索完全够用；
       规模上千后再考虑升级 pgvector / Milvus。
"""

import json
import logging
from pathlib import Path

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
}

# 关键词包含规则（全等匹配失败后的兜底）：岗位名只要"包含"该词即命中。
# 【为什么需要】实测岗位名可能是短名——数据库/前端传「后端」而不是
# 「后端开发面试」，全等映射枚举不完各种写法，包含式匹配一劳永逸。
# 规则按顺序尝试，第一条命中的生效；注意「前端/产品/数据/行为」等
# 岗位名不含这些词，不会被误伤。
POSITION_SUBSTR_RULES = [
    ("后端", "python_backend"),
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


def search_kb(entries: list, text: str, top_k: int = 3) -> list:
    """按关键词命中数给条目打分，返回最相关的 top_k 条。

    打分规则很朴素：条目的 keywords / topic 在查询文本中每命中一个词 +1 分。
    简历技能栈越长，命中的关键词越多，得分越高——对本项目几十条的量级足够。
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
