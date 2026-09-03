"""数据库模块"""

import os
import sqlite3
import logging
from app.config.config import DATABASE_NAME

logger = logging.getLogger(__name__)

# 全局连接池，用于管理所有活跃的数据库连接
_connections = []

def get_db():
    """
    获取数据库连接
    
    Returns:
        sqlite3.Connection: 配置了行工厂的数据库连接对象
    """
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row  # 支持列名访问
    _connections.append(conn)
    return conn

def return_db(conn):
    """
    关闭数据库连接并从连接池移除
    
    Args:
        conn: 数据库连接对象
    """
    if conn and conn in _connections:
        conn.close()
        _connections.remove(conn)

def init_db():
    """初始化数据库（创建表结构）"""
    if not os.path.exists(DATABASE_NAME):
        # 数据库不存在，创建新数据库
        import app.create_personal_interview_system_db
    else:
        # 数据库已存在，更新表结构
        import app.create_personal_interview_system_db

def close_all_connections():
    """关闭所有数据库连接（程序退出时调用）"""
    for conn in _connections[:]:  # 使用副本避免迭代时修改
        try:
            conn.close()
            _connections.remove(conn)
        except Exception as e:
            logger.error(f"[DB] 关闭连接失败: {e}")
