"""
数据库连接池模块（双轨版：PostgreSQL / SQLite）
================================================
双轨设计，由 config.DATABASE_URL 决定后端：
- 有值 → 走 PostgreSQL，用 psycopg_pool.ConnectionPool
  （预先建好 N 个连接，借出/归还循环复用；内部用线程+锁实现，
  getconn/putconn 线程安全，每个连接同一时刻只借给一个线程）
- 为空 → 回退 SQLite：每次操作新建连接、用完关闭
  （SQLite 是单文件库，建连开销可忽略）

对上层暴露的接口只有两个，业务代码不感知后端差异：
    get_connection()      借一个连接
    return_connection()   还回连接

为什么 PG 需要真正的池而 SQLite 不需要：PG 是独立服务端进程，建连要走
TCP 握手 + 鉴权（几十毫秒级），必须复用；SQLite 本地文件无此开销。
"""

import threading

from app.config.config import DATABASE_URL, DATABASE_NAME

# ---------- 按需 import 驱动 ----------
# DATABASE_URL 为空（SQLite 回退）的环境可能没装 psycopg，
# 所以 psycopg 相关 import 放在 PG 分支里，而不是文件顶部
if DATABASE_URL:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool


class _SQLiteCompatCursor:
    """
    SQLite 游标的方言适配：把业务代码里的 PG 风格 %s 占位符转成 SQLite 的 ?

    业务 SQL 全库按 PG 方言书写（%s / RETURNING），为避免每处 SQL 写两份，
    在游标层做一次机械翻译。两个前提保证替换安全：
    1. 全项目 SQL 文本无 LIKE 模式字面量，不存在 '%s' 被误替换的场景
    2. Python 3.13 内置 SQLite >= 3.45，原生支持 RETURNING 子句，无需改写
    """

    def __init__(self, cursor):
        self._cur = cursor

    def execute(self, sql, params=()):
        return self._cur.execute(sql.replace("%s", "?"), params)

    def executemany(self, sql, seq_of_params):
        return self._cur.executemany(sql.replace("%s", "?"), seq_of_params)

    def __getattr__(self, name):
        # fetchone/fetchall/lastrowid 等其余属性直接委托给原生游标
        return getattr(self._cur, name)


class _SQLiteCompatConnection:
    """
    SQLite 连接包装：cursor() / execute() / executemany() 都过方言适配

    execute 必须也做翻译：sqlite3.Connection 自带便捷方法 execute()
    （等价于 cursor() + execute()），项目里大量代码直接 conn.execute(...)
    书写 SQL，若只适配 cursor() 这部分 %s 会原样透传给 SQLite 报语法错误
    """

    def __init__(self, conn):
        self._conn = conn

    def cursor(self):
        return _SQLiteCompatCursor(self._conn.cursor())

    def execute(self, sql, params=()):
        return _SQLiteCompatCursor(self._conn.execute(sql.replace("%s", "?"), params))

    def executemany(self, sql, seq_of_params):
        return _SQLiteCompatCursor(self._conn.executemany(sql.replace("%s", "?"), seq_of_params))

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)


class DatabasePool:
    """
    双轨数据库连接池

    backend="postgresql"：psycopg_pool 池（借出/归还，连接长期复用）
    backend="sqlite"    ：每次新建连接（简单稳定）
    """

    def __init__(self, db_name: str, db_url: str = ""):
        # db_name = SQLite 数据库文件路径（回退分支用）
        # db_url  = PostgreSQL 连接串 postgresql://用户:密码@主机:端口/库（PG 分支用）
        self.db_name = db_name
        self.db_url = db_url
        # 后端判定：URL 有值即 PG，否则 SQLite（回退开关的核心判断就这一行）
        self.backend = "postgresql" if db_url else "sqlite"

        # ---------- SQLite 回退分支要用的登记结构 ----------
        # 登记所有借出去的连接，供程序退出时统一关闭（避免 Windows 上文件被占用）
        self._all_connections: list = []
        self._lock = threading.Lock()      # 保护登记列表的并发修改

        # ---------- PG 分支：创建真正的连接池 ----------
        if self.backend == "postgresql":
            # min_size=1, max_size=10：池满 10 个时 getconn 阻塞等待归还（池的自限流）
            # 【autocommit 必须开】SQLite 旧代码是"每句自动提交"语义，
            # psycopg 默认事务模式需显式 conn.commit()；开 autocommit 后行为与
            # SQLite 完全一致，上层一行不用改。多语句原子性的事务块
            # （with conn.transaction()）以后单独加
            self._pg_pool = ConnectionPool(
                min_size=1,
                max_size=10,
                conninfo=self.db_url,
                timeout=10,            # PG 不可用时 10 秒报错（默认 30 秒），启动失败更快暴露
                kwargs={"row_factory": dict_row, "autocommit": True},
                open=False,            # 先不建连，下面手动 open，避免 import 本模块时就卡在网络请求上
            )
            # open(wait=False)：立即返回不阻塞等 PG 就绪，真正建连发生在首次 getconn()；
            # PG 没启动时在那时报 OperationalError: connection refused（信息直接明了）
            self._pg_pool.open(wait=False)

    def get_connection(self):
        """
        借一个数据库连接

        postgresql 分支 → psycopg.Connection（dict 行工厂 + 自动提交）
        sqlite 分支     → sqlite3.Connection（Row 行工厂，即借即新）
        """
        if self.backend == "postgresql":
            return self._pg_pool.getconn()

        # ---------- SQLite 回退分支 ----------
        # 每次操作新建连接：SQLite 是本地单文件，建连开销可忽略
        import sqlite3
        conn = sqlite3.connect(self.db_name)
        # Row 行工厂：支持 row["列名"] 取值（与 PG 分支的 dict_row 对齐）
        conn.row_factory = sqlite3.Row
        with self._lock:                   # 登记时要加锁（多线程可能同时登记）
            self._all_connections.append(conn)
        # 方言适配包装：业务 SQL 的 %s 占位符在此统一翻译为 SQLite 的 ?
        return _SQLiteCompatConnection(conn)

    def return_connection(self, conn):
        """
        归还连接

        postgresql 分支：连接回池复用（不关闭，复用的核心）
        sqlite 分支    ：真正关闭（"还"即"关"，否则 .db 文件一直被占用，
                         Windows 上其他工具打不开）
        """
        if self.backend == "postgresql":
            if conn is not None:
                # 若连接还挂在未结束的事务上，池会自动 rollback 再复用
                # （防止脏状态传给下一个借用人）
                self._pg_pool.putconn(conn)
            return

        # ---------- SQLite 回退分支 ----------
        # conn 非 None 且确实是之前借出去的（登记过），防止重复关闭或关掉别人的连接
        if conn and conn in self._all_connections:
            conn.close()
            self._all_connections.remove(conn)

    def close_all(self):
        """关闭池内所有连接（程序退出时调用）"""
        if self.backend == "postgresql":
            self._pg_pool.close()
            return

        # ---------- SQLite 回退分支 ----------
        with self._lock:
            for conn in self._all_connections:
                try:
                    conn.close()
                except Exception as e:
                    print(f"[ERROR] 关闭数据库连接失败: {e}")
            self._all_connections.clear()


# 创建数据库连接池实例（模块级单例：全项目共用这一个池）
db_pool = DatabasePool(DATABASE_NAME, DATABASE_URL)
