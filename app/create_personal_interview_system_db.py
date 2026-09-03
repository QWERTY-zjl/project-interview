"""
智能招聘面试模拟系统 - 个人用户版数据库初始化脚本
==============================================
本脚本用于创建和初始化个人用户版系统所需的SQLite数据库表结构
包括：用户表、面试类型表、面试表、面试问题表、表情记录表、练习进度表等
"""

import sqlite3

# ==================== 数据库连接 ====================
# 连接到SQLite数据库文件，如果不存在则自动创建
conn = sqlite3.connect('interview_system.db')
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

# ==================== 完成 ====================
conn.commit()
conn.close()

print("个人用户版数据库和表已成功创建。")
