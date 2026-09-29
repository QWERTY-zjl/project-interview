"""
智能招聘面试模拟系统 - 个人用户版数据库初始化脚本
==============================================
本脚本用于创建和初始化个人用户版系统所需的SQLite数据库表结构
包括：用户表、面试类型表、面试表、面试问题表、表情记录表、练习进度表等
"""

import os
import sqlite3

# ==================== 数据库连接 ====================
# 连接到SQLite数据库文件，如果不存在则自动创建
# 路径锚定到本脚本所在目录（app/db/），与启动时的工作目录无关，
# 避免在其他目录执行时于错误位置生成一个空库
conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'interview_system.db'))
cursor = conn.cursor()

# ==================== 用户表 (users) ====================
# 用于存储个人用户信息
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    email TEXT,
    password_hash TEXT,
    created_at INTEGER DEFAULT (strftime('%s', 'now')),
    last_login_at INTEGER
)
''')

# ==================== 面试类型表 (interview_types) ====================
# 用于存储不同类型的面试
cursor.execute('''
CREATE TABLE IF NOT EXISTS interview_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    difficulty_level INTEGER,
    duration INTEGER,
    question_count INTEGER
)
''')

# ==================== 面试表 (interviews) ====================
# 用于存储面试安排和记录
# 状态说明：0=未开始，1=试题已备好，2=面试进行中，3=面试完毕，4=面试报告已生成
cursor.execute('''
CREATE TABLE IF NOT EXISTS interviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    interview_type_id INTEGER,
    start_time INTEGER,
    end_time INTEGER,
    status INTEGER,
    question_count INTEGER,
    total_score REAL,
    voice_reading INTEGER,
    voice_type TEXT DEFAULT 'professional_male',
    report_content BLOB,
    token TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (interview_type_id) REFERENCES interview_types(id)
)
''')

# ==================== 面试问题表 (interview_questions) ====================
# 用于存储面试题目、答案和语音文件
# 题目类型：voice=语音回答题，text=手写/文本题
cursor.execute('''
CREATE TABLE IF NOT EXISTS interview_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interview_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    question_type TEXT DEFAULT 'voice',
    score_standard TEXT,
    answer_audio BLOB,
    answer_text TEXT,
    created_at INTEGER DEFAULT (strftime('%s', 'now')),
    answered_at INTEGER,
    question_audio BLOB,
    voice_type TEXT,
    user_score REAL,
    feedback TEXT,
    FOREIGN KEY (interview_id) REFERENCES interviews(id)
)
''')

# ==================== 面试表情记录表 (interview_expression_records) ====================
# 用于存储面试过程中的表情识别数据，支持情绪分析
cursor.execute('''
CREATE TABLE IF NOT EXISTS interview_expression_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interview_id INTEGER NOT NULL,
    expression TEXT,
    expression_cn TEXT,
    confidence REAL,
    emotion_status TEXT,
    emotion_score REAL,
    quality_score REAL,
    final_score REAL,
    suggestions TEXT,
    timestamp INTEGER,
    FOREIGN KEY (interview_id) REFERENCES interviews(id)
)
''')

# ==================== 练习进度表 (practice_progress) ====================
# 用于存储用户的练习进度
cursor.execute('''
CREATE TABLE IF NOT EXISTS practice_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    interview_type_id INTEGER,
    total_practices INTEGER DEFAULT 0,
    completed_practices INTEGER DEFAULT 0,
    average_score REAL DEFAULT 0,
    last_practice_at INTEGER,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (interview_type_id) REFERENCES interview_types(id)
)
''')

# ==================== 反馈数据表 (feedback_data) ====================
# 用于存储用户的反馈数据
cursor.execute('''
CREATE TABLE IF NOT EXISTS feedback_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    interview_id INTEGER,
    feedback_type TEXT,
    feedback_content TEXT,
    rating INTEGER,
    created_at INTEGER DEFAULT (strftime('%s', 'now')),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (interview_id) REFERENCES interviews(id)
)
''')

# ==================== 数据库迁移和字段升级 ====================
# 提交表结构更改
conn.commit()

# 检查并添加必要的字段
# 检查并添加 user_score 和 feedback 字段到 interview_questions 表
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

# ==================== 插入初始数据 ====================
# 插入默认面试类型
cursor.execute('''
INSERT OR IGNORE INTO interview_types (name, description, difficulty_level, duration, question_count) VALUES
('前端开发面试', '针对前端开发岗位的技术面试', 3, 30, 5),
('后端开发面试', '针对后端开发岗位的技术面试', 3, 30, 5),
('产品经理面试', '针对产品经理岗位的面试', 2, 25, 4),
('数据分析面试', '针对数据分析岗位的技术面试', 3, 30, 5),
('行为面试', '针对个人综合素质的行为面试', 2, 20, 4)
''')

# ==================== 支付扩展表（原 create_payment_tables.py 并入） ====================
# payment_module.py（用户认证/配额/套餐/订单）运行时需要这些表。
# 2026-09-28 并入本脚本：由 db.py 的 init_db() 在程序启动时自动创建，
# 不再依赖手动执行独立脚本，避免"脚本在、表没建"的漂移。
# 注意：原脚本中的 users 表定义未搬入（与本脚本的定义冲突，以本脚本 +
# 上方迁移补列的方式对齐 payment_module 所需的 phone/user_type/status）。

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
    user_id INTEGER NOT NULL,
    plan_id INTEGER NOT NULL,
    order_id INTEGER NOT NULL,
    status INTEGER DEFAULT 1, -- 0=已过期, 1=有效, 2=已取消
    start_date INTEGER NOT NULL,
    end_date INTEGER NOT NULL,
    interviews_remaining INTEGER DEFAULT 0,
    tts_minutes_remaining REAL DEFAULT 0,
    ai_analysis_remaining INTEGER DEFAULT 0,
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
    app_id TEXT,
    private_key TEXT,
    public_key TEXT,
    alipay_public_key TEXT,
    notify_url TEXT,
    return_url TEXT,
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

for plan in default_plans:
    cursor.execute('''
    INSERT OR IGNORE INTO pricing_plans
    (name, code, description, plan_type, price, original_price, interviews_included,
     tts_minutes_included, ai_analysis_included, validity_days, is_recommended, sort_order)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', plan)

# ==================== 完成 ====================
conn.commit()
conn.close()

print("个人用户版数据库和表已成功创建。")
