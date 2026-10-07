"""数据库模块

作用：整个项目所有需要读写数据库的代码，都通过这里拿连接/还连接。
相当于数据库的「统一入口」，其他模块不直接 import sqlite3 / psycopg。

【2026-10 从 SQLite 迁移到 PostgreSQL】本文件改为薄委托层：
    get_db() / return_db() / close_all_connections() 全部转发给
    app/db/db_pool.py 的双轨连接池，具体走 PostgreSQL 还是 SQLite
    由 config.DATABASE_URL 是否有值决定（回退开关）。
    函数签名不变，业务代码（api 层、service 层）无感知，一行不用改。
"""

import logging
from app.db.db_pool import db_pool   # 双轨连接池（PG 用 psycopg_pool，SQLite 回退旧逻辑）

# logging.getLogger(__name__)：拿到本模块专属的日志记录器，
# 打日志时会自动带上模块名（如 app.db.db），方便排查是哪个文件输出的
logger = logging.getLogger(__name__)

def get_db():
    """获取数据库连接

    谁要用数据库，谁就调这个函数「借」一个连接。
    用完后必须调 return_db(conn) 还回去。

    返回的连接已配置好行工厂：
    - PG 分支：dict 行，row["列名"] 取值，每句 SQL 自动提交（autocommit）
    - SQLite 分支：sqlite3.Row 行，row["列名"] 取值（旧行为不变）

    Returns:
        数据库连接对象（psycopg.Connection 或 sqlite3.Connection）
    """
    return db_pool.get_connection()

def return_db(conn):
    """归还数据库连接

    - PG 分支：连接回池复用（池会自动回滚挂在连接上的未提交事务）
    - SQLite 分支：真正关闭（避免 .db 文件被占用）

    Args:
        conn: 之前从 get_db() 借到的连接对象
    """
    db_pool.return_connection(conn)

def init_db():
    """初始化数据库（创建表结构）

    程序启动时由 main.py 调用一次。
    【原理】import 一个模块时，Python 会把模块顶层的代码从头到尾执行一遍——
    建表脚本正是利用这一点：import 它 = 执行建库建表 + 探测式补字段 + 插默认数据。
    脚本内部用 IF NOT EXISTS / try-except 迁移保证重复执行也安全（幂等），
    新建库和老库两种情况都覆盖，所以这里不需要先判断文件存不存在。
    脚本内部按 DATABASE_URL 分发：有值走 PG 方言建表，为空走原 SQLite 建表。

    【import 路径】import 后面写「点分路径」= 文件在项目里的目录位置：
    app/db/create_personal_interview_system_db.py → app.db.create_personal_interview_system_db
    （文件从 app/ 搬到 app/db/ 后，老路径会 ModuleNotFoundError，
    导致服务器启动直接退出——2026-09-29 修正）
    """
    import app.db.create_personal_interview_system_db

def close_all_connections():
    """关闭所有数据库连接（程序退出时调用）"""
    db_pool.close_all()
