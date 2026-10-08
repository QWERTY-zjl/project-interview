"""
数据搬迁脚本：SQLite 备份库 → PostgreSQL
==========================================
【作用】把 app/db/interview_system_backup_20261008.db（迁移前的 SQLite 全量备份）
里的 13 张表数据整体搬进 PostgreSQL，是「阶段 5 数据搬迁」的一次性脚本（可重复执行）。

【运行方式】在项目根目录执行：
    python -m app.db.migrate_sqlite_to_pg

【前置条件】
    1. 根目录 .env 里 DATABASE_URL 已配置（postgresql:// 开头）——脚本只认 PG 模式
    2. PG 服务器已启动（docker compose up -d postgres）

【脚本做了什么（按执行顺序）】
    1. 校验 DATABASE_URL / 备份文件存在，否则直接报错退出
    2. 以「只读模式」打开备份库（mode=ro：物理上杜绝误写备份的可能）
    3. import 建表脚本 → 触发 PG 分支自动建表（幂等，表已存在就跳过）
    4. 全量读入源数据 → 通用孤儿清洗（PG 强制外键，断链行必须先剔除，
       剔除明细在运行时打印）
    5. 单事务写入 PG：
         TRUNCATE 全部 13 张表（清空目标，保证脚本可重复执行）
         → 逐表 INSERT（显式带原 id，防止外键断链）
         → 每表 setval 校准自增序列（防止新数据主键冲突）
    6. 打印「源 → 剔除 → 目标」行数对照表，人工核对

【为什么写入必须带 OVERRIDING SYSTEM VALUE】
    PG 建表用的是 GENERATED ALWAYS AS IDENTITY（"永远自动生成"），
    默认禁止 INSERT 时手工指定 id 列；加上 OVERRIDING SYSTEM VALUE 这个开关
    才允许"我用备份里的原 id，你数据库别管"。搬完数据后 setval 把序列拨到
    max(id)，之后正常插入就继续自动编号，两不耽误。
"""

import os
import sqlite3
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# import 路径处理：本脚本既可以用 python -m app.db.migrate_sqlite_to_pg 跑
# （此时项目根已在 sys.path 里），也可能被直接 python 路径.py 跑（此时不在）。
# parents[2] = app/db/migrate_sqlite_to_pg.py → app/db → app → 项目根，
# 把项目根插到 sys.path 最前面保证 import app.xxx 一定能找到
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv

# config.py 也是这么加载 .env 的；本脚本可能单独运行（不经过 config.py），
# 所以自己再 load 一次保证 DATABASE_URL 一定读得到
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")
# 备份文件路径锚定到本脚本所在目录（app/db/），换目录运行也不会找错
BACKUP_PATH = Path(__file__).resolve().parent / "interview_system_backup_20261008.db"

# ---------------------------------------------------------------------------
# 表依赖顺序（父表在前，子表在后）：INSERT 必须先有父行才能插子行，
# 否则 PG 外键校验直接报错。箭头读法：A → B 表示 B 的外键指向 A
# ---------------------------------------------------------------------------
TABLE_ORDER = [
    "users",                        # 无外键（根）
    "interview_types",              # 无外键（根）
    "interviews",                   # ← users, interview_types
    "interview_questions",          # ← interviews
    "interview_expression_records", # ← interviews
    "practice_progress",            # ← users, interview_types
    "feedback_data",                # ← users, interviews
    "user_quotas",                  # ← users
    "pricing_plans",                # 无外键（根）
    "orders",                       # ← users, pricing_plans
    "user_subscriptions",           # ← users, pricing_plans, orders
    "usage_logs",                   # ← users, orders
    "payment_configs",              # 无外键（根）
]

# ---------------------------------------------------------------------------
# 每张子表的外键声明：(本表列名, 父表名)。
# 孤儿清洗就是按这张映射逐列核对"值是否在父表存活 id 集合里"
# ---------------------------------------------------------------------------
TABLE_FK = {
    "interviews": [("user_id", "users"), ("interview_type_id", "interview_types")],
    "interview_questions": [("interview_id", "interviews")],
    "interview_expression_records": [("interview_id", "interviews")],
    "practice_progress": [("user_id", "users"), ("interview_type_id", "interview_types")],
    "feedback_data": [("user_id", "users"), ("interview_id", "interviews")],
    "user_quotas": [("user_id", "users")],
    "orders": [("user_id", "users"), ("plan_id", "pricing_plans")],
    "user_subscriptions": [("user_id", "users"), ("plan_id", "pricing_plans"), ("order_id", "orders")],
    "usage_logs": [("user_id", "users"), ("order_id", "orders")],
}


def clean_orphans(table, rows, cols, alive_ids):
    """
    通用孤儿清洗：把外键指向"父表不存在的行"从数据里剔除

    【为什么能自动覆盖 'test' 这种脏值】
    interview_id='test' 不是整数，必然不在父表 id 集合（整数集合）里，
    一视同仁被判为孤儿剔除——不需要为脏值单写逻辑
    """
    fk_specs = TABLE_FK.get(table)
    if not fk_specs:
        return rows, []                      # 无外键的表（users 等）不清洗

    col_index = {c: i for i, c in enumerate(cols)}
    kept, removed = [], []
    for row in rows:
        broken = None
        for col, parent in fk_specs:
            value = row[col_index[col]]
            # 跳过 NULL（外键列允许 NULL = "没有关联"，不算断链）；
            # 剩下的值只要不是父表存活 id，就是孤儿（含非整数脏值）
            if value is not None and (not isinstance(value, int) or value not in alive_ids[parent]):
                broken = (row[col_index["id"]], col, value, parent)
                break
        if broken:
            removed.append(broken)
        else:
            kept.append(row)
    return kept, removed


def main():
    # ==================== 第 0 步：前置校验 ====================
    if not DATABASE_URL.startswith("postgresql"):
        sys.exit(
            "[中止] .env 里没有配置 DATABASE_URL（或不是 postgresql:// 开头）。\n"
            "本脚本只用于 SQLite→PG 搬迁；SQLite 回退模式下无事可做。"
        )
    if not BACKUP_PATH.exists():
        sys.exit(f"[中止] 找不到备份文件：{BACKUP_PATH}")

    print(f"[1/5] 打开备份库（只读）：{BACKUP_PATH.name}")
    # sqlite3 URI 只读打开：file:路径?mode=ro。路径里的反斜杠换成正斜杠
    # （Windows 上 sqlite URI 两种都认，正斜杠更稳）；mode=ro 保证物理上写不进备份
    src = sqlite3.connect("file:" + str(BACKUP_PATH).replace("\\", "/") + "?mode=ro", uri=True)
    src.row_factory = sqlite3.Row

    print("[2/5] 检查 PG 表结构（import 建表脚本，PG 分支自动建表，幂等）...")
    # import 即执行：建表脚本顶层按 DATABASE_URL 分发，走 _init_postgresql() 建 13 张表。
    # 表已存在时 CREATE TABLE IF NOT EXISTS 直接跳过，所以重复搬迁也安全
    import app.db.create_personal_interview_system_db  # noqa: F401

    print("[3/5] 读取源数据并清洗孤儿行...")
    # data = {表名: (行列表, 列名列表)}：先把 13 张表全部读进内存再统一清洗。
    # 好处：清洗要跨表传递"存活 id 集合"，先全读进来逻辑最简单
    # （备份 112MB，全量进内存约几百 MB，开发机无压力）
    data = {}
    for table in TABLE_ORDER:
        cursor = src.execute(f"SELECT * FROM {table}")
        cols = [d[0] for d in cursor.description]
        rows = [tuple(r) for r in cursor.fetchall()]   # sqlite3.Row → 普通 tuple
        data[table] = [rows, cols]
    src.close()   # 备份库读完了，立刻关掉（只读连接也要释放句柄）

    # ---------- 按依赖序逐表清洗：父表先洗，存活 id 集合传给子表 ----------
    alive_ids = {}                     # {表名: 清洗后存活的 id 集合}
    removed_counts = {}                # {表名: 剔除行数}，供最后的对照表打印
    all_removed = []                   # (表, 行id, 外键列, 值, 父表) 汇总明细
    for table in TABLE_ORDER:
        rows, cols = data[table]
        kept, removed = clean_orphans(table, rows, cols, alive_ids)
        id_index = cols.index("id")
        alive_ids[table] = {r[id_index] for r in kept}
        data[table][0] = kept
        removed_counts[table] = len(removed)
        for row_id, col, value, parent in removed:
            all_removed.append((table, row_id, col, value, parent))

    if all_removed:
        print(f"\n  孤儿数据清洗：共剔除 {len(all_removed)} 行（PG 强制外键，这些行插不进去）")
        for table, row_id, col, value, parent in all_removed:
            print(f"    [剔除] {table}.id={row_id}  {col}={value!r} 在 {parent} 里不存在")
        print()
    else:
        print("  孤儿数据清洗：无孤儿，全部数据外键完整")

    # ==================== 第 4 步：单事务写入 PG ====================
    print("[4/5] 连接 PG 开始搬迁（TRUNCATE → INSERT → setval，单事务）...")
    # 延迟 import psycopg：只有真的要搬数据才需要驱动
    import psycopg
    from psycopg import sql

    conn = psycopg.connect(DATABASE_URL, connect_timeout=5)
    cur = conn.cursor()

    # ---- 4a. 清空目标表（可重复执行的关键）----
    # TRUNCATE 比 DELETE 快得多（不逐行记日志），一次清 13 张；
    # RESTART IDENTITY：顺带把自增序列也归位；CASCADE：允许清有外键引用的表
    cur.execute(
        sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(
            sql.SQL(", ").join(sql.Identifier(t) for t in TABLE_ORDER)
        )
    )

    # ---- 4b. 逐表插入（显式带原 id）----
    # OVERRIDING SYSTEM VALUE：允许手工给 GENERATED ALWAYS AS IDENTITY 列赋值
    # （见文件头说明）。占位符 %s 的个数 = 列数，值由 executemany 逐行传入
    for table in TABLE_ORDER:
        rows, cols = data[table]
        if not rows:
            print(f"  {table}: 源 0 行，跳过")
            continue
        insert_sql = sql.SQL("INSERT INTO {t} ({cols}) OVERRIDING SYSTEM VALUE VALUES ({phs})").format(
            t=sql.Identifier(table),
            cols=sql.SQL(", ").join(sql.Identifier(c) for c in cols),
            # sql.Placeholder() 生成一个 %s；乘列数再逗号拼接 = (%s, %s, ...)
            phs=sql.SQL(", ").join(sql.Placeholder() * len(cols)),
        )
        cur.executemany(insert_sql, rows)
        print(f"  {table}: 灌入 {len(rows)} 行")

    # ---- 4c. 每表 setval 校准自增序列 ----
    # 显式插入了原 id，但 PG 的自增序列并不知道——它还停在 1。
    # 不校准的话，下一个新用户 INSERT 会生成 id=1 → 主键冲突。
    # pg_get_serial_sequence('表','id')：查出该表 id 列绑定的序列名；
    # setval(序列, max_id)：把序列"当前值"拨到最大已用 id
    print("  校准自增序列...")
    for table in TABLE_ORDER:
        # 注意必须用 sql.SQL().format() 组合 SQL（psycopg 的专用拼接器会把
        # Identifier 转成带引号的安全标识符）；Python 原生 str.format 不认识
        # Identifier 对象，会把它的 repr 字符串原样塞进 SQL 导致语法错误
        cur.execute(
            sql.SQL("SELECT COALESCE(MAX(id), 0) FROM {}").format(sql.Identifier(table))
        )
        max_id = cur.fetchone()[0]
        if max_id > 0:
            cur.execute("SELECT setval(pg_get_serial_sequence(%s, %s), %s)", (table, "id", max_id))
        else:
            # 空表特例：setval(序列, 1, false) 的 false 表示"1 还没用过"，
            # 下一次 nextval 正好从 1 开始（默认 true 会从 2 开始）
            cur.execute("SELECT setval(pg_get_serial_sequence(%s, %s), 1, false)", (table, "id"))

    conn.commit()   # 全部成功才一次性落库；任何一步报错走 except 回滚
    conn.close()

    # ==================== 第 5 步：行数对照 ====================
    print("[5/5] 行数对照（源-剔除 vs PG 实际）...")
    conn = psycopg.connect(DATABASE_URL, connect_timeout=5)
    cur = conn.cursor()
    print(f"  {'表名':<30}{'源行数':>8}{'剔除':>6}{'PG实际':>8}  校验")
    ok_all = True
    for table in TABLE_ORDER:
        rows, _ = data[table]
        cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table)))
        pg_count = cur.fetchone()[0]
        match = "OK" if pg_count == len(rows) else "不一致!"
        if pg_count != len(rows):
            ok_all = False
        print(f"  {table:<30}{len(rows):>8}{removed_counts[table]:>6}{pg_count:>8}  {match}")
    conn.close()

    print()
    if ok_all:
        print("搬迁完成：全部 13 张表行数一致，序列已校准。可以启动服务器做冒烟验证。")
    else:
        sys.exit("搬迁异常：存在行数不一致的表，请检查上方输出")


if __name__ == "__main__":
    main()
