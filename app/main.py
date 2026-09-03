"""
智能招聘面试模拟系统 - FastAPI主服务器模块
============================================
本文件包含FastAPI Web服务器的核心功能：
- 岗位、候选人、面试管理API
- 语音识别（ASR）和语音合成（TTS）
- 表情分析功能
- 付费功能集成（支付宝）
- 面试问题生成和报告生成
"""

import sys
import os
import logging
import time
import threading
from contextlib import asynccontextmanager

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# 确保所有子模块的日志都被捕获
for handler in logging.root.handlers:
    handler.setLevel(logging.INFO)

# 先导入系统级别的pydantic，避免与lib目录下的版本冲突
try:
    import pydantic
    import pydantic_core
    logger.info(f'使用系统pydantic: {pydantic.__version__}, pydantic-core: {pydantic_core.__version__}')
except ImportError:
    pass

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
import uvicorn

# 导入配置和模块
from app.config.config import DASHSCOPE_API_KEY
from app.db.db import init_db, close_all_connections
from app.api.position_api import get_positions, create_position, update_position, delete_position
from app.api.resume_api import upload_resume
from app.api.interview_api import get_interview_info, get_next_question, submit_text_answer, toggle_voice_reading, set_interview_voice
from app.api.tts_api import get_tts_voices, synthesize_tts
from app.api.expression_api import recognize_expression_api, analyze_expression_api, save_interview_expression, get_expression_report
from app.api.auth_api import api_register, api_login, api_get_quota
from app.api.pricing_api import api_get_plans, api_get_plan_detail
from app.api.order_api import api_create_order, api_pay_order, api_check_order_status, api_get_user_orders
from app.api.payment_api import alipay_notify, alipay_return

# 全局变量
server_running = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理
    """
    global server_running
    
    # 启动时
    logger.info("正在启动应用...")
    server_running = True
    
    # 初始化数据库
    try:
        logger.info("正在初始化数据库...")
        init_db()
        logger.info("数据库初始化完成")
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")
        raise
    
    # 启动线程监控
    monitor_thread = threading.Thread(target=monitor_threads, name="monitor_threads", daemon=True)
    monitor_thread.start()
    logger.info("线程监控已启动")
    
    # 启动应用监控
    app_monitor_thread = threading.Thread(target=monitor_app, name="app_monitor", daemon=True)
    app_monitor_thread.start()
    logger.info("应用监控已启动")
    
    # 启动资源监控
    try:
        resource_monitor_thread = threading.Thread(target=monitor_resources, name="resource_monitor", daemon=True)
        resource_monitor_thread.start()
        logger.info("资源监控已启动")
    except ImportError:
        logger.warning("psutil 未安装，跳过资源监控")
    
    yield
    
    # 关闭时
    logger.info("正在关闭应用...")
    server_running = False
    
    # 等待监控线程结束
    time.sleep(2)
    
    # 关闭所有数据库连接
    try:
        close_all_connections()
        logger.info("所有数据库连接已关闭")
    except Exception as e:
        logger.error(f"关闭数据库连接时出错: {e}")
    
    logger.info("应用关闭完成")


# 线程监控函数
def monitor_threads():
    """监控所有线程的状态"""
    import threading
    import time
    while server_running:
        try:
            threads = threading.enumerate()
            logger.debug(f"当前线程数: {len(threads)}")
            for thread in threads:
                logger.debug(f"  - {thread.name} (Daemon: {thread.daemon}, Alive: {thread.is_alive()})")
            time.sleep(30)  # 每30秒检查一次
        except Exception as e:
            logger.error(f"线程监控出错: {e}")


# 监控FastAPI应用状态的函数
def monitor_app():
    """监控FastAPI应用的状态"""
    import time
    while server_running:
        try:
            logger.debug("FastAPI应用运行中...")
            time.sleep(10)  # 每10秒检查一次
        except Exception as e:
            logger.error(f"应用监控出错: {e}")


# 监控系统资源的函数
def monitor_resources():
    """监控系统资源使用情况"""
    import psutil
    import time
    while server_running:
        try:
            # 获取系统资源使用情况
            cpu_percent = psutil.cpu_percent()
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            logger.debug(f"系统资源使用情况: CPU: {cpu_percent}%, 内存: {memory.percent}%, 磁盘: {disk.percent}%")
            time.sleep(60)  # 每分钟检查一次
        except Exception as e:
            logger.error(f"资源监控出错: {e}")


# ==================== FastAPI应用初始化 ====================
logger.info("开始初始化FastAPI应用...")

# 创建FastAPI应用实例，配置静态文件目录
app = FastAPI(
    title="智能招聘面试模拟系统",
    description="提供面试模拟、简历分析、语音合成等功能",
    version="1.0.0",
    lifespan=lifespan
)

logger.info("FastAPI应用实例创建成功")

# 启用跨域资源共享（CORS），允许前端跨域访问API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 在生产环境中应该设置具体的域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger.info("CORS配置成功")

# ==================== API密钥配置 ====================
# 从环境变量获取阿里云DashScope API密钥（用于语音识别和合成）
if DASHSCOPE_API_KEY:
    logger.info('DASHSCOPE_API_KEY 已加载')
else:
    logger.warning('DASHSCOPE_API_KEY 未配置!')

# ==================== 静态文件服务 ====================
@app.get("/static/{path:path}")
async def serve_static(path: str):
    """提供静态文件服务"""
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    file_path = os.path.join(static_dir, path)
    
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return FileResponse(file_path)
    else:
        raise HTTPException(status_code=404, detail="文件不存在")

# ==================== 根路径 ====================
@app.get("/")
async def root():
    """根路径"""
    return {"message": "智能招聘面试模拟系统 API", "version": "1.0.0"}

# ==================== 岗位管理API ====================
app.get("/api/positions")(get_positions)
app.post("/api/positions")(create_position)
app.put("/api/positions/{id}")(update_position)
app.delete("/api/positions/{id}")(delete_position)

# ==================== 简历上传API ====================
app.post("/api/resume/upload")(upload_resume)

# ==================== 面试管理API ====================
app.get("/api/interview/{token}/info")(get_interview_info)
app.get("/api/interview/{token}/get_question")(get_next_question)
app.post("/api/interview/{token}/submit_text_answer")(submit_text_answer)
app.post("/api/interview/{token}/toggle_voice_reading")(toggle_voice_reading)
app.post("/api/interview/{token}/set_voice")(set_interview_voice)

# ==================== TTS API ====================
app.get("/api/tts/voices")(get_tts_voices)
app.post("/api/tts/synthesize")(synthesize_tts)

# ==================== 表情分析API ====================
app.post("/api/expression/recognize")(recognize_expression_api)
app.post("/api/expression/analyze")(analyze_expression_api)
app.post("/api/interview/{token}/expression")(save_interview_expression)
app.get("/api/interview/{token}/expression_report")(get_expression_report)

# ==================== 认证API ====================
app.post("/api/auth/register")(api_register)
app.post("/api/auth/login")(api_login)
app.get("/api/user/quota")(api_get_quota)

# ==================== 套餐管理API ====================
app.get("/api/pricing/plans")(api_get_plans)
app.get("/api/pricing/plans/{plan_id}")(api_get_plan_detail)

# ==================== 订单管理API ====================
app.post("/api/orders/create")(api_create_order)
app.post("/api/orders/pay")(api_pay_order)
app.get("/api/orders/{order_no}/status")(api_check_order_status)
app.get("/api/orders/user/{user_id}")(api_get_user_orders)

# ==================== 支付宝回调API ====================
app.post("/api/payment/alipay/notify")(alipay_notify)
app.get("/api/payment/alipay/return")(alipay_return)

# ==================== 应用错误处理 ====================
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理器"""
    logger.error(f"全局异常: {exc}")
    import traceback
    traceback.print_exc()
    
    return JSONResponse(
        status_code=500,
        content={"error": "内部服务器错误", "message": str(exc)}
    )


if __name__ == '__main__':
    logger.info("启动FastAPI服务器...")
    logger.info("服务器启动在 http://0.0.0.0:10003")
    
    # 启动uvicorn服务器
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=10003,
        reload=False,
        workers=1
    )
