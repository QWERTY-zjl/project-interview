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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 统一把根日志器上所有 handler 抬到 INFO，确保 api/ 子模块各自 logger 的 INFO 日志能输出
for handler in logging.root.handlers:
    handler.setLevel(logging.INFO)

# 先导入系统级别的pydantic，避免与lib目录下的版本冲突：
# 在 FastAPI import 前抢先加载，防止 lib/ 下另一份 pydantic 混用；没装则静默跳过
try:
    import pydantic
    import pydantic_core
    logger.info(f'使用系统pydantic: {pydantic.__version__}, pydantic-core: {pydantic_core.__version__}')
except ImportError:
    pass

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse, RedirectResponse
import uvicorn

from app.config.config import DASHSCOPE_API_KEY  # 大模型/TTS 调用凭证，config.py 从 .env 读取
# init_db：启动时执行建表脚本（幂等，表已存在就跳过）；close_all_connections：退出时关闭全部连接
from app.db.db import init_db, close_all_connections
# 各 api/ 文件的 router 实例同名，import 时用 as 别名区分模块
from app.api.resume_api import router as resume_router
from app.api.interview_api import router as interview_router
from app.api.report_api import router as report_router
from app.api.tts_api import router as tts_router
from app.api.expression_api import router as expression_router
from app.api.auth_api import router as auth_router
from app.api.pricing_api import router as pricing_router
from app.api.order_api import router as order_router
from app.api.payment_api import router as payment_router, quota_router

# 三个监控线程的运行开关：置 False 后各线程 while 循环退出（见 lifespan 关闭阶段）
server_running = False


# lifespan：yield 之前是启动逻辑，yield 之后是关闭清理逻辑（FastAPI 生命周期约定）
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理
    """
    global server_running
    
    logger.info("正在启动应用...")
    server_running = True
    
    try:
        logger.info("正在初始化数据库...")
        init_db()
        logger.info("数据库初始化完成")
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")
        # 原样再抛出让 uvicorn 启动失败：数据库没准备好时宁可退出，也别带病运行
        raise
    
    # daemon 守护线程：主进程退出时直接终止，不阻塞退出流程
    monitor_thread = threading.Thread(target=monitor_threads, name="monitor_threads", daemon=True)
    monitor_thread.start()
    logger.info("线程监控已启动")
    
    app_monitor_thread = threading.Thread(target=monitor_app, name="app_monitor", daemon=True)
    app_monitor_thread.start()
    logger.info("应用监控已启动")
    
    try:
        resource_monitor_thread = threading.Thread(target=monitor_resources, name="resource_monitor", daemon=True)
        resource_monitor_thread.start()
        logger.info("资源监控已启动")
    except ImportError:
        # psutil 是可选依赖（看系统资源用的），没装也不影响主业务
        logger.warning("psutil 未安装，跳过资源监控")
    
    yield
    
    logger.info("正在关闭应用...")
    server_running = False  # 置 False → 三个监控线程的 while 循环退出

    # 等待监控线程收尾
    time.sleep(2)
    
    try:
        close_all_connections()
        logger.info("所有数据库连接已关闭")
    except Exception as e:
        logger.error(f"关闭数据库连接时出错: {e}")
    
    logger.info("应用关闭完成")


# 三个监控函数结构相同；日志用 DEBUG 级别，正常运行不输出（有意为之，调 DEBUG 可见）
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


def monitor_app():
    """监控FastAPI应用的状态"""
    import time
    while server_running:
        try:
            logger.debug("FastAPI应用运行中...")
            time.sleep(10)  # 每10秒检查一次
        except Exception as e:
            logger.error(f"应用监控出错: {e}")


def monitor_resources():
    """监控系统资源使用情况"""
    import psutil
    import time
    while server_running:
        try:
            cpu_percent = psutil.cpu_percent()
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            logger.debug(f"系统资源使用情况: CPU: {cpu_percent}%, 内存: {memory.percent}%, 磁盘: {disk.percent}%")
            time.sleep(60)  # 每分钟检查一次
        except Exception as e:
            logger.error(f"资源监控出错: {e}")


# ==================== FastAPI应用初始化 ====================
logger.info("开始初始化FastAPI应用...")

# 创建 FastAPI 应用实例（路由/中间件/异常处理都挂在它身上）
app = FastAPI(
    title="智能招聘面试模拟系统",
    description="提供面试模拟、简历分析、语音合成等功能",
    version="1.0.0",
    lifespan=lifespan,
    # docs_url=None：默认 /docs 页面从 jsdelivr CDN 拉资源，代理/断网时白屏；
    # 改用下方自定义 /docs 路由做本地化 swagger-ui（资源在 static/swagger-ui/）
    docs_url=None
)

logger.info("FastAPI应用实例创建成功")

# 启用跨域资源共享（CORS），允许前端跨域访问API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许任何来源；生产环境应改为具体域名
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

# ==================== API文档（本地化 swagger-ui） ====================
# 默认 /docs 从 cdn.jsdelivr.net 拉 swagger-ui 资源，代理/断网时白屏；
# 这里改用 get_swagger_ui_html 生成同款页面，资源指向项目内 static/swagger-ui/（离线可用）
from fastapi.openapi.docs import get_swagger_ui_html

# include_in_schema=False：不让 /docs 自己出现在 openapi.json 里
@app.get("/docs", include_in_schema=False)
async def custom_docs():
    """接口文档页面（swagger-ui 资源本地化版本）"""
    # JS/CSS 指向本机 /static/...；openapi_url 指向 /openapi.json 渲染接口列表
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - 接口文档",
        oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
        swagger_js_url="/static/swagger-ui/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger-ui/swagger-ui.css",
    )

# ==================== 静态文件服务 ====================
# {path:path} 路径转换器：一个参数吃进整段子路径（含 /，如 swagger-ui/swagger-ui.css）
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
    """根路径：302 跳转到 /static/admin.html（工作台）

    用重定向而非直接返回文件：页面 URL 落在 /static/ 下时，页面内的相对路径
    资源引用（js/xxx.js、css/xxx.css）才能正确解析到 /static/js/... 等路由；
    生产环境由 nginx 直接以静态目录为根，不经过此路由。
    """
    return RedirectResponse("/static/admin.html", status_code=302)

# ==================== 路由注册（APIRouter 模式） ====================
# 各业务模块在自己的文件里用 APIRouter 声明路由（带中文 tags 和 summary），
# 这里统一挂载到 app 上，注册逻辑不再散落在 main.py
app.include_router(resume_router)        # 简历
app.include_router(interview_router)     # 面试流程
app.include_router(report_router)        # 面试报告
app.include_router(tts_router)           # 语音合成
app.include_router(expression_router)    # 表情分析
app.include_router(auth_router)          # 用户认证
app.include_router(pricing_router)       # 套餐定价
app.include_router(order_router)         # 订单
app.include_router(payment_router)       # 支付
app.include_router(quota_router)         # 配额

# ==================== 应用错误处理 ====================
# 兜底异常处理器：接口里没被接住的异常统一转成 500 响应，避免 uvicorn 默认错误页
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理器"""
    logger.error(f"全局异常: {exc}")
    import traceback
    traceback.print_exc()

    # 返回 500 JSON 响应。注意：str(exc) 会把内部异常原文暴露给客户端，
    # 开发期方便排错；正式对外时建议去掉 message，防止泄露实现细节
    return JSONResponse(
        status_code=500,
        content={"error": "内部服务器错误", "message": str(exc)}
    )


if __name__ == '__main__':
    logger.info("启动FastAPI服务器...")
    logger.info("服务器启动在 http://0.0.0.0:10009")

    # 端口 10009 与原 Flask 版一致，nginx/Docker 配置无需改动
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",  # 监听所有网卡，局域网可访问
        port=10009,
        reload=True,
        workers=1        # 单进程。已迁 PostgreSQL（支持并发写，不再有 SQLite 单写者锁库问题）；个人版保持单进程简单可靠
    )
