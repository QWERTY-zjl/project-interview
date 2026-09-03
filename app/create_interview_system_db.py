"""
智能招聘面试模拟系统 - 数据库初始化脚本
==============================================
本脚本用于创建和初始化系统所需的SQLite数据库表结构
包括：岗位表、候选人表、面试表、面试问题表、表情记录表等
"""

import sqlite3

# ==================== 数据库连接 ====================
# 连接到SQLite数据库文件，如果不存在则自动创建
conn = sqlite3.connect('interview_system.db')
cursor = conn.cursor()

# ==================== 岗位表 (positions) ====================
# 用于存储招聘岗位信息
cursor.execute('''
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    requirements TEXT,
    responsibilities TEXT,
    quantity INTEGER,
    status INTEGER,
    created_at INTEGER DEFAULT (strftime('%s', 'now')),
    recruiter TEXT
)
''')

# ==================== 候选人表 (candidates) ====================
# 用于存储申请岗位的候选人信息，包括简历附件
cursor.execute('''
CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    email TEXT,
    resume_content BLOB
)
''')

# ==================== 面试表 (interviews) ====================
# 用于存储面试安排和记录
# 状态说明：0=未开始，1=试题已备好，2=面试进行中，3=面试完毕，4=面试报告已生成
cursor.execute('''
CREATE TABLE IF NOT EXISTS interviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL,
    interviewer TEXT,
    start_time INTEGER,
    end_time INTEGER,
    status INTEGER,
    question_count INTEGER,
    is_passed INTEGER,
    voice_reading INTEGER,
    voice_type TEXT DEFAULT 'professional_male',
    report_content BLOB,
    token TEXT
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
    voice_type TEXT
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

# ==================== 数据库迁移和字段升级 ====================
# 提交表结构更改
conn.commit()

# 数据库兼容性检查：为现有数据库添加新字段
# 检查并添加 voice_type 字段到 interviews 表
try:
    cursor.execute("SELECT voice_type FROM interviews LIMIT 1")
except sqlite3.OperationalError:
    print("添加 voice_type 字段到 interviews 表...")
    cursor.execute("ALTER TABLE interviews ADD COLUMN voice_type TEXT DEFAULT 'professional_male'")
    conn.commit()
    print("voice_type 字段添加成功")

# 检查并添加 question_type 字段到 interview_questions 表
try:
    cursor.execute("SELECT question_type FROM interview_questions LIMIT 1")
except sqlite3.OperationalError:
    print("添加 question_type 字段到 interview_questions 表...")
    cursor.execute("ALTER TABLE interview_questions ADD COLUMN question_type TEXT DEFAULT 'voice'")
    conn.commit()
    print("question_type 字段添加成功")

# 检查并添加 question_audio 字段（预生成的语音文件）
try:
    cursor.execute("SELECT question_audio FROM interview_questions LIMIT 1")
except sqlite3.OperationalError:
    print("添加 question_audio 字段...")
    cursor.execute("ALTER TABLE interview_questions ADD COLUMN question_audio BLOB")
    conn.commit()
    print("question_audio 字段添加成功")

# 检查并添加 voice_type 字段到问题表（记录问题使用的音色）
try:
    cursor.execute("SELECT voice_type FROM interview_questions LIMIT 1")
except sqlite3.OperationalError:
    print("添加 voice_type 字段到 interview_questions 表...")
    cursor.execute("ALTER TABLE interview_questions ADD COLUMN voice_type TEXT")
    conn.commit()
    print("voice_type 字段添加成功")

# ==================== 完成 ====================
conn.close()

print("数据库和表已成功创建。")