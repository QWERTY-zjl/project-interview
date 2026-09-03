"""
支付宝支付模块
支持网页支付和扫码支付
"""
import json
import time
import urllib.parse
import base64
from datetime import datetime

# 支付宝SDK（需要安装: pip install alipay-sdk-python）
try:
    from alipay import AliPay
    ALIPAY_SDK_AVAILABLE = True
except ImportError:
    ALIPAY_SDK_AVAILABLE = False
    print("[WARNING] 支付宝SDK未安装，支付功能将使用模拟模式")
    print("[INFO] 如需真实支付，请运行: pip install alipay-sdk-python")

class AlipayManager:
    """支付宝管理器"""
    
    def __init__(self, app_id, private_key, alipay_public_key, 
                 notify_url=None, return_url=None, sandbox=True):
        """
        初始化支付宝配置
        
        参数:
            app_id: 支付宝应用ID
            private_key: 应用私钥（RSA2格式）
            alipay_public_key: 支付宝公钥
            notify_url: 异步通知URL
            return_url: 同步返回URL
            sandbox: 是否使用沙箱环境
        """
        self.app_id = app_id
        self.sandbox = sandbox
        
        if ALIPAY_SDK_AVAILABLE and app_id and private_key and alipay_public_key:
            try:
                self.alipay = AliPay(
                    appid=app_id,
                    app_notify_url=notify_url,
                    app_private_key_string=private_key,
                    alipay_public_key_string=alipay_public_key,
                    sign_type="RSA2",
                    debug=sandbox
                )
                self.enabled = True
            except Exception as e:
                print(f"[ERROR] 支付宝初始化失败: {e}")
                self.enabled = False
                self.alipay = None
        else:
            self.enabled = False
            self.alipay = None
    
    def create_web_payment(self, order_no, amount, subject, body=""):
        """
        创建网页支付（用于PC网站支付）
        
        返回: {
            'success': True/False,
            'payment_url': 支付页面URL,
            'order_no': 订单号
        }
        """
        if not self.enabled:
            # 模拟支付模式
            return {
                'success': True,
                'payment_url': f'/mock_payment?order_no={order_no}&amount={amount}',
                'order_no': order_no,
                'mock': True
            }
        
        try:
            # 调用支付宝接口生成支付表单
            order_string = self.alipay.api_alipay_trade_page_pay(
                out_trade_no=order_no,
                total_amount=str(amount),
                subject=subject,
                body=body,
                return_url=self.return_url,
                notify_url=self.notify_url
            )
            
            # 构建支付URL
            if self.sandbox:
                gateway = "https://openapi.alipaydev.com/gateway.do"
            else:
                gateway = "https://openapi.alipay.com/gateway.do"
            
            payment_url = f"{gateway}?{order_string}"
            
            return {
                'success': True,
                'payment_url': payment_url,
                'order_no': order_no
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def create_qr_payment(self, order_no, amount, subject, body=""):
        """
        创建扫码支付（生成二维码让用户扫码）
        
        返回: {
            'success': True/False,
            'qr_code': 二维码内容（用于生成二维码图片）,
            'order_no': 订单号
        }
        """
        if not self.enabled:
            return {
                'success': False,
                'error': '支付宝SDK未配置'
            }
        
        try:
            result = self.alipay.api_alipay_trade_precreate(
                out_trade_no=order_no,
                total_amount=str(amount),
                subject=subject,
                body=body,
                notify_url=self.notify_url
            )
            
            if result.get("code") == "10000":
                return {
                    'success': True,
                    'qr_code': result.get('qr_code'),
                    'order_no': order_no
                }
            else:
                return {
                    'success': False,
                    'error': result.get('msg', '创建支付失败')
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def query_order(self, order_no):
        """
        查询订单支付状态
        
        返回: {
            'success': True/False,
            'paid': True/False,
            'trade_no': 支付宝交易号,
            'amount': 支付金额,
            'pay_time': 支付时间
        }
        """
        if not self.enabled:
            return {
                'success': False,
                'error': '支付宝SDK未配置'
            }
        
        try:
            result = self.alipay.api_alipay_trade_query(out_trade_no=order_no)
            
            if result.get("code") == "10000":
                trade_status = result.get('trade_status')
                
                if trade_status == "TRADE_SUCCESS":
                    return {
                        'success': True,
                        'paid': True,
                        'trade_no': result.get('trade_no'),
                        'amount': result.get('total_amount'),
                        'pay_time': result.get('send_pay_date')
                    }
                elif trade_status in ["WAIT_BUYER_PAY", "TRADE_CLOSED"]:
                    return {
                        'success': True,
                        'paid': False,
                        'status': trade_status
                    }
                else:
                    return {
                        'success': True,
                        'paid': False,
                        'status': trade_status
                    }
            else:
                return {
                    'success': False,
                    'error': result.get('msg', '查询失败')
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def verify_notify(self, data, signature):
        """
        验证支付宝异步通知的签名
        
        参数:
            data: 通知数据（字典）
            signature: 签名
            
        返回: True/False
        """
        if not self.enabled:
            return False
        
        try:
            return self.alipay.verify(data, signature)
        except Exception as e:
            print(f"[ERROR] 签名验证失败: {e}")
            return False
    
    def close_order(self, order_no):
        """
        关闭未支付订单
        
        返回: {
            'success': True/False
        }
        """
        if not self.enabled:
            return {'success': False, 'error': '支付宝SDK未配置'}
        
        try:
            result = self.alipay.api_alipay_trade_close(out_trade_no=order_no)
            
            if result.get("code") == "10000":
                return {'success': True}
            else:
                return {
                    'success': False,
                    'error': result.get('msg', '关闭订单失败')
                }
                
        except Exception as e:
            return {'success': False, 'error': str(e)}


# ==================== 支付辅助函数 ====================

def format_amount(amount):
    """格式化金额，保留2位小数"""
    return f"{float(amount):.2f}"

def generate_order_subject(plan_name):
    """生成订单标题"""
    return f"AI面试系统 - {plan_name}"

def get_payment_status_text(status_code):
    """获取支付状态文本"""
    status_map = {
        0: '未支付',
        1: '已支付',
        2: '已取消',
        3: '已退款'
    }
    return status_map.get(status_code, '未知状态')


# ==================== 模拟支付（开发测试用） ====================

class MockPayment:
    """模拟支付，用于开发和测试"""
    
    def __init__(self):
        self.payments = {}
    
    def create_payment(self, order_no, amount, subject):
        """创建模拟支付"""
        self.payments[order_no] = {
            'order_no': order_no,
            'amount': amount,
            'subject': subject,
            'status': 'pending',
            'created_at': time.time()
        }
        
        return {
            'success': True,
            'payment_url': f'/mock_payment_page?order_no={order_no}',
            'order_no': order_no,
            'mock': True
        }
    
    def confirm_payment(self, order_no):
        """确认支付（模拟用户完成支付）"""
        if order_no in self.payments:
            self.payments[order_no]['status'] = 'paid'
            self.payments[order_no]['paid_at'] = time.time()
            self.payments[order_no]['trade_no'] = f'MOCK{int(time.time())}'
            return True
        return False
    
    def query_payment(self, order_no):
        """查询支付状态"""
        payment = self.payments.get(order_no)
        if not payment:
            return {'success': False, 'error': '订单不存在'}
        
        return {
            'success': True,
            'paid': payment['status'] == 'paid',
            'trade_no': payment.get('trade_no'),
            'amount': payment['amount']
        }

# 全局模拟支付实例
mock_payment = MockPayment()
