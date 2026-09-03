import sqlite3
import os

def create_payment_tables():
    """创建支付和用户相关的数据库表"""
    
    # 连接到SQLite数据库
    db_path = os.path.join(os.path.dirname(__file__), 'interview_system.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. 创建用户表（扩展现有系统，支持用户注册登录）
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        phone TEXT,
        user_type TEXT DEFAULT 'free', -- free=免费用户, premium=付费用户, admin=管理员
        status INTEGER DEFAULT 1, -- 0=禁用, 1=正常
        created_at INTEGER DEFAULT (strftime('%s', 'now')),
        updated_at INTEGER DEFAULT (strftime('%s', 'now'))
    )
    ''')
    
    # 2. 创建用户配额表（记录用户的免费额度和付费额度）
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
    
    # 3. 创建套餐表（定义可购买的套餐）
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
    
    # 4. 创建订单表
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
    
    # 5. 创建用户订阅表（记录用户的订阅状态）
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
    
    # 6. 创建使用记录表（记录用户的具体使用情况）
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
    
    # 7. 创建支付配置表（存储支付宝等配置）
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
    
    # 初始化默认套餐数据
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
    
    conn.commit()
    conn.close()
    
    print("支付相关数据库表创建成功！")
    print("\n已创建的表：")
    print("  - users: 用户表")
    print("  - user_quotas: 用户配额表")
    print("  - pricing_plans: 套餐表")
    print("  - orders: 订单表")
    print("  - user_subscriptions: 用户订阅表")
    print("  - usage_logs: 使用记录表")
    print("  - payment_configs: 支付配置表")
    print("\n已初始化默认套餐：")
    print("  - 免费试用（3次面试）")
    print("  - 单次面试（¥9.9）")
    print("  - 5次面试包（¥39.9）推荐")
    print("  - 10次面试包（¥69.9）")
    print("  - 月度会员（¥199/月）推荐")
    print("  - 年度会员（¥1999/年）推荐")

if __name__ == '__main__':
    create_payment_tables()
