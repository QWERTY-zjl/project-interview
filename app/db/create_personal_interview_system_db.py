"""
智能招聘面试模拟系统 - 个人用户版数据库初始化脚本
==============================================
作用：创建和初始化系统全部 13 张数据库表，是表结构的「权威来源」。
程序每次启动时由 app/db/db.py 的 init_db() 自动 import 执行，也可手动运行。

按 DATABASE_URL 分发的双方言版本：
  - config.DATABASE_URL 有值（postgresql:// 开头）→ _init_postgresql()：PG 方言建表
  - DATABASE_URL 为空                             → _init_sqlite()：SQLite 建表
    （回退开关：删掉 .env 里的 DATABASE_URL 即整体回到 SQLite）
  PG 建表 SQL 一次性写全所有字段，无补列逻辑；
  SQLite 分支额外含探测式补列，兼容缺字段的已有库。

本文件 = Python 外壳 + SQL 内芯：
  1. 分发段   ：读 DATABASE_URL，决定走 PG 还是 SQLite
  2. 建表段   ：逐张 CREATE TABLE IF NOT EXISTS
  3. 初始数据 ：插入默认面试类型和默认套餐（幂等，重复执行不会插重）
  4. 收尾     ：commit 提交事务 + close 关闭连接
"""

import os
import sqlite3

# 【分发开关】和 config.py 保持同源：直接读环境变量（config.py 也是这么读的）。
# load_dotenv 在 config.py 里已经执行过，但本脚本可能被单独手动运行（不经过
# config.py），所以这里再调一次 load_dotenv 保证 .env 一定被加载
from dotenv import load_dotenv
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "")


# ============================================================================
# 分支一：PostgreSQL 建表
# ============================================================================
def _init_postgresql():
    """
    用 PG 方言创建全部 13 张表 + 初始数据

    【SQLite → PG 方言翻译对照】（逐条对应下面的 SQL）：
      INTEGER PRIMARY KEY AUTOINCREMENT
          → BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY
          （IDENTITY = PG 的标准自增语法，INSERT 时不给 id 就自动编号）
      INTEGER 存 Unix 时间戳
          → BIGINT（SQLite 的 INTEGER 是 8 字节，PG 的 INTEGER 只有 4 字节，
            2038 年会溢出，所以时间戳列一律用 8 字节的 BIGINT）
      REAL（SQLite 的 8 字节浮点）
          → DOUBLE PRECISION（注意：PG 的 REAL 是 4 字节单精度，直接用
            REAL 会丢精度，必须用 8 字节的 DOUBLE PRECISION 才和 SQLite 等价）
      TEXT → TEXT（一致）
      BLOB → BYTEA（PG 的二进制大对象类型）
      DEFAULT (strftime('%s', 'now'))（当前 Unix 秒）
          → DEFAULT (EXTRACT(EPOCH FROM now())::BIGINT)
          （now() = PG 的当前时间，EXTRACT(EPOCH ...) 取 Unix 秒数，
            ::BIGINT 是 PG 的类型转换语法，等价于 CAST(... AS BIGINT)）

    【外键说明】SQLite 建表里的 FOREIGN KEY 声明默认不强制执行（只是文档），
    PG 会真正强制校验：插入的 user_id 必须在 users 表里真实存在，否则报错。
    所以数据搬迁（migrate_sqlite_to_pg.py）前必须先清理孤儿数据。
    """
    # psycopg3 的 import 放在函数内：DATABASE_URL 为空的机器可能根本没装
    # psycopg（回退环境），文件顶 import 会让 SQLite 回退路径直接报 ImportError
    import psycopg

    # connect_timeout=5：PG 没启动时 5 秒报错快速失败，而不是干等几分钟
    conn = psycopg.connect(DATABASE_URL, connect_timeout=5)
    cursor = conn.cursor()

    # ==================== 用户表 (users) ====================
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        -- 主键自增：GENERATED ALWAYS AS IDENTITY = 插入时自动编号（PG 标准写法）
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        username TEXT NOT NULL,                 -- 用户名（必填）
        email TEXT,                             -- 邮箱
        password_hash TEXT,                     -- 密码哈希（只存摘要不存明文）
        -- 注册时间：默认当前 Unix 秒（EXTRACT 从 now() 里取秒数再转整数）
        created_at BIGINT DEFAULT (EXTRACT(EPOCH FROM now())::BIGINT),
        last_login_at BIGINT,                   -- 最后登录时间（登录成功时由代码更新）
        -- 剩余可用 AI 面试次数：注册默认 3 次；每场"大模型成功出题"扣 1 次
        interview_quota INTEGER DEFAULT 3,      -- 可用面试次数（个人版唯一配额项）
        -- 登录会话凭证：登录成功生成随机 token 写入本列并下发给前端（登出置 NULL）
        auth_token TEXT,
        phone TEXT,                             -- 手机号（原 SQLite 迁移段补列）
        user_type TEXT DEFAULT 'free',          -- 账号类型（企业版遗留，保留兼容）
        status INTEGER DEFAULT 1                -- 账号状态：0=禁用 1=正常
    )
    ''')

    # ==================== 面试类型表 (interview_types) ====================
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS interview_types (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        name TEXT NOT NULL,                     -- 类型名（如"前端开发面试"）
        description TEXT,                       -- 类型描述
        difficulty_level INTEGER,               -- 难度等级
        duration INTEGER,                       -- 预计时长（分钟）
        question_count INTEGER                  -- 该类型默认出题数量
    )
    ''')

    # ==================== 面试表 (interviews) ====================
    # 状态说明：0=未开始，1=试题已备好，2=面试进行中，3=面试完毕，4=面试报告已生成
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS interviews (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id INTEGER NOT NULL,                -- 谁的面试（外键 → users.id）
        interview_type_id INTEGER,               -- 面哪种类型（外键 → interview_types.id）
        start_time BIGINT,                       -- 开始时间（Unix时间戳）
        end_time BIGINT,                         -- 结束时间
        status INTEGER,                          -- 状态 0~4（含义见上方注释）
        question_count INTEGER,                  -- 本场题目数
        total_score DOUBLE PRECISION,            -- 总分（报告生成后写入）
        voice_reading INTEGER,                   -- 是否语音读题（0/1）
        voice_type TEXT DEFAULT 'professional_male',  -- 面试官音色
        -- 评估报告（JSON 文本）
        report_content TEXT,
        token TEXT,                              -- 面试链接令牌（候选人凭它访问专属面试页）
        FOREIGN KEY (user_id) REFERENCES users(id),   -- 外键：关联用户表（PG 真强制）
        FOREIGN KEY (interview_type_id) REFERENCES interview_types(id)
    )
    ''')

    # ==================== 面试问题表 (interview_questions) ====================
    # 题目类型：voice=语音回答题，text=手写/文本题
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS interview_questions (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        interview_id INTEGER NOT NULL,           -- 属于哪场面试（外键 → interviews.id）
        question TEXT NOT NULL,                  -- 题目文本（LLM 生成）
        question_type TEXT DEFAULT 'voice',      -- 题型：voice=语音回答，text=文字回答
        score_standard TEXT,                     -- 评分标准（出题时一并生成）
        answer_audio BYTEA,                      -- 候选人回答的录音
        answer_text TEXT,                        -- 回答的转写文本
        created_at BIGINT DEFAULT (EXTRACT(EPOCH FROM now())::BIGINT),  -- 出题时间
        answered_at BIGINT,                      -- 回答时间
        question_audio BYTEA,                    -- 预生成的题目朗读语音（TTS 合成）
        voice_type TEXT,                         -- 该题朗读使用的音色
        user_score DOUBLE PRECISION,             -- 该题得分（原 SQLite 迁移段补列）
        feedback TEXT,                           -- 该题的 AI 点评（原迁移段补列）
        FOREIGN KEY (interview_id) REFERENCES interviews(id)
    )
    ''')

    # ==================== 面试表情记录表 (interview_expression_records) ====================
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS interview_expression_records (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        interview_id INTEGER NOT NULL,           -- 属于哪场面试（外键 → interviews.id）
        expression TEXT,                         -- 识别到的表情（英文标签）
        expression_cn TEXT,                      -- 表情中文名
        confidence DOUBLE PRECISION,             -- 识别置信度（0~1，越高越可信）
        emotion_status TEXT,                     -- 情绪状态（如专注/紧张）
        emotion_score DOUBLE PRECISION,          -- 情绪得分
        quality_score DOUBLE PRECISION,          -- 画质得分
        final_score DOUBLE PRECISION,            -- 综合得分
        suggestions TEXT,                        -- 改进建议
        -- 采样时间点（面试进行到第几秒）。timestamp 本身是 PG 的类型名，
        -- 但允许直接用作列名（非保留字），与 SQLite 版保持同名不改动业务代码
        timestamp BIGINT,
        FOREIGN KEY (interview_id) REFERENCES interviews(id)
    )
    ''')

    # ==================== 练习进度表 (practice_progress) ====================
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS practice_progress (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id INTEGER NOT NULL,                -- 谁（外键 → users.id）
        interview_type_id INTEGER,               -- 练的哪种类型（外键 → interview_types.id）
        total_practices INTEGER DEFAULT 0,       -- 总练习次数
        completed_practices INTEGER DEFAULT 0,   -- 完成次数
        average_score DOUBLE PRECISION DEFAULT 0, -- 平均分
        last_practice_at BIGINT,                 -- 最近一次练习时间
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (interview_type_id) REFERENCES interview_types(id)
    )
    ''')

    # ==================== 反馈数据表 (feedback_data) ====================
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS feedback_data (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id INTEGER NOT NULL,                -- 谁提的反馈（外键 → users.id）
        interview_id INTEGER,                    -- 针对哪场面试（外键 → interviews.id）
        feedback_type TEXT,                      -- 反馈类型（如 bug/建议）
        feedback_content TEXT,                   -- 反馈正文
        rating INTEGER,                          -- 评分
        created_at BIGINT DEFAULT (EXTRACT(EPOCH FROM now())::BIGINT),  -- 反馈时间
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (interview_id) REFERENCES interviews(id)
    )
    ''')

    # ==================== 支付扩展表（用户配额/套餐/订单/订阅/使用记录/支付配置）====================
    # payment_module.py（用户认证/配额/套餐/订单）运行时需要这些表

    # 用户配额表（记录用户的免费额度和付费额度）
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_quotas (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id INTEGER NOT NULL,
        free_interviews_remaining INTEGER DEFAULT 3,      -- 免费面试次数
        total_interviews_used INTEGER DEFAULT 0,          -- 已使用面试次数
        tts_quota_minutes INTEGER DEFAULT 10,             -- TTS配额（分钟）
        tts_used_minutes DOUBLE PRECISION DEFAULT 0,      -- 已使用TTS（分钟）
        ai_analysis_quota INTEGER DEFAULT 5,              -- AI分析配额（次数）
        ai_analysis_used INTEGER DEFAULT 0,               -- 已使用AI分析次数
        reset_date BIGINT,                                -- 配额重置日期
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    ''')

    # 套餐表（定义可购买的套餐；code 有唯一约束——初始数据靠它判重）
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS pricing_plans (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        name TEXT NOT NULL,                               -- 套餐名称
        code TEXT UNIQUE NOT NULL,                        -- 套餐代码（唯一）
        description TEXT,                                 -- 套餐描述
        plan_type TEXT NOT NULL,                          -- onetime/monthly/yearly
        price DOUBLE PRECISION NOT NULL,                  -- 价格（元）
        original_price DOUBLE PRECISION,                  -- 原价（用于显示折扣）
        interviews_included INTEGER DEFAULT 0,            -- 包含面试次数
        tts_minutes_included INTEGER DEFAULT 0,           -- 包含TTS分钟数
        ai_analysis_included INTEGER DEFAULT 0,           -- 包含AI分析次数
        validity_days INTEGER DEFAULT 30,                 -- 有效期（天）
        is_recommended INTEGER DEFAULT 0,                 -- 是否推荐
        sort_order INTEGER DEFAULT 0,                     -- 排序
        status INTEGER DEFAULT 1,                         -- 0=下架, 1=上架
        created_at BIGINT DEFAULT (EXTRACT(EPOCH FROM now())::BIGINT)
    )
    ''')

    # 订单表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS orders (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        order_no TEXT UNIQUE NOT NULL,                    -- 订单号（唯一）
        user_id INTEGER NOT NULL,
        plan_id INTEGER,                                  -- 购买的套餐ID
        plan_name TEXT,                                   -- 套餐名称（快照）
        amount DOUBLE PRECISION NOT NULL,                 -- 订单金额
        pay_method TEXT,                                  -- 支付方式: alipay=支付宝
        pay_status INTEGER DEFAULT 0,                     -- 0=未支付,1=已支付,2=已取消,3=已退款
        pay_time BIGINT,                                  -- 支付时间
        pay_trade_no TEXT,                                -- 第三方支付流水号
        validity_start BIGINT,                            -- 有效期开始
        validity_end BIGINT,                              -- 有效期结束
        created_at BIGINT DEFAULT (EXTRACT(EPOCH FROM now())::BIGINT),
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (plan_id) REFERENCES pricing_plans(id)
    )
    ''')

    # 用户订阅表（记录用户的订阅状态；企业版遗留，保留兼容）
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_subscriptions (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id INTEGER NOT NULL,                         -- 哪个用户的订阅
        plan_id INTEGER NOT NULL,                         -- 订的哪个套餐
        order_id INTEGER NOT NULL,                        -- 由哪笔订单产生
        status INTEGER DEFAULT 1,                         -- 0=已过期, 1=有效, 2=已取消
        start_date BIGINT NOT NULL,                       -- 生效日期
        end_date BIGINT NOT NULL,                         -- 到期日期
        interviews_remaining INTEGER DEFAULT 0,           -- 剩余面试次数
        tts_minutes_remaining DOUBLE PRECISION DEFAULT 0, -- 剩余TTS分钟数
        ai_analysis_remaining INTEGER DEFAULT 0,          -- 剩余AI分析次数
        auto_renew INTEGER DEFAULT 0,                     -- 是否自动续费
        created_at BIGINT DEFAULT (EXTRACT(EPOCH FROM now())::BIGINT),
        updated_at BIGINT DEFAULT (EXTRACT(EPOCH FROM now())::BIGINT),
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (plan_id) REFERENCES pricing_plans(id),
        FOREIGN KEY (order_id) REFERENCES orders(id)
    )
    ''')

    # 使用记录表（记录用户的具体使用情况）
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS usage_logs (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id INTEGER NOT NULL,
        resource_type TEXT NOT NULL,            -- interview=面试, tts=语音合成, ai_analysis=AI分析
        resource_id INTEGER,                    -- 关联的资源ID
        quantity_used DOUBLE PRECISION NOT NULL, -- 使用量
        quantity_unit TEXT,                     -- 单位: count=次数, minutes=分钟
        cost_type TEXT,                         -- free/subscription/pay_per_use
        order_id INTEGER,                       -- 关联的订单（如果是付费）
        created_at BIGINT DEFAULT (EXTRACT(EPOCH FROM now())::BIGINT),
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (order_id) REFERENCES orders(id)
    )
    ''')

    # 支付配置表（存储支付宝等配置）
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS payment_configs (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        pay_method TEXT UNIQUE NOT NULL,        -- alipay=支付宝
        app_id TEXT,                            -- 支付宝应用ID
        private_key TEXT,                       -- 商户私钥（签名用，绝不外泄）
        public_key TEXT,                        -- 商户公钥
        alipay_public_key TEXT,                 -- 支付宝公钥（验签用）
        notify_url TEXT,                        -- 支付成功后支付宝回调通知的地址
        return_url TEXT,                        -- 支付完成后跳回页面的地址
        sandbox_mode INTEGER DEFAULT 1,         -- 0=生产环境, 1=沙箱环境
        status INTEGER DEFAULT 0,               -- 0=禁用, 1=启用
        created_at BIGINT DEFAULT (EXTRACT(EPOCH FROM now())::BIGINT),
        updated_at BIGINT DEFAULT (EXTRACT(EPOCH FROM now())::BIGINT)
    )
    ''')

    # ==================== 初始数据（幂等） ====================
    # 【与 SQLite 版的差异】SQLite 用 INSERT OR IGNORE（无唯一列时其实判不了重），
    # PG 版改用两种更可靠的幂等手段：
    #   1. pricing_plans：ON CONFLICT (code) DO NOTHING —— code 列有 UNIQUE 约束，
    #      已存在同 code 的套餐就跳过（这是 PG 对 "INSERT OR IGNORE" 的等价写法）
    #   2. interview_types：表里没有任何唯一列，没法用 ON CONFLICT，
    #      所以先数行数：非 0 说明插过（或搬过数据），直接跳过
    default_plans = [
        # 免费试用
        ('免费试用', 'free_trial', '新用户免费体验3次面试', 'onetime', 0, None, 3, 10, 5, 30, 0, 1),
        # 按次付费
        ('单次面试', 'single_interview', '单次AI面试，适合偶尔使用', 'onetime', 9.9, 19.9, 1, 30, 5, 30, 0, 2),
        ('5次面试包', 'interview_pack_5', '5次AI面试，经济实惠', 'onetime', 39.9, 99.5, 5, 150, 25, 90, 1, 3),
        ('10次面试包', 'interview_pack_10', '10次AI面试，赠送更多TTS时长', 'onetime', 69.9, 199, 10, 300, 50, 90, 0, 4),
        # 包月订阅
        ('月度会员', 'monthly_premium', '无限次面试+500分钟语音合成', 'monthly', 199, 299, 999999, 500, 100, 30, 1, 5),
        # 包年订阅
        ('年度会员', 'yearly_premium', '无限次面试+6000分钟语音合成，最划算', 'yearly', 1999, 3588, 999999, 6000, 1200, 365, 1, 6),
    ]

    # PG 占位符是 %s（SQLite 是 ?）：值参数化传给 psycopg，防注入
    for plan in default_plans:
        cursor.execute('''
        INSERT INTO pricing_plans
        (name, code, description, plan_type, price, original_price, interviews_included,
         tts_minutes_included, ai_analysis_included, validity_days, is_recommended, sort_order)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (code) DO NOTHING
        ''', plan)

    # 默认面试类型：先查行数判重（表没有唯一列，只能手动幂等）
    cursor.execute('SELECT COUNT(*) FROM interview_types')
    if cursor.fetchone()[0] == 0:
        cursor.execute('''
        INSERT INTO interview_types (name, description, difficulty_level, duration, question_count) VALUES
        ('前端开发面试', '针对前端开发岗位的技术面试', 3, 30, 5),
        ('后端开发面试', '针对后端开发岗位的技术面试', 3, 30, 5),
        ('产品经理面试', '针对产品经理岗位的面试', 2, 25, 4),
        ('数据分析面试', '针对数据分析岗位的技术面试', 3, 30, 5),
        ('行为面试', '针对个人综合素质的行为面试', 2, 20, 4)
        ''')

    conn.commit()
    conn.close()
    print("PostgreSQL 数据库 13 张表已成功创建。")


# ============================================================================
# 分支二：SQLite 建表（原有逻辑，一行未动，仅包进函数作为回退开关）
# ============================================================================
def _init_sqlite():
    # 路径锚定到脚本所在目录：不管从哪个目录启动，连的都是同一个库，
    # 避免"在别的目录运行时凭空生成一个空库"
    conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'interview_system.db'))
    cursor = conn.cursor()

    # ==================== 用户表 (users) ====================
    # 用于存储个人用户信息
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,   -- 主键：自增编号，每个用户唯一
        username TEXT NOT NULL,                 -- 用户名（NOT NULL = 必填）
        email TEXT,                             -- 邮箱
        password_hash TEXT,                     -- 密码哈希（只存摘要不存明文）
        created_at INTEGER DEFAULT (strftime('%s', 'now')),  -- 注册时间，默认当前Unix时间戳
        last_login_at INTEGER,                  -- 最后登录时间（登录成功时由代码更新）
        -- 剩余可用 AI 面试次数：注册默认 3 次；每场"大模型成功出题"的面试扣 1 次
        --（出题降级为默认题库时不扣——没消耗大模型就不算用掉额度，见 question_service.py）
        interview_quota INTEGER DEFAULT 3,      -- 可用面试次数（个人版唯一配额项）
        -- 登录会话凭证：登录成功时生成随机 token 写入本列并下发给前端，
        -- 之后所有需要身份的接口凭请求头里的 token 反查本表确定"当前用户"。
        auth_token TEXT                         -- 登录会话凭证（登出时置 NULL）
    )
    ''')

    # ==================== 面试类型表 (interview_types) ====================
    # 用于存储不同类型的面试
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS interview_types (
        id INTEGER PRIMARY KEY AUTOINCREMENT,   -- 主键
        name TEXT NOT NULL,                     -- 类型名（如"前端开发面试"）
        description TEXT,                       -- 类型描述
        difficulty_level INTEGER,               -- 难度等级
        duration INTEGER,                       -- 预计时长（分钟）
        question_count INTEGER                  -- 该类型默认出题数量
    )
    ''')

    # ==================== 面试表 (interviews) ====================
    # 用于存储面试安排和记录
    # 状态说明：0=未开始，1=试题已备好，2=面试进行中，3=面试完毕，4=面试报告已生成
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS interviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,                -- 谁的面试（外键 → users.id）
        interview_type_id INTEGER,               -- 面哪种类型（外键 → interview_types.id）
        start_time INTEGER,                      -- 开始时间（Unix时间戳）
        end_time INTEGER,                        -- 结束时间
        status INTEGER,                          -- 状态 0~4（含义见上方注释）
        question_count INTEGER,                  -- 本场题目数
        total_score REAL,                        -- 总分（报告生成后写入）
        voice_reading INTEGER,                   -- 是否语音读题（0/1）
        voice_type TEXT DEFAULT 'professional_male',  -- 面试官音色
        report_content BLOB,                     -- 评估报告PDF（BLOB = 存二进制文件的字段类型）
        token TEXT,                              -- 面试链接令牌（候选人凭它访问专属面试页）
        -- 【FOREIGN KEY 语法】FOREIGN KEY (本表列名) REFERENCES 对方表(对方列名)
        -- 含义：user_id 这一列存的值，必须能在 users.id 里找到（存的是"指向"）
        -- 注：SQLite 默认不强制校验外键，此声明主要用于文档说明和 ER 图工具自动画连线
        FOREIGN KEY (user_id) REFERENCES users(id), -- 外键：关联用户表
        FOREIGN KEY (interview_type_id) REFERENCES interview_types(id) -- 外键：关联面试类型表
    )
    ''')

    # ==================== 面试问题表 (interview_questions) ====================
    # 用于存储面试题目、答案和语音文件
    # 题目类型：voice=语音回答题，text=手写/文本题
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS interview_questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        interview_id INTEGER NOT NULL,           -- 属于哪场面试（外键 → interviews.id）
        question TEXT NOT NULL,                  -- 题目文本（LLM 生成）
        question_type TEXT DEFAULT 'voice',      -- 题型：voice=语音回答，text=文字回答
        score_standard TEXT,                     -- 评分标准（出题时一并生成）
        answer_audio BLOB,                       -- 候选人回答的录音
        answer_text TEXT,                        -- 回答的转写文本
        created_at INTEGER DEFAULT (strftime('%s', 'now')),  -- 出题时间
        answered_at INTEGER,                     -- 回答时间
        question_audio BLOB,                     -- 预生成的题目朗读语音（TTS 合成）
        voice_type TEXT,                         -- 该题朗读使用的音色
        user_score REAL,                         -- 该题得分
        feedback TEXT,                           -- 该题的 AI 点评
        FOREIGN KEY (interview_id) REFERENCES interviews(id)
    )
    ''')

    # ==================== 面试表情记录表 (interview_expression_records) ====================
    # 用于存储面试过程中的表情识别数据，支持情绪分析
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS interview_expression_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        interview_id INTEGER NOT NULL,           -- 属于哪场面试（外键 → interviews.id）
        expression TEXT,                         -- 识别到的表情（英文标签）
        expression_cn TEXT,                      -- 表情中文名
        confidence REAL,                         -- 识别置信度（0~1，越高越可信）
        emotion_status TEXT,                     -- 情绪状态（如专注/紧张）
        emotion_score REAL,                      -- 情绪得分
        quality_score REAL,                      -- 画质得分
        final_score REAL,                        -- 综合得分
        suggestions TEXT,                        -- 改进建议
        timestamp INTEGER,                       -- 采样时间点（面试进行到第几秒）
        FOREIGN KEY (interview_id) REFERENCES interviews(id)
    )
    ''')

    # ==================== 练习进度表 (practice_progress) ====================
    # 用于存储用户的练习进度
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS practice_progress (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,                -- 谁（外键 → users.id）
        interview_type_id INTEGER,               -- 练的哪种类型（外键 → interview_types.id）
        total_practices INTEGER DEFAULT 0,       -- 总练习次数
        completed_practices INTEGER DEFAULT 0,   -- 完成次数
        average_score REAL DEFAULT 0,            -- 平均分
        last_practice_at INTEGER,                -- 最近一次练习时间
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (interview_type_id) REFERENCES interview_types(id)
    )
    ''')

    # ==================== 反馈数据表 (feedback_data) ====================
    # 用于存储用户的反馈数据
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS feedback_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,                -- 谁提的反馈（外键 → users.id）
        interview_id INTEGER,                    -- 针对哪场面试（外键 → interviews.id）
        feedback_type TEXT,                      -- 反馈类型（如 bug/建议）
        feedback_content TEXT,                   -- 反馈正文
        rating INTEGER,                          -- 评分
        created_at INTEGER DEFAULT (strftime('%s', 'now')),  -- 反馈时间
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (interview_id) REFERENCES interviews(id)
    )
    ''')

    # ==================== 支付扩展表 ====================
    # payment_module.py（用户认证/配额/套餐/订单）运行时需要这些表，
    # 由 db.py 的 init_db() 在程序启动时自动创建

    # 用户配额表（记录用户的免费额度和付费额度）
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_quotas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        free_interviews_remaining INTEGER DEFAULT 3, -- 免费面试次数
        total_interviews_used INTEGER DEFAULT 0, -- 已使用面试次数
        tts_quota_minutes INTEGER DEFAULT 10, -- TTS配额（分钟）
        tts_used_minutes REAL DEFAULT 0, -- 已使用TTS（分钟）
        ai_analysis_quota INTEGER DEFAULT 5, -- AI分析配额（次数）
        ai_analysis_used INTEGER DEFAULT 0, -- 已使用AI分析次数
        reset_date INTEGER, -- 配额重置日期
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    ''')

    # 套餐表（定义可购买的套餐）
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS pricing_plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, -- 套餐名称
        code TEXT UNIQUE NOT NULL, -- 套餐代码
        description TEXT, -- 套餐描述
        plan_type TEXT NOT NULL, -- 类型: onetime=按次, monthly=包月, yearly=包年
        price REAL NOT NULL, -- 价格（元）
        original_price REAL, -- 原价（用于显示折扣）
        interviews_included INTEGER DEFAULT 0, -- 包含面试次数
        tts_minutes_included INTEGER DEFAULT 0, -- 包含TTS分钟数
        ai_analysis_included INTEGER DEFAULT 0, -- 包含AI分析次数
        validity_days INTEGER DEFAULT 30, -- 有效期（天）
        is_recommended INTEGER DEFAULT 0, -- 是否推荐
        sort_order INTEGER DEFAULT 0, -- 排序
        status INTEGER DEFAULT 1, -- 0=下架, 1=上架
        created_at INTEGER DEFAULT (strftime('%s', 'now'))
    )
    ''')

    # 订单表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_no TEXT UNIQUE NOT NULL, -- 订单号
        user_id INTEGER NOT NULL,
        plan_id INTEGER, -- 购买的套餐ID
        plan_name TEXT, -- 套餐名称（快照）
        amount REAL NOT NULL, -- 订单金额
        pay_method TEXT, -- 支付方式: alipay=支付宝
        pay_status INTEGER DEFAULT 0, -- 0=未支付, 1=已支付, 2=已取消, 3=已退款
        pay_time INTEGER, -- 支付时间
        pay_trade_no TEXT, -- 第三方支付流水号
        validity_start INTEGER, -- 有效期开始
        validity_end INTEGER, -- 有效期结束
        created_at INTEGER DEFAULT (strftime('%s', 'now')),
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (plan_id) REFERENCES pricing_plans(id)
    )
    ''')

    # 用户订阅表（记录用户的订阅状态）
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,                -- 哪个用户的订阅
        plan_id INTEGER NOT NULL,                -- 订的哪个套餐（外键 → pricing_plans.id）
        order_id INTEGER NOT NULL,               -- 由哪笔订单产生（外键 → orders.id）
        status INTEGER DEFAULT 1, -- 0=已过期, 1=有效, 2=已取消
        start_date INTEGER NOT NULL,             -- 生效日期
        end_date INTEGER NOT NULL,               -- 到期日期（会员有效期判断依据）
        interviews_remaining INTEGER DEFAULT 0,  -- 剩余面试次数
        tts_minutes_remaining REAL DEFAULT 0,    -- 剩余TTS分钟数
        ai_analysis_remaining INTEGER DEFAULT 0, -- 剩余AI分析次数
        auto_renew INTEGER DEFAULT 0, -- 是否自动续费
        created_at INTEGER DEFAULT (strftime('%s', 'now')),
        updated_at INTEGER DEFAULT (strftime('%s', 'now')),
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (plan_id) REFERENCES pricing_plans(id),
        FOREIGN KEY (order_id) REFERENCES orders(id)
    )
    ''')

    # 使用记录表（记录用户的具体使用情况）
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS usage_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        resource_type TEXT NOT NULL, -- interview=面试, tts=语音合成, ai_analysis=AI分析
        resource_id INTEGER, -- 关联的资源ID
        quantity_used REAL NOT NULL, -- 使用量
        quantity_unit TEXT, -- 单位: count=次数, minutes=分钟
        cost_type TEXT, -- free=免费额度, subscription=订阅额度, pay_per_use=按量付费
        order_id INTEGER, -- 关联的订单（如果是付费）
        created_at INTEGER DEFAULT (strftime('%s', 'now')),
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (order_id) REFERENCES orders(id)
    )
    ''')

    # 支付配置表（存储支付宝等配置）
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS payment_configs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pay_method TEXT UNIQUE NOT NULL, -- alipay=支付宝
        app_id TEXT,                     -- 支付宝应用ID
        private_key TEXT,                -- 商户私钥（签名用，绝不外泄）
        public_key TEXT,                 -- 商户公钥
        alipay_public_key TEXT,          -- 支付宝公钥（验签用）
        notify_url TEXT,                 -- 支付成功后支付宝回调通知的地址
        return_url TEXT,                 -- 支付完成后跳回页面的地址
        sandbox_mode INTEGER DEFAULT 1, -- 0=生产环境, 1=沙箱环境
        status INTEGER DEFAULT 0, -- 0=禁用, 1=启用
        created_at INTEGER DEFAULT (strftime('%s', 'now')),
        updated_at INTEGER DEFAULT (strftime('%s', 'now'))
    )
    ''')

    # 初始化默认套餐数据（INSERT OR IGNORE：已存在则跳过，可重复执行）
    default_plans = [
        # 免费试用
        ('免费试用', 'free_trial', '新用户免费体验3次面试', 'onetime', 0, None, 3, 10, 5, 30, 0, 1),
        # 按次付费
        ('单次面试', 'single_interview', '单次AI面试，适合偶尔使用', 'onetime', 9.9, 19.9, 1, 30, 5, 30, 0, 2),
        ('5次面试包', 'interview_pack_5', '5次AI面试，经济实惠', 'onetime', 39.9, 99.5, 5, 150, 25, 90, 1, 3),
        ('10次面试包', 'interview_pack_10', '10次AI面试，赠送更多TTS时长', 'onetime', 69.9, 199, 10, 300, 50, 90, 0, 4),
        # 包月订阅
        ('月度会员', 'monthly_premium', '无限次面试+500分钟语音合成', 'monthly', 199, 299, 999999, 500, 100, 30, 1, 5),
        # 包年订阅
        ('年度会员', 'yearly_premium', '无限次面试+6000分钟语音合成，最划算', 'yearly', 1999, 3588, 999999, 6000, 1200, 365, 1, 6),
    ]

    # ? 占位符参数化传值防注入；plan 元组值的顺序必须与列清单一一对应
    for plan in default_plans:
        cursor.execute('''
        INSERT OR IGNORE INTO pricing_plans
        (name, code, description, plan_type, price, original_price, interviews_included,
         tts_minutes_included, ai_analysis_included, validity_days, is_recommended, sort_order)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', plan)

    # ==================== 数据库迁移和字段升级 ====================
    # 【为什么需要这段】CREATE TABLE IF NOT EXISTS 对缺新字段的已有表什么都不做；
    # 下面用「探测式迁移」补列，让已有库无损升级。
    conn.commit()

    # 探测式补列：SELECT 报 no such column 说明旧表缺列，
    # ALTER TABLE ADD COLUMN 补上（新列对旧行自动填 NULL/默认值，不破坏原有数据）
    try:
        cursor.execute("SELECT user_score FROM interview_questions LIMIT 1")
    except sqlite3.OperationalError:
        print("添加 user_score 字段到 interview_questions 表...")
        cursor.execute("ALTER TABLE interview_questions ADD COLUMN user_score REAL")
        conn.commit()
        print("user_score 字段添加成功")

    try:
        cursor.execute("SELECT feedback FROM interview_questions LIMIT 1")
    except sqlite3.OperationalError:
        print("添加 feedback 字段到 interview_questions 表...")
        cursor.execute("ALTER TABLE interview_questions ADD COLUMN feedback TEXT")
        conn.commit()
        print("feedback 字段添加成功")

    # 检查并添加 total_score 字段到 interviews 表
    try:
        cursor.execute("SELECT total_score FROM interviews LIMIT 1")
    except sqlite3.OperationalError:
        print("添加 total_score 字段到 interviews 表...")
        cursor.execute("ALTER TABLE interviews ADD COLUMN total_score REAL")
        conn.commit()
        print("total_score 字段添加成功")

    # 检查并添加 user_id 字段到 interviews 表
    try:
        cursor.execute("SELECT user_id FROM interviews LIMIT 1")
    except sqlite3.OperationalError:
        print("添加 user_id 字段到 interviews 表...")
        cursor.execute("ALTER TABLE interviews ADD COLUMN user_id INTEGER")
        conn.commit()
        print("user_id 字段添加成功")

    # 检查并添加 interview_type_id 字段到 interviews 表
    try:
        cursor.execute("SELECT interview_type_id FROM interviews LIMIT 1")
    except sqlite3.OperationalError:
        print("添加 interview_type_id 字段到 interviews 表...")
        cursor.execute("ALTER TABLE interviews ADD COLUMN interview_type_id INTEGER")
        conn.commit()
        print("interview_type_id 字段添加成功")

    # 检查并添加 phone 字段到 users 表（payment_module.py 注册时会写入）
    try:
        cursor.execute("SELECT phone FROM users LIMIT 1")
    except sqlite3.OperationalError:
        print("添加 phone 字段到 users 表...")
        cursor.execute("ALTER TABLE users ADD COLUMN phone TEXT")
        conn.commit()
        print("phone 字段添加成功")

    # 检查并添加 user_type 字段到 users 表（登录/会员升级时读写）
    try:
        cursor.execute("SELECT user_type FROM users LIMIT 1")
    except sqlite3.OperationalError:
        print("添加 user_type 字段到 users 表...")
        cursor.execute("ALTER TABLE users ADD COLUMN user_type TEXT DEFAULT 'free'")
        conn.commit()
        print("user_type 字段添加成功")

    # 检查并添加 status 字段到 users 表（登录时检查账号状态，0=禁用 1=正常）
    try:
        cursor.execute("SELECT status FROM users LIMIT 1")
    except sqlite3.OperationalError:
        print("添加 status 字段到 users 表...")
        cursor.execute("ALTER TABLE users ADD COLUMN status INTEGER DEFAULT 1")
        conn.commit()
        print("status 字段添加成功")

    # 检查并添加 interview_quota 字段到 users 表（个人版唯一配额：可用 AI 面试次数）
    # 老用户的存量账号统一补默认值 3（DEFAULT 在 ALTER ADD COLUMN 时对已有行生效）
    try:
        cursor.execute("SELECT interview_quota FROM users LIMIT 1")
    except sqlite3.OperationalError:
        print("添加 interview_quota 字段到 users 表...")
        cursor.execute("ALTER TABLE users ADD COLUMN interview_quota INTEGER DEFAULT 3")
        conn.commit()
        print("interview_quota 字段添加成功")

    # 检查并添加 auth_token 字段到 users 表（登录会话凭证）
    # 与上面 interview_quota 同款探测式迁移：查询报错说明列不存在，补上即可。
    # 已有账号该列默认 NULL = 未登录状态，首次登录时才写入 token
    try:
        cursor.execute("SELECT auth_token FROM users LIMIT 1")
    except sqlite3.OperationalError:
        print("添加 auth_token 字段到 users 表...")
        cursor.execute("ALTER TABLE users ADD COLUMN auth_token TEXT")
        conn.commit()
        print("auth_token 字段添加成功")

    # ==================== 插入初始数据 ====================
    # INSERT OR IGNORE：已存在则跳过，幂等；列清单不含 id，主键自增自动编号
    # 插入默认面试类型
    cursor.execute('''
    INSERT OR IGNORE INTO interview_types (name, description, difficulty_level, duration, question_count) VALUES
    ('前端开发面试', '针对前端开发岗位的技术面试', 3, 30, 5),
    ('后端开发面试', '针对后端开发岗位的技术面试', 3, 30, 5),
    ('产品经理面试', '针对产品经理岗位的面试', 2, 25, 4),
    ('数据分析面试', '针对数据分析岗位的技术面试', 3, 30, 5),
    ('行为面试', '针对个人综合素质的行为面试', 2, 20, 4)
    ''')


    conn.commit()
    # 不关闭的话 .db 文件一直被占用，Windows 上其他工具打开会报 database is locked
    conn.close()

    print("个人用户版数据库和表已成功创建。")


# ============================================================================
# 分发入口：按 DATABASE_URL 决定走哪条建表路径
# ============================================================================
if DATABASE_URL.startswith("postgresql"):
    _init_postgresql()
else:
    _init_sqlite()
