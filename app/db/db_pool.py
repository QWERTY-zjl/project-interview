"""
数据库连接池模块
================
本模块负责管理数据库连接池，提高数据库操作性能
"""

import sqlite3
from sqlite3 import Connection
from typing import List, Optional
from app.config.config import DATABASE_NAME


class DatabasePool:
    """
    数据库连接池类
    """
    
    def __init__(self, db_name: str, pool_size: int = 5):
        """
        初始化数据库连接池
        
        参数:
            db_name: 数据库文件名
            pool_size: 连接池大小
        """
        self.db_name = db_name
        self.pool_size = pool_size
        self.pool: List[Connection] = []
        self._initialize_pool()
    
    def _initialize_pool(self):
        """
        初始化连接池
        """
        for _ in range(self.pool_size):
            conn = sqlite3.connect(self.db_name)
            conn.row_factory = sqlite3.Row
            self.pool.append(conn)
    
    def get_connection(self) -> Optional[Connection]:
        """
        从连接池获取连接
        
        返回:
            数据库连接对象，如果连接池为空则返回None
        """
        if self.pool:
            return self.pool.pop()
        return None
    
    def return_connection(self, conn: Connection):
        """
        将连接返回连接池
        
        参数:
            conn: 数据库连接对象
        """
        if conn and conn not in self.pool:
            self.pool.append(conn)
    
    def close_all(self):
        """
        关闭所有连接
        """
        for conn in self.pool:
            try:
                conn.close()
            except Exception as e:
                print(f"[ERROR] 关闭数据库连接失败: {e}")
        self.pool.clear()


# 创建数据库连接池实例
db_pool = DatabasePool(DATABASE_NAME, pool_size=10)
