"""
数据库连接池模块（双轨版：PostgreSQL / SQLite）
================================================
【2026-10 从 SQLite 迁移到 PostgreSQL】本项目连接层改为双轨设计：
- config.DATABASE_URL 有值 → 走 PostgreSQL，用 psycopg_pool.ThreadedConnectionPool
  （真正的池：预先建好 N 个连接，借出/归还循环复用，跨线程共享）
- DATABASE_URL 为空       → 回退 SQLite，行为与旧版 db.py 完全一致
  （每次操作新建连接、用完关闭——SQLite 是单文件库，建连开销可忽略）

对上层暴露的接口只有两个，业务代码不感知后端差异：
    get_connection()      借一个连接
    return_connection()   还回连接

为什么 PG 需要真正的池而 SQLite 不需要：
- PG 是独立服务端进程，建连要走 TCP 握手 + 鉴权（几十毫秒级），必须复用
- psycopg 的连接默认可跨线程使用吗？不行——psycopg3 的 Connection 也不是
  线程安全的，但 psycopg_pool 的 ThreadedConnectionPool 内部自带锁，
  借/还操作是线程安全的，每个连接同一时刻只借给一个线程，所以安全
"""

import threading

from app.config.config import DATABASE_URL, DATABASE_NAME

# ---------- 按需 import 驱动 ----------
# DATABASE_URL 为空（SQLite 回退）时不需要装 psycopg 也能跑，
# 所以 psycopg 相关 import 放在 PG 分支里，而不是文件顶部
if DATABASE_URL:
    import psycopg                        # psycopg3 主包（对比旧驱动 psycopg2）
    from psycopg.rows import dict_row     # 行工厂：让查询结果按「字典」返回
    # ConnectionPool：psycopg 官方同步连接池。名字里没带 Threaded，但它内部
    # 就是用线程 + 锁实现的（异步场景才用另一个 AsyncConnectionPool），
    # getconn/putconn 都是线程安全的，多线程并发借还没问题
    from psycopg_pool import ConnectionPool


class DatabasePool:
    """
    双轨数据库连接池

    backend="postgresql"：psycopg_pool 池（借出/归还，连接长期复用）
    backend="sqlite"    ：每次新建连接（与旧 db.py 行为一致，保证回退零风险）
    """

    def __init__(self, db_name: str, db_url: str = ""):
        """
        参数:
            db_name: SQLite 数据库文件路径（回退分支用）
            db_url:  PostgreSQL 连接串 postgresql://用户:密码@主机:端口/库（PG 分支用）
        """
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
            # ConnectionPool 参数逐个解释：
            #   min_size=1, max_size=10 → 池里常驻至少 1 个、最多 10 个连接，
            #     超过 10 个并发借出时，后来的调用会阻塞等待别人归还（池的自限流）
            #   conninfo=db_url → 连接串，psycopg 直接解析 postgresql:// 格式
            #   kwargs={...} → 传给每个连接的 psycopg.connect() 的额外参数：
            #     row_factory=dict_row → 查询结果每行是 dict，
            #       取值写 row["列名"]，和旧 sqlite3.Row 用法兼容
            #     autocommit=True → 每条 SQL 执行完立即自动提交。
            #       【为什么必须开】SQLite 旧代码是"每句自动提交"语义，
            #       而 psycopg 默认事务模式需要显式 conn.commit()。
            #       开 autocommit 后行为与 SQLite 完全一致，上层一行不用改；
            #       需要多语句原子性的事务块（with conn.transaction()）以后单独加
            self._pg_pool = ConnectionPool(
                min_size=1,
                max_size=10,
                conninfo=self.db_url,
                timeout=10,            # getconn 最长等待秒数：PG 不可用时 10 秒报错，
                                       # 而不是用默认 30 秒干等（启动失败更快暴露）
                kwargs={"row_factory": dict_row, "autocommit": True},
                open=False,            # 先不建连，下面手动 open（官方推荐写法，
                                       # 避免 import 本模块时就卡在网络请求上）
            )
            # open(wait=False)：立即返回，不阻塞等 PG 就绪。
            # 真正建连发生在首次 getconn() 时，PG 没启动会在那时报
            # OperationalError: connection refused（信息直接明了）
            self._pg_pool.open(wait=False)

    # ------------------------------------------------------------------
    # 借连接
    # ------------------------------------------------------------------
    def get_connection(self):
        """
        借一个数据库连接

        返回:
            postgresql 分支 → psycopg.Connection（dict 行工厂 + 自动提交）
            sqlite 分支     → sqlite3.Connection（Row 行工厂，即借即新）
        """
        if self.backend == "postgresql":
            # getconn()：从池里取一个空闲连接；池空且已满 10 个时阻塞等待
            # （内部有锁保护，多线程并发调用安全）
            return self._pg_pool.getconn()

        # ---------- SQLite 回退分支：与旧 db.py 语义完全一致 ----------
        # 每次操作新建一个连接。SQLite 是本地单文件，建连≈打开文件，开销可忽略，
        # 保持旧行为可以让回退路径 100% 与迁移前相同（稳定性优先）
        import sqlite3
        conn = sqlite3.connect(self.db_name)
        # Row 行工厂：查询结果支持 row["列名"] 取值（与 PG 分支的 dict_row 对齐）
        conn.row_factory = sqlite3.Row
        with self._lock:                   # 登记时要加锁（多线程可能同时登记）
            self._all_connections.append(conn)
        return conn

    # ------------------------------------------------------------------
    # 还连接
    # ------------------------------------------------------------------
    def return_connection(self, conn):
        """
        归还连接

        postgresql 分支：连接回池子等待下次借出（不关闭，复用的核心）
        sqlite 分支    ：真正关闭（SQLite 模式下"还"就等于"关"，
                         否则 .db 文件一直被占用，Windows 上其他工具打不开）
        """
        if self.backend == "postgresql":
            if conn is not None:
                # putconn()：把连接放回池里。若连接还挂在未结束的事务上，
                # 池会自动 rollback 再复用（防止脏状态传给下一个借用人）
                self._pg_pool.putconn(conn)
            return

        # ---------- SQLite 回退分支 ----------
        # 两个判断：conn 不是 None，且确实是之前借出去的（登记过），
        # 防止重复关闭或关掉别人的连接
        if conn and conn in self._all_connections:
            conn.close()                   # 真正关闭与数据库文件的连接
            self._all_connections.remove(conn)

    # ------------------------------------------------------------------
    # 程序退出时统一关闭
    # ------------------------------------------------------------------
    def close_all(self):
        """关闭池内所有连接（程序退出时调用）"""
        if self.backend == "postgresql":
            # psycopg_pool 自带 close：关掉池里所有连接并停止借出服务
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
