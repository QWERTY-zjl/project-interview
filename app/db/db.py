"""数据库模块

作用：整个项目所有需要读写数据库的代码，都通过这里拿连接/还连接，
其他模块不直接 import sqlite3 / psycopg。

薄委托层：get_db() / return_db() / close_all_connections() 全部转发给
app/db/db_pool.py 的双轨连接池，走 PostgreSQL 还是 SQLite 由
config.DATABASE_URL 是否有值决定（回退开关），业务代码无感知。
"""

import logging
from app.db.db_pool import db_pool   # 双轨连接池（PG 用 psycopg_pool，SQLite 回退旧逻辑）

logger = logging.getLogger(__name__)

def get_db():
    """获取数据库连接：用完必须调 return_db(conn) 归还。

    返回的连接已配置好行工厂：
    - PG 分支：dict 行，row["列名"] 取值，每句 SQL 自动提交（autocommit）
    - SQLite 分支：sqlite3.Row 行，row["列名"] 取值
    """
    return db_pool.get_connection()

def return_db(conn):
    """归还数据库连接

    - PG 分支：连接回池复用（池会自动回滚挂在连接上的未提交事务）
    - SQLite 分支：真正关闭（避免 .db 文件被占用）
    """
    db_pool.return_connection(conn)

def init_db():
    """初始化数据库（创建表结构），程序启动时由 main.py 调用一次。

    建表脚本是幂等的（IF NOT EXISTS / 探测式补列），重复执行安全，
    新库和已有库都覆盖；内部按 DATABASE_URL 分发：
    有值走 PG 方言建表，为空走 SQLite 建表。
    """
    import app.db.create_personal_interview_system_db

def close_all_connections():
    """关闭所有数据库连接（程序退出时调用）"""
    db_pool.close_all()
