"""
知识库向量化入库脚本（pgvector 版）
====================================
【这是什么】维护脚本：读知识库条目 JSON → 调百炼 text-embedding 模型把每条
考点变成向量 → 写入 PostgreSQL 的 kb_embeddings 表（pgvector 扩展的 VECTOR 列）。

【什么时候跑】新增/修改知识库条目后重跑一次。采用「全量重建」策略：
先清空该知识库的旧向量再全量插入——20 条的成本不到一分钱、几秒跑完，
换来"条目内容与向量永不脱节"，不需要记录哪条改过。

【怎么跑】（项目根目录下，必须 PG 模式：Docker 已启动 + .env 配好 DATABASE_URL）
    app\\venv\\Scripts\\python.exe app\\knowledge\\build_embeddings.py
    可选：--kb python_backend（指定知识库文件名，不带 .json）

【前置】需要 embedding API 额度（免费额度耗尽时接口返回 403，充值后即可）。

【为什么向量进数据库而不是 JSON】向量是机器数据（一行 1024 个小数），
存 JSON 文件又大又不可查询；pgvector 让检索变成一条 SQL（ORDER BY embedding
<=> 查询向量），这是真正的向量数据库用法。考点内容本身仍在 JSON 文件里
（可读、可人工校对、随 git）——「内容在文件、向量在库」各司其职。
"""

import argparse
import json
import sys
from pathlib import Path

# 脚本在 app/knowledge/ 下，把项目根加进 sys.path 才能导入 app.* 模块
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from openai import OpenAI

from app.config.config import DASHSCOPE_API_KEY, DASHSCOPE_BASE_URL, EMBEDDING_MODEL
from app.db.db_pool import db_pool

KB_DIR = Path(__file__).resolve().parent


def build_embedding_text(entry: dict) -> str:
    """把一条考点拼成送入 embedding 模型的文本。

    检索时可能被命中的语义都来自这几段（知识点名/核心问题/答案要点/关键词），
    全部拼进输入文本，向量的"语义覆盖面"才完整。
    """
    parts = [
        entry.get("topic", ""),
        entry.get("core_question", ""),
        "；".join(entry.get("answer_points", [])),
        "关键词：" + "、".join(entry.get("keywords", [])),
    ]
    return " ".join(p for p in parts if p)


def vector_to_pgtext(vec: list) -> str:
    """把 Python 浮点列表转成 pgvector 接受的文本表示 '[0.1,0.2,...]'。

    pgvector 支持从文本字面量强转（SQL 里 %s::vector），这样无需安装
    pgvector 的 Python 适配包——零新增 pip 依赖。
    保留 6 位小数：float 默认 repr 有十几位，没必要，还省传输。
    """
    return "[" + ",".join(f"{v:.6f}" for v in vec) + "]"


def main():
    parser = argparse.ArgumentParser(description="为知识库条目生成向量并入库 pgvector")
    parser.add_argument("--kb", default="python_backend", help="知识库文件名（不带 .json）")
    args = parser.parse_args()

    # 0. 前置检查：向量表是 PG 专属（SQLite 没有 VECTOR 类型和 <=> 操作符）
    if db_pool.backend != "postgresql":
        print("[ERROR] 当前是 SQLite 回退模式，pgvector 不可用。")
        print("        请启动 Docker Desktop，并在 .env 里取消 DATABASE_URL 注释后重试。")
        sys.exit(1)

    kb_file = KB_DIR / f"{args.kb}.json"
    with open(kb_file, "r", encoding="utf-8") as f:
        entries = json.load(f)
    print(f"[1/3] 读取 {kb_file.name}：{len(entries)} 条，调用 {EMBEDDING_MODEL} ...")

    # 1. 调 embedding API（批量：input 传列表，一次请求拿全部向量）
    texts = [build_embedding_text(e) for e in entries]
    client = OpenAI(api_key=DASHSCOPE_API_KEY, base_url=DASHSCOPE_BASE_URL)
    vectors = []
    for i in range(0, len(texts), 10):
        batch = texts[i:i + 10]
        resp = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        # 返回顺序与 input 顺序一致，逐条取出向量
        vectors.extend(item.embedding for item in resp.data)
        print(f"      批次 {i // 10 + 1}：{len(batch)} 条完成")

    # 2. 入库：建表（幂等）→ 清旧 → 全量插入（autocommit 模式，逐句生效）
    conn = db_pool.get_connection()
    try:
        cur = conn.cursor()
        # pgvector 扩展是 VECTOR 类型的前提；镜像已预编译，CREATE 只需一次（幂等）
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute('''
            CREATE TABLE IF NOT EXISTS kb_embeddings (
                id        VARCHAR(32) PRIMARY KEY,
                kb_name   VARCHAR(64) NOT NULL,
                embedding VECTOR(1024) NOT NULL
            )
        ''')
        cur.execute("CREATE INDEX IF NOT EXISTS idx_kb_embeddings_kb ON kb_embeddings(kb_name)")
        # 全量重建：清掉该知识库的全部旧向量再插入，杜绝"条目改了向量没更新"
        cur.execute("DELETE FROM kb_embeddings WHERE kb_name = %s", (args.kb,))
        for entry, vec in zip(entries, vectors):
            # ::vector 把文本字面量强转为向量类型，pgvector 认 '[a,b,c]' 格式
            cur.execute(
                "INSERT INTO kb_embeddings (id, kb_name, embedding) VALUES (%s, %s, %s::vector)",
                (entry["id"], args.kb, vector_to_pgtext(vec)),
            )
        print(f"[2/3] 已写入 kb_embeddings 表：{len(entries)} 条，维度 {len(vectors[0])}")

        # 3. 回读验证：库里能查到的条数与条目数一致才算成功
        cur.execute("SELECT COUNT(*) AS n FROM kb_embeddings WHERE kb_name = %s", (args.kb,))
        n = cur.fetchone()["n"]
        assert n == len(entries), f"入库条数不符：期望 {len(entries)}，实际 {n}"
        print(f"[3/3] 验证通过：kb_embeddings 中 {args.kb} 共 {n} 条向量")
    finally:
        # 所有退出路径都要还连接（项目约定：连接归还必须走 return_connection）
        db_pool.return_connection(conn)


if __name__ == "__main__":
    main()
