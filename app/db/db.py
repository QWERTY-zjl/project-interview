"""数据库模块

作用：整个项目所有需要读写 SQLite 数据库的代码，都通过这里拿连接/还连接。
相当于数据库的「统一入口」，其他模块不直接 import sqlite3。
"""

import os
import sqlite3          # Python 自带的 SQLite 驱动，标准库，不用安装
import logging
from app.config.config import DATABASE_NAME  # 从配置文件读取数据库文件路径

# logging.getLogger(__name__)：拿到本模块专属的日志记录器，
# 打日志时会自动带上模块名（如 app.db.db），方便排查是哪个文件输出的
logger = logging.getLogger(__name__)

# 全局连接池，用于管理所有活跃的数据库连接
# 本质就是一个普通 Python 列表，记录当前「借出去还没还」的连接对象。
# 作用：程序退出时能统一关闭所有连接，避免数据库文件被占用。
# 注意：SQLite 本身不支持真正的多线程连接池，这里只是简易登记。
_connections = []

def get_db():
    """获取数据库连接

    谁要用数据库，谁就调这个函数「借」一个连接。
    用完后必须调 return_db(conn) 还回去。

    Returns:
        sqlite3.Connection: 配置了行工厂的数据库连接对象
    """
    # 连接数据库文件（DATABASE_NAME 是配置里的路径，如 app/db/interview_system.db）。
    # 如果文件不存在，SQLite 会自动创建一个空的 .db 文件
    conn = sqlite3.connect(DATABASE_NAME)
    # row_factory = sqlite3.Row：设置「行工厂」。
    # 默认查出来的每行是元组 (值1, 值2)，只能按下标取 row[0]；
    # 换成 Row 后可以像字典一样用列名取：row["user_id"]、row.keys()。
    # 这是本项目所有查询都能写 row["列名"] 的原因
    conn.row_factory = sqlite3.Row  # 支持列名访问
    # 登记到全局列表，表示这个连接已借出、尚未关闭
    _connections.append(conn)
    return conn

def return_db(conn):
    """关闭数据库连接并从连接池移除

    「还连接」：用完必须关掉，否则连接一直占着数据库文件（Windows 上
    表现为 .db 文件被锁定，其他工具打开会报 database is locked）。

    Args:
        conn: 数据库连接对象
    """
    # 两个判断：conn 不是 None，且确实是之前借出去的（在列表里登记过），
    # 防止重复关闭或关掉别人的连接
    if conn and conn in _connections:
        conn.close()            # 真正关闭与数据库文件的连接
        _connections.remove(conn)  # 从登记列表中移除

def init_db():
    """初始化数据库（创建表结构）

    程序启动时调用一次。不管数据库文件存不存在，都交给
    create_personal_interview_system_db.py 处理（该脚本内部会
    判断文件是否存在，然后建库建表或补齐缺失的字段/表）。
    两个分支 import 同一个模块，是因为建表脚本里两种情况都覆盖了。
    """
    if not os.path.exists(DATABASE_NAME):
        # 数据库不存在，创建新数据库
        import app.create_personal_interview_system_db
    else:
        # 数据库已存在，更新表结构（比如以前没这个字段的表补上字段）
        import app.create_personal_interview_system_db

def close_all_connections():
    """关闭所有数据库连接（程序退出时调用）"""
    # _connections[:] 是浅拷贝：先复制一份再遍历删除。
    # 如果直接遍历 _connections 边遍历边 remove，列表长度变化会导致
    # 漏删或跳过元素，这是 Python 列表遍历删除的经典坑。
    for conn in _connections[:]:  # 使用副本避免迭代时修改
        try:
            conn.close()
            _connections.remove(conn)
        except Exception as e:
            # 单个连接关闭失败只记日志，不影响其他连接继续关闭
            logger.error(f"[DB] 关闭连接失败: {e}")
