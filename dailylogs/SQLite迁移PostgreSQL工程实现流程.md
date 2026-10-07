# SQLite → PostgreSQL 迁移工程实现流程

> 制定时间：2026-10-08
> 目标：把智面无忧的存储层从 SQLite（app/db/interview_system.db）整体切换到 PostgreSQL 16
> 原则：单一权威建表脚本 + 启动自动初始化 + 保留 SQLite 回退开关 + 最小改动面

## 一、现状与影响面

### 现状要点

- 建表：`app/db/create_personal_interview_system_db.py`（单一权威脚本，含启动时自动补列的迁移段，13 张表）
- 连接层：`app/db/db_pool.py`（threading.local 每线程一连接）+ `app/db/db.py`（每操作一连接，旧模式）
- 配置：`DATABASE_NAME` 在 `app/config/config.py`
- 业务层全部手写 SQL（无 ORM）

### 影响面清单（grep "sqlite3|\.db" 实测 16 个文件）

| 分类 | 文件 | 改动 |
|---|---|---|
| **核心改造** | app/db/db_pool.py | 连接池换 psycopg 实现，对上保持 `get_connection()` 接口不变 |
| **核心改造** | app/db/create_personal_interview_system_db.py | 新增 PG 方言建表 + 按 DATABASE_URL 分发 |
| **核心改造** | app/config/config.py | 新增 DATABASE_URL（.env 可覆盖） |
| 连带检查 | app/api/interview_api.py、resume_api.py、report_api.py、auth_api.py、deps.py、expression_api.py | 占位符 ?→%s、lastrowid→RETURNING、行取值方式复查 |
| 连带检查 | app/ai_services/report_service.py、question_service.py | 同上 |
| 连带检查 | app/payment_module.py、main.py | 同上 + init_db 调用方式 |
| **不动** | app/server.py（Flask 旧入口，仅参考）、swagger-ui 静态资源 | 不迁移 |

## 二、SQL 方言差异对照（全局 grep 逐项清理）

| SQLite 写法 | PostgreSQL 等价 | 出现位置 |
|---|---|---|
| `?` 占位符 | `%s` | 全部 execute/ executemany |
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY` | 建表脚本 13 处 |
| `cursor.lastrowid` | `INSERT ... RETURNING id` 后 `fetchone()` | 各插入接口 |
| `INSERT OR REPLACE / OR IGNORE` | `ON CONFLICT (列) DO UPDATE / DO NOTHING` | 全局搜 `INSERT OR` |
| `PRAGMA foreign_keys=ON` | PG 外键默认生效，删掉 PRAGMA | db.py / db_pool.py |
| `datetime('now')`、`strftime(...)` | `now()`、`to_char(...)` | 全局搜 `datetime(`、`strftime` |
| `PRAGMA table_info` 补列迁移段 | 查 `information_schema.columns` 判断列是否存在 | 建表脚本迁移段 |
| `sqlite_master` | `information_schema.tables` | 建表脚本判断逻辑 |

**时间字段策略**：起步阶段 SQLite 里时间列若是 TEXT 存储，PG 版**保持 TEXT**（行为零差异、零风险）；改成 `TIMESTAMPTZ` 列为迁移后的独立优化项，不混进本次。

## 三、分阶段实施流程

### 阶段 0：基线冻结（0.5h）

1. git 当前状态干净（未提交项先提交）
2. 切分支 `feature/pg-migration`，所有迁移在此分支进行
3. 复制 `app/db/interview_system.db` 为 `interview_system_backup_20261008.db`（搬迁数据源）
4. 记录基线：现服务全链路冒烟一次（登录→上传→出题→答题→报告→表情→配额），截图/记要点

### 阶段 1：基础设施（1h）

1. `uv pip install "psycopg[binary,pool]" --python app\venv\Scripts\python.exe`（psycopg3，驱动+池）
2. `docker/docker-compose.yml` 增加：

```yaml
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: interview_system
      POSTGRES_USER: zsmian
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    ports:
      - "5432:5432"
    volumes:
      - pg_data:/var/lib/postgresql/data
```

3. `.env` 增加 `DATABASE_URL=postgresql://zsmian:密码@127.0.0.1:5432/interview_system`；`.env.example` 同步加说明（不填真实密码）
4. config.py：`DATABASE_URL = os.getenv("DATABASE_URL", "")`，并保留 `DATABASE_NAME`（SQLite 回退用）

### 阶段 2：连接层改造（2~3h，核心）

1. db_pool.py 内部重写：`psycopg_pool.ThreadedConnectionPool(min=1, max=10, open=False)` + 手动 open；`get_connection()` 返回的连接设置 `row_factory=dict_row`（dict 行支持 `row["col"]` 语法，上层大部分代码不感知）
2. 事务语义变化（重要）：SQLite 每句自动提交，psycopg 事务需显式 `conn.commit()`。方案：在 get_connection 里设 `conn.autocommit = True` 起步（行为与 SQLite 完全一致），多语句原子写的地方后续单独加事务块——先保证行为等价，再谈优化
3. db.py（旧每操作一连接模式）：同样改 psycopg，或标记废弃统一走 db_pool（视引用量定，减少双轨）
4. `close_all()`：psycopg 的池自带 close，直接替换

### 阶段 3：建表脚本 PG 方言（2~3h）

1. create_personal_interview_system_db.py 重构为按 `DATABASE_URL` 分发：
   - 空 → 走原 SQLite 路径（回退开关，一行不动）
   - `postgresql://` 开头 → 走新增的 PG 建表函数
2. PG 建表函数：13 张表逐张翻译（AUTOINCREMENT→IDENTITY，字段级 SQL 注释保留），无 PRAGMA，外键显式写上（PG 会强制执行，注意 data 里孤儿数据——搬迁前先清洗）
3. 自动补列迁移段改用 `information_schema.columns` 判断
4. 保留"启动时 init_db() 自动执行"的项目约定（main.py 不变）

### 阶段 4：业务 SQL 清理（3~5h，机械但量大）

1. 全局 grep `?`（execute 内）→ `%s`：逐文件过 interview_api / resume_api / report_api / auth_api / deps / expression_api / report_service / question_service / payment_module / main
2. 全局 grep `lastrowid` → RETURNING id
3. 全局 grep `INSERT OR` / `strftime` / `datetime(` → PG 等价
4. 行取值复查：`row["col"]` 不用动；`row[0]` 下标取值（sqlite3.Row 支持、dict 不支持）→ 改列名取值
5. 每改完一个文件跑一次该模块冒烟（见阶段 6 清单，分模块过）

### 阶段 5：数据搬迁脚本（2h）

新建一次性脚本 `app/db/migrate_sqlite_to_pg.py`：

1. 读 backup .db 全部 13 张表 → 按外键依赖顺序 INSERT INTO PG（显式保留原 id，防外键断链）
2. 每表搬完 `setval` 校准序列（`SELECT setval(pg_get_serial_sequence('表','id'), (SELECT max(id) FROM 表))`），否则新插入主键冲突
3. 迁移前孤儿数据检查：interviews.user_id 指向不存在的 users 等外键断链数据，先修复或剔除
4. 打印各表行数对照（源 vs 目标），人工核对
5. 脚本可重复执行（先 TRUNCATE 目标表再灌）

### 阶段 6：验证（2h）

冒烟清单（对照阶段 0 基线）：

- [ ] 注册 / 登录 / 登出（auth_token 生效）
- [ ] 上传简历（PDF/DOCX/TXT）→ 建场 → AI 出题 5 道
- [ ] 断点续答：答 1 题退出重进，从第 2 题继续
- [ ] 提交答案 → 生成报告 → 已完成面试直接回存档报告（不再调 LLM）
- [ ] 表情抓拍入库、报告聚合情绪分布
- [ ] 配额扣减与显示（/api/user/quota）
- [ ] 历史记录列表归属正确（user_id 对应）
- [ ] 并发场景：两个终端同时答题不报 `database is locked`（这就是换 PG 的意义）
- [ ] Docker compose 起 app + postgres 全链路再过一遍

### 阶段 7：收尾（1h）

1. README「数据库设计」章节同步：ER 图、表说明、连接配置说明（项目硬性约定）
2. `.gitignore`：`*.db` 规则保留（备份文件不入库）
3. 稳定运行数天后，另开提交删除 SQLite 建表路径与回退开关（干净收口）

## 四、回退方案

- 迁移全程在 feature 分支，任何阶段崩了 `git checkout main` 即回原状
- 双方言开关在阶段 7 收尾前一直保留：`.env` 删掉 `DATABASE_URL` → 回 SQLite 全功能
- 数据安全：backup .db 只读不写；迁移后发现 PG 有问题，SQLite 路径 + 备份文件随时可恢复现场

## 五、风险与对策

| 风险 | 对策 |
|---|---|
| psycopg 事务语义与 SQLite 自动提交不一致导致漏 commit | 阶段 2 用 `autocommit=True` 起步保证行为等价 |
| 搬迁后自增序列未校准 → 新数据主键冲突 | 阶段 5 每表强制 setval |
| 历史孤儿数据在 PG 外键下插入失败 | 阶段 5 迁移前孤儿检查（项目已知有 user_id=1 傀儡账号历史） |
| `row[0]` 下标取值在 dict 行下静默出错 | 阶段 4 逐文件 grep 下标取值 |
| 大量 `?`→`%s` 漏改只在运行时暴露 | 按模块改、按模块冒烟，不攒到最后一起测 |

## 六、工作量预估

阶段 0~7 合计约 **13~17 小时**（3~5 个半天会话），建议拆 3 次提交：基础设施+连接层 / 建表+业务 SQL / 搬迁+收尾。
