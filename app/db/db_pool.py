"""
数据库连接池模块
================
线程安全的数据库连接池（按线程隔离）

和 db.py 的区别：
- db.py 每次操作都新建连接、用完关闭（建连开销小，适合 SQLite）
- 这里每个线程第一次使用时建一个连接，之后该线程一直复用自己的这个

线程安全说明（为什么不能预建 N 个连接来回分发）：
- sqlite3 默认 check_same_thread=True：连接只能被创建它的线程使用
- 预先在主线程建好 pool_size 个连接再借给其他线程，会直接抛
  ProgrammingError: SQLite objects created in a thread can only be
  used in that same thread
- 因此采用「线程本地」策略：按需创建 + 线程内复用，跨线程互不共享
"""

import threading
import sqlite3
from sqlite3 import Connection          # 连接对象的类型，只用于类型注解
from app.config.config import DATABASE_NAME


class DatabasePool:
    """
    线程安全的数据库连接池（每线程一个连接）
    """

    def __init__(self, db_name: str):
        """
        参数:
            db_name: 数据库文件名
        """
        self.db_name = db_name
        # threading.local()：每个线程看到的是各自独立的存储空间，
        # 线程 A 写入的 self._local.conn，线程 B 读不到——隔离的关键
        self._local = threading.local()
        # 登记所有线程创建过的连接，供程序退出时统一关闭
        self._all_connections: list[Connection] = []
        self._lock = threading.Lock()      # 保护登记列表的并发修改

    def get_connection(self) -> Connection:
        """
        获取当前线程专属的连接，第一次调用时现场创建

        返回:
            数据库连接对象（永远成功，不会再返回 None）
        """
        conn = getattr(self._local, "conn", None)
        if conn is None:                    # 本线程还没建过连接
            conn = sqlite3.connect(self.db_name)
            conn.row_factory = sqlite3.Row  # 同 db.py：让查询结果支持按列名取值
            self._local.conn = conn         # 存进线程本地，下次同线程直接复用
            with self._lock:                # 登记时要加锁（多线程可能同时登记）
                self._all_connections.append(conn)
        return conn
    
    def return_connection(self, conn: Connection):
        """
        将连接返回连接池

        线程本地模式下连接常驻复用，无需真正归还。
        保留此方法是为了兼容旧的调用习惯（借了还，不报错）。
        """
        pass
    
    def close_all(self):
        """
        关闭所有线程创建的连接

        程序退出时调用。注意：sqlite3 不允许跨线程 close，
        所以这里只能关掉登记列表里能关的连接，
        其他线程创建的连接会报 ProgrammingError 并被捕获记录，
        程序退出时进程结束，连接随进程释放，不影响数据安全。
        """
        with self._lock:
            for conn in self._all_connections:
                try:
                    conn.close()
                except Exception as e:
                    print(f"[ERROR] 关闭数据库连接失败: {e}")
            self._all_connections.clear()


# 创建数据库连接池实例
# 模块级别直接实例化（全局单例用法）；不再预建连接，各线程首次使用时才建
db_pool = DatabasePool(DATABASE_NAME)
