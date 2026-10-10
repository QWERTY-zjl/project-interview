"""
付费功能模块 - 用户认证、配额管理、支付处理
"""
import hashlib
import secrets
import time
from datetime import datetime, timedelta
from functools import wraps

# 连接统一从 app/db/db.py 借还：PG 分支返回 psycopg3 连接（dict 行 + autocommit）。
# 用完必须 return_db 还回连接池，不能像旧 SQLite 版那样直接 conn.close()
from app.db.db import get_db, return_db

def hash_password(password):
    """密码哈希"""
    return hashlib.sha256(password.encode()).hexdigest()

def generate_token():
    """生成随机token"""
    return secrets.token_urlsafe(32)

# ==================== 用户认证相关 ====================

def register_user(username, email, password, phone=None):
    """
    注册用户
    返回: (success, message, user_id)
    """
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # 检查用户名是否已存在
        cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
        if cursor.fetchone():
            return False, "用户名已存在", None
        
        # 检查邮箱是否已存在
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            return False, "邮箱已被注册", None
        
        # 创建用户
        password_hash = hash_password(password)
        cursor.execute('''
            INSERT INTO users (username, email, password_hash, phone)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        ''', (username, email, password_hash, phone))
        # RETURNING id：psycopg3 没有 lastrowid，靠 RETURNING 拿自增 id（dict 行按列名取）
        user_id = cursor.fetchone()["id"]
        
        # 初始化用户配额（免费试用）
        reset_date = int((datetime.now() + timedelta(days=30)).timestamp())
        cursor.execute('''
            INSERT INTO user_quotas 
            (user_id, free_interviews_remaining, tts_quota_minutes, ai_analysis_quota, reset_date)
            VALUES (%s, 3, 10, 5, %s)
        ''', (user_id, reset_date))
        
        conn.commit()
        return True, "注册成功", user_id
        
    except Exception as e:
        conn.rollback()
        return False, f"注册失败: {str(e)}", None
    finally:
        return_db(conn)

def login_user(username_or_email, password):
    """
    用户登录
    返回: (success, message, user_data)
    """
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        password_hash = hash_password(password)
        
        # 支持用户名或邮箱登录
        cursor.execute('''
            SELECT id, username, email, user_type, status
            FROM users 
            WHERE (username = %s OR email = %s) AND password_hash = %s
        ''', (username_or_email, username_or_email, password_hash))
        
        user = cursor.fetchone()
        
        if not user:
            return False, "用户名或密码错误", None
        
        if user['status'] == 0:
            return False, "账号已被禁用", None
        
        # 更新最后登录时间（users 表的列名是 last_login_at，无 updated_at 列）
        cursor.execute('''
            UPDATE users SET last_login_at = %s WHERE id = %s
        ''', (int(time.time()), user['id']))
        conn.commit()
        
        return True, "登录成功", dict(user)
        
    except Exception as e:
        return False, f"登录失败: {str(e)}", None
    finally:
        return_db(conn)

def get_user_by_id(user_id):
    """根据ID获取用户信息"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT id, username, email, phone, user_type, status, created_at
            FROM users WHERE id = %s
        ''', (user_id,))
        
        user = cursor.fetchone()
        return dict(user) if user else None
    finally:
        return_db(conn)

# ==================== 配额管理相关 ====================

def get_user_quota(user_id):
    """
    获取用户配额信息
    返回用户当前可用的资源配额
    """
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # 获取基础配额
        cursor.execute('''
            SELECT * FROM user_quotas WHERE user_id = %s
        ''', (user_id,))
        
        quota = cursor.fetchone()
        
        if not quota:
            # 如果没有配额记录，创建默认配额
            reset_date = int((datetime.now() + timedelta(days=30)).timestamp())
            cursor.execute('''
                INSERT INTO user_quotas 
                (user_id, free_interviews_remaining, tts_quota_minutes, ai_analysis_quota, reset_date)
                VALUES (%s, 3, 10, 5, %s)
            ''', (user_id, reset_date))
            conn.commit()
            
            cursor.execute('SELECT * FROM user_quotas WHERE user_id = %s', (user_id,))
            quota = cursor.fetchone()
        
        quota_dict = dict(quota)
        
        # 获取有效的订阅配额
        current_time = int(time.time())
        cursor.execute('''
            SELECT interviews_remaining, tts_minutes_remaining, ai_analysis_remaining,
                   end_date, plan_id
            FROM user_subscriptions
            WHERE user_id = %s AND status = 1 AND end_date > %s
            ORDER BY end_date DESC
        ''', (user_id, current_time))
        
        subscriptions = [dict(row) for row in cursor.fetchall()]  # dict 行已支持 .get，dict() 只是浅拷贝兜底

        # 汇总配额
        total_interviews = quota_dict.get('free_interviews_remaining', 3)
        total_tts = quota_dict.get('tts_quota_minutes', 10)
        total_ai = quota_dict.get('ai_analysis_quota', 5)
        
        subscription_info = []
        for sub in subscriptions:
            total_interviews += sub.get('interviews_remaining', 0)
            total_tts += sub.get('tts_minutes_remaining', 0)
            total_ai += sub.get('ai_analysis_remaining', 0)
            subscription_info.append({
                'plan_id': sub.get('plan_id', 0),
                'end_date': sub.get('end_date', 0),
                'interviews': sub.get('interviews_remaining', 0),
                'tts_minutes': sub.get('tts_minutes_remaining', 0),
                'ai_analysis': sub.get('ai_analysis_remaining', 0)
            })
        
        return {
            'free_quota': {
                'interviews': quota_dict.get('free_interviews_remaining', 3),
                'tts_minutes': quota_dict.get('tts_quota_minutes', 10),
                'ai_analysis': quota_dict.get('ai_analysis_quota', 5)
            },
            'used': {
                'interviews': quota_dict.get('total_interviews_used', 0),
                'tts_minutes': quota_dict.get('tts_used_minutes', 0),
                'ai_analysis': quota_dict.get('ai_analysis_used', 0)
            },
            'total_available': {
                'interviews': total_interviews,
                'tts_minutes': total_tts,
                'ai_analysis': total_ai
            },
            'subscriptions': subscription_info,
            'reset_date': quota_dict.get('reset_date', 0)
        }
        
    finally:
        return_db(conn)

def check_quota(user_id, resource_type):
    """
    检查用户是否有足够的配额
    resource_type: 'interview', 'tts', 'ai_analysis'
    返回: (has_quota, quota_info)
    """
    quota = get_user_quota(user_id)
    
    if resource_type == 'interview':
        available = quota['total_available']['interviews']
        return available > 0, {'available': available, 'type': 'interview'}
    elif resource_type == 'tts':
        available = quota['total_available']['tts_minutes']
        return available > 0, {'available': available, 'type': 'tts'}
    elif resource_type == 'ai_analysis':
        available = quota['total_available']['ai_analysis']
        return available > 0, {'available': available, 'type': 'ai_analysis'}
    
    return False, None

def use_quota(user_id, resource_type, quantity=1, resource_id=None):
    """
    使用配额
    resource_type: 'interview', 'tts', 'ai_analysis'
    quantity: 使用量（次数或分钟数）
    返回: (success, message)
    """
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # 首先检查配额
        has_quota, quota_info = check_quota(user_id, resource_type)
        if not has_quota:
            return False, "配额不足，请购买套餐"
        
        current_time = int(time.time())
        
        # 优先使用免费配额
        cursor.execute('SELECT * FROM user_quotas WHERE user_id = %s', (user_id,))
        quota = cursor.fetchone()
        
        cost_type = 'free'
        
        if resource_type == 'interview':
            if quota['free_interviews_remaining'] >= quantity:
                # 使用免费配额
                cursor.execute('''
                    UPDATE user_quotas 
                    SET free_interviews_remaining = free_interviews_remaining - %s,
                        total_interviews_used = total_interviews_used + %s
                    WHERE user_id = %s
                ''', (quantity, quantity, user_id))
            else:
                # 使用订阅配额
                remaining = quantity
                cursor.execute('''
                    SELECT * FROM user_subscriptions 
                    WHERE user_id = %s AND status = 1 AND interviews_remaining > 0
                    ORDER BY end_date ASC
                ''', (user_id,))
                
                subscriptions = cursor.fetchall()
                for sub in subscriptions:
                    if remaining <= 0:
                        break
                    use_amount = min(remaining, sub['interviews_remaining'])
                    cursor.execute('''
                        UPDATE user_subscriptions 
                        SET interviews_remaining = interviews_remaining - %s,
                            updated_at = %s
                        WHERE id = %s
                    ''', (use_amount, current_time, sub['id']))
                    remaining -= use_amount
                    cost_type = 'subscription'
                
                if remaining > 0:
                    return False, "配额不足"
                
                # 更新总使用次数
                cursor.execute('''
                    UPDATE user_quotas 
                    SET total_interviews_used = total_interviews_used + %s
                    WHERE user_id = %s
                ''', (quantity, user_id))
        
        elif resource_type == 'tts':
            if quota['tts_quota_minutes'] >= quantity:
                cursor.execute('''
                    UPDATE user_quotas 
                    SET tts_quota_minutes = tts_quota_minutes - %s,
                        tts_used_minutes = tts_used_minutes + %s
                    WHERE user_id = %s
                ''', (quantity, quantity, user_id))
            else:
                remaining = quantity
                cursor.execute('''
                    SELECT * FROM user_subscriptions 
                    WHERE user_id = %s AND status = 1 AND tts_minutes_remaining > 0
                    ORDER BY end_date ASC
                ''', (user_id,))
                
                subscriptions = cursor.fetchall()
                for sub in subscriptions:
                    if remaining <= 0:
                        break
                    use_amount = min(remaining, sub['tts_minutes_remaining'])
                    cursor.execute('''
                        UPDATE user_subscriptions 
                        SET tts_minutes_remaining = tts_minutes_remaining - %s,
                            updated_at = %s
                        WHERE id = %s
                    ''', (use_amount, current_time, sub['id']))
                    remaining -= use_amount
                    cost_type = 'subscription'
                
                if remaining > 0:
                    return False, "配额不足"
                
                cursor.execute('''
                    UPDATE user_quotas 
                    SET tts_used_minutes = tts_used_minutes + %s
                    WHERE user_id = %s
                ''', (quantity, user_id))
        
        elif resource_type == 'ai_analysis':
            if quota['ai_analysis_quota'] >= quantity:
                cursor.execute('''
                    UPDATE user_quotas 
                    SET ai_analysis_quota = ai_analysis_quota - %s,
                        ai_analysis_used = ai_analysis_used + %s
                    WHERE user_id = %s
                ''', (quantity, quantity, user_id))
            else:
                remaining = quantity
                cursor.execute('''
                    SELECT * FROM user_subscriptions 
                    WHERE user_id = %s AND status = 1 AND ai_analysis_remaining > 0
                    ORDER BY end_date ASC
                ''', (user_id,))
                
                subscriptions = cursor.fetchall()
                for sub in subscriptions:
                    if remaining <= 0:
                        break
                    use_amount = min(remaining, sub['ai_analysis_remaining'])
                    cursor.execute('''
                        UPDATE user_subscriptions 
                        SET ai_analysis_remaining = ai_analysis_remaining - %s,
                            updated_at = %s
                        WHERE id = %s
                    ''', (use_amount, current_time, sub['id']))
                    remaining -= use_amount
                    cost_type = 'subscription'
                
                if remaining > 0:
                    return False, "配额不足"
                
                cursor.execute('''
                    UPDATE user_quotas 
                    SET ai_analysis_used = ai_analysis_used + %s
                    WHERE user_id = %s
                ''', (quantity, user_id))
        
        # 记录使用日志
        unit = 'count' if resource_type in ['interview', 'ai_analysis'] else 'minutes'
        cursor.execute('''
            INSERT INTO usage_logs 
            (user_id, resource_type, resource_id, quantity_used, quantity_unit, cost_type, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        ''', (user_id, resource_type, resource_id, quantity, unit, cost_type, current_time))
        
        conn.commit()
        return True, "配额使用成功"
        
    except Exception as e:
        conn.rollback()
        return False, f"使用配额失败: {str(e)}"
    finally:
        return_db(conn)

# ==================== 套餐管理相关 ====================

def get_pricing_plans(plan_type=None, only_active=True):
    """
    获取套餐列表
    """
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        query = "SELECT * FROM pricing_plans WHERE 1=1"
        params = []
        
        if plan_type:
            query += " AND plan_type = %s"
            params.append(plan_type)
        
        if only_active:
            query += " AND status = 1"
        
        query += " ORDER BY sort_order ASC"
        
        cursor.execute(query, params)
        plans = cursor.fetchall()
        
        return [dict(plan) for plan in plans]
        
    finally:
        return_db(conn)

def get_plan_by_id(plan_id):
    """根据ID获取套餐详情"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM pricing_plans WHERE id = %s", (plan_id,))
        plan = cursor.fetchone()
        return dict(plan) if plan else None
    finally:
        return_db(conn)

# ==================== 订单管理相关 ====================

def create_order(user_id, plan_id):
    """
    创建订单
    返回: (success, message, order_data)
    """
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # 获取套餐信息
        plan = get_plan_by_id(plan_id)
        if not plan:
            return False, "套餐不存在", None
        
        if plan['status'] != 1:
            return False, "该套餐已下架", None
        
        # 生成订单号
        order_no = f"INT{int(time.time())}{user_id}{secrets.randbelow(1000):03d}"
        
        # 计算有效期
        current_time = int(time.time())
        validity_start = current_time
        validity_end = current_time + (plan['validity_days'] * 24 * 60 * 60)
        
        cursor.execute('''
            INSERT INTO orders 
            (order_no, user_id, plan_id, plan_name, amount, validity_start, validity_end, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (order_no, user_id, plan_id, plan['name'], plan['price'], 
              validity_start, validity_end, current_time))
        # RETURNING id：psycopg3 没有 lastrowid，靠 RETURNING 拿自增 id（dict 行按列名取）
        order_id = cursor.fetchone()["id"]
        conn.commit()
        
        return True, "订单创建成功", {
            'order_id': order_id,
            'order_no': order_no,
            'amount': plan['price'],
            'plan_name': plan['name']
        }
        
    except Exception as e:
        conn.rollback()
        return False, f"创建订单失败: {str(e)}", None
    finally:
        return_db(conn)

def get_order_by_no(order_no):
    """根据订单号获取订单信息"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM orders WHERE order_no = %s", (order_no,))
        order = cursor.fetchone()
        return dict(order) if order else None
    finally:
        return_db(conn)

def update_order_status(order_no, pay_status, trade_no=None, total_amount=None):
    """只更新订单支付状态（支付宝异步通知/同步返回回调用）

    与 update_order_payment 的区别：本函数只改 orders 表的状态字段，
    不创建用户订阅（订阅激活走 mock/confirm 等明确入口）。
    total_amount 保留在签名里与回调数据对齐，但 orders 表没有对应列，暂不落库。

    Returns: (success, message)
    """
    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            UPDATE orders
            SET pay_status = %s, pay_trade_no = %s, pay_time = %s
            WHERE order_no = %s
        ''', (pay_status, trade_no, int(time.time()), order_no))
        conn.commit()
        # rowcount=0 说明订单号不存在
        if cursor.rowcount == 0:
            return False, "订单不存在"
        return True, "订单状态已更新"
    except Exception as e:
        conn.rollback()
        return False, f"更新订单状态失败: {str(e)}"
    finally:
        return_db(conn)

def update_order_payment(order_no, pay_method, pay_trade_no):
    """
    更新订单支付状态
    支付成功后调用，创建用户订阅
    """
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        current_time = int(time.time())
        
        # 更新订单状态
        cursor.execute('''
            UPDATE orders 
            SET pay_status = 1, pay_method = %s, pay_trade_no = %s, pay_time = %s
            WHERE order_no = %s
        ''', (pay_method, pay_trade_no, current_time, order_no))
        
        # 获取订单信息
        order = get_order_by_no(order_no)
        if not order:
            return False, "订单不存在"
        
        # 获取套餐信息
        plan = get_plan_by_id(order['plan_id'])
        if not plan:
            return False, "套餐不存在"
        
        # 创建或更新用户订阅
        cursor.execute('''
            INSERT INTO user_subscriptions 
            (user_id, plan_id, order_id, start_date, end_date, 
             interviews_remaining, tts_minutes_remaining, ai_analysis_remaining)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ''', (order['user_id'], order['plan_id'], order['id'], 
              order['validity_start'], order['validity_end'],
              plan['interviews_included'], plan['tts_minutes_included'], 
              plan['ai_analysis_included']))
        
        # 更新用户类型为付费用户，并把套餐面试次数加进 users.interview_quota
        # （个人版唯一配额列：大模型出题成功一场扣 1，见 question_service）
        cursor.execute('''
            UPDATE users
            SET user_type = 'premium',
                interview_quota = interview_quota + %s
            WHERE id = %s
        ''', (plan['interviews_included'] or 0, order['user_id']))
        
        conn.commit()
        return True, "支付成功，订阅已激活"
        
    except Exception as e:
        conn.rollback()
        return False, f"更新订单失败: {str(e)}"
    finally:
        return_db(conn)

def get_user_orders(user_id, limit=10):
    """获取用户订单历史"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT * FROM orders 
            WHERE user_id = %s 
            ORDER BY created_at DESC 
            LIMIT %s
        ''', (user_id, limit))
        
        orders = cursor.fetchall()
        return [dict(order) for order in orders]
        
    finally:
        return_db(conn)

# ==================== 支付配置相关 ====================

def get_payment_config(pay_method='alipay'):
    """获取支付配置"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM payment_configs WHERE pay_method = %s", (pay_method,))
        config = cursor.fetchone()
        return dict(config) if config else None
    finally:
        return_db(conn)

def save_payment_config(pay_method, app_id, private_key, public_key, 
                       alipay_public_key, notify_url, return_url, sandbox_mode=1):
    """保存支付配置"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        current_time = int(time.time())
        
        cursor.execute('''
            INSERT INTO payment_configs
            (pay_method, app_id, private_key, public_key, alipay_public_key,
             notify_url, return_url, sandbox_mode, status, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1, %s)
            ON CONFLICT (pay_method) DO UPDATE SET
                app_id = EXCLUDED.app_id, private_key = EXCLUDED.private_key,
                public_key = EXCLUDED.public_key, alipay_public_key = EXCLUDED.alipay_public_key,
                notify_url = EXCLUDED.notify_url, return_url = EXCLUDED.return_url,
                sandbox_mode = EXCLUDED.sandbox_mode, status = EXCLUDED.status,
                updated_at = EXCLUDED.updated_at
        ''', (pay_method, app_id, private_key, public_key, alipay_public_key,
              notify_url, return_url, sandbox_mode, current_time))
        
        conn.commit()
        return True, "配置保存成功"
        
    except Exception as e:
        conn.rollback()
        return False, f"保存配置失败: {str(e)}"
    finally:
        return_db(conn)
