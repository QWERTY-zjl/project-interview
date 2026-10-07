"""
智能招聘面试模拟系统 - FastAPI主服务器模块
============================================
本文件包含FastAPI Web服务器的核心功能：
- 岗位、候选人、面试管理API
- 语音识别（ASR）和语音合成（TTS）
- 表情分析功能
- 付费功能集成（支付宝）
- 面试问题生成和报告生成

版权声明：仅供学习参考，禁止商用/二次分发/他用本代码申请软著
"""

# ---- 标准库导入 ----
# import 模块名：导入整个模块，之后用"模块名.函数"的方式调用
import sys     # 解释器相关工具（本文件当前未实际用到，保留备用）
import os      # 操作系统接口：路径拼接 os.path.join、判断文件存在 os.path.exists 等
import logging # 标准日志库，print 的"专业版"：带时间戳、级别、可统一开关
import time    # 时间工具：下面用 time.sleep(秒) 让监控线程周期性休眠
import threading  # 多线程库：下面用它启动后台监控线程
# from 模块 import 具体名字：只导入需要的那个东西，之后直接写名字即可
# asynccontextmanager：装饰器工具，把"带 yield 的 async 函数"变成异步上下文管理器，
# FastAPI 靠它管理应用的启动/关闭流程（见下面 lifespan 函数）
from contextlib import asynccontextmanager

# 配置日志：basicConfig 是"全局默认配置"，只在第一次调用时生效
logging.basicConfig(
    level=logging.INFO,   # 只输出 INFO 及以上级别（DEBUG 级别的日志会被过滤掉，见下面监控函数）
    # format 里的 %(名字)s 是占位符语法，运行时分别替换成：时间 - 日志器名 - 级别 - 消息内容
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# getLogger(名字)：领取一个"日志器"；__name__ 是 Python 内置变量，在本文件里它的值就是 "app.main"
# 用模块名当日志器名，日志里就能看出这条消息是哪个文件打的
logger = logging.getLogger(__name__)

# 遍历根日志器上挂的所有处理器（handler = 日志的输出通道，默认是控制台），统一抬到 INFO 级别，
# 确保 api/ 目录下各子模块用各自 logger 打的 INFO 日志也能正常输出
for handler in logging.root.handlers:
    handler.setLevel(logging.INFO)

# 先导入系统级别的pydantic，避免与lib目录下的版本冲突
# 语法说明：try/except = "试一下，出这个错就走另一条路"。
#   在 FastAPI 正式 import 之前先手动 import pydantic（FastAPI 的底层校验库），
#   让它抢先加载进内存，之后 FastAPI 再 import 时拿到的就是同一份，
#   防止项目 lib/ 目录下存在另一份 pydantic 时两份混用出诡异冲突。
#   except ImportError + pass = 万一没装也不报错，静默跳过（后面 FastAPI 导入时自然会报出真正的错）
try:
    import pydantic
    import pydantic_core
    # f'...{变量}...' 是 f-string 语法：花括号里可以直接放变量/表达式，运行时拼接成字符串
    logger.info(f'使用系统pydantic: {pydantic.__version__}, pydantic-core: {pydantic_core.__version__}')
except ImportError:
    pass

# ---- 第三方库导入（都装在项目的 venv 里）----
# 一行导入多个名字用逗号隔开：
#   FastAPI：框架主类，本文件用它创建 app 实例
#   Request：请求对象（能拿到客户端 IP、请求头等原始信息）
#   UploadFile/File/Form：上传文件和表单参数的声明工具（本文件没直接用，api/ 目录的接口文件在用）
#   HTTPException：手动抛 HTTP 错误的异常类，raise 它 = 返回错误响应（如 404），见下面静态文件接口
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
# CORSMiddleware：处理浏览器跨域请求的中间件（原理见下方 CORS 配置处）
from fastapi.middleware.cors import CORSMiddleware
# 三种现成的"响应类型"：
#   JSONResponse：返回 JSON 数据；FileResponse：返回磁盘上的文件（html/图片/PDF）；
#   StreamingResponse：流式返回大块数据（本文件未用到，api/ 里的音频接口在用）
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
# uvicorn：ASGI 服务器——真正监听 10009 端口、接收 HTTP 请求的程序。
# 分工：FastAPI 负责"处理请求"，uvicorn 负责"接请求"，两者配合才能对外提供服务
import uvicorn

# 导入配置和模块
# from app.config.config import DASHSCOPE_API_KEY：
#   app.config.config 表示 app/ 目录下 config/ 目录里的 config.py 文件（Python 用点号表示目录层级），
#   这个密钥在 config.py 里从 .env 读取，是所有大模型/TTS 调用的凭证
from app.config.config import DASHSCOPE_API_KEY
# init_db：启动时执行建表脚本（脚本写成幂等的，表已存在就跳过）；close_all_connections：退出时关闭全部连接
from app.db.db import init_db, close_all_connections
# 每个 api/ 文件里都创建了一个 APIRouter 实例（变量名固定叫 router）。
# "import router as resume_router" 里的 as 是起别名：10 个文件都叫 router，直接 import 会互相覆盖，
# 统一改成 文件名_router 后，下面 include_router 时一眼能看出挂载的是哪个模块
from app.api.resume_api import router as resume_router
from app.api.interview_api import router as interview_router
from app.api.report_api import router as report_router
from app.api.tts_api import router as tts_router
from app.api.expression_api import router as expression_router
from app.api.auth_api import router as auth_router
from app.api.pricing_api import router as pricing_router
from app.api.order_api import router as order_router
from app.api.payment_api import router as payment_router, quota_router

# 全局变量：模块级变量，本文件里任何函数都能读到它。
# 它是三个监控线程的"运行开关"——线程函数里 while server_running 反复循环，
# 把它置为 False 后循环条件不成立，线程自然退出（见 lifespan 的关闭阶段）
server_running = False


# @asynccontextmanager（@ 符号 = "把下面的函数套用这个装饰器"）：
# 把这个"带 yield 的 async 函数"包装成异步上下文管理器。FastAPI 约定：把它传给
# FastAPI(lifespan=...) 后——
#   应用启动前 → 执行 yield 之前的代码（准备阶段）
#   到 yield 处暂停，应用开始对外服务（uvicorn 在此期间持续接请求）
#   应用关闭时 → 恢复执行，走 yield 之后的代码（清理阶段）
# 于是同一个函数天然分出"启动逻辑"和"关闭逻辑"两段
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理
    """
    # global 声明：函数里想"修改"全局变量（而不是新建一个同名局部变量）必须先写这句
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
        # 单独一行的 raise = 把刚捕获的异常原样再抛出去，uvicorn 会启动失败并打印完整堆栈。
        # 启动阶段宁可退出来，也别"带病运行"——数据库没准备好，后面所有请求都会挂
        raise
    
    # 启动线程监控
    # threading.Thread(target=函数, name=线程名, daemon=True)：创建线程对象——
    #   target 指定这个线程要执行的函数，name 方便日志辨认，
    #   daemon=True 表示"守护线程"：主进程退出时守护线程会被直接终止，不阻塞退出流程
    #   （监控线程是辅助角色，用守护模式正合适）
    # 注意：只是创建对象还不会跑，调用 .start() 才真正开始执行
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
        # psutil 是可选依赖（看系统资源用的），没装也不影响主业务，警告一声继续跑
        logger.warning("psutil 未安装，跳过资源监控")
    
    # yield：上面是启动逻辑，执行到这里就"暂停"——应用开始对外服务，
    # 一直挂着，直到进程收到关闭信号（比如 Ctrl+C），才继续往下走
    yield
    
    # 关闭时（yield 之后 = 清理逻辑）
    logger.info("正在关闭应用...")
    server_running = False  # 置 False → 三个监控线程的 while 循环条件失效，各自退出

    # 等待监控线程结束：挂起 2 秒给它们收尾的时间
    time.sleep(2)
    
    # 关闭所有数据库连接
    try:
        close_all_connections()
        logger.info("所有数据库连接已关闭")
    except Exception as e:
        logger.error(f"关闭数据库连接时出错: {e}")
    
    logger.info("应用关闭完成")


# 线程监控函数（下面三个监控函数结构相同：while 开关 → 干活 → sleep 休眠 → 循环）
# 注意：它们打的是 logger.debug，而日志级别是 INFO（见开头 basicConfig），
# 所以正常运行时看不到这些日志——这是有意的，想看时把级别调成 DEBUG 才输出
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

# 创建 FastAPI 应用实例：整个 Web 服务的核心对象，路由/中间件/异常处理全都挂在它身上
# title/description/version 三项会显示在 /docs 接口文档页面的抬头
app = FastAPI(
    title="智能招聘面试模拟系统",
    description="提供面试模拟、简历分析、语音合成等功能",
    version="1.0.0",
    # lifespan=：把上面定义的生命周期函数交给 FastAPI，启动/关闭逻辑由它统一调度
    lifespan=lifespan,
    # docs_url=None：关闭默认的 /docs 页面。默认实现从 jsdelivr CDN 加载界面资源，
    # 代理/断网时白屏；改用本地化 swagger-ui（见下方自定义 /docs 路由），资源文件在 static/swagger-ui/
    docs_url=None
)

logger.info("FastAPI应用实例创建成功")

# 启用跨域资源共享（CORS），允许前端跨域访问API
# 背景知识：浏览器的"同源策略"默认禁止 A 网站的页面用 JS 去调 B 网站的接口（安全机制）。
# CORS 是官方放行机制：服务器在响应头里声明"我允许某某来源访问"，浏览器看到声明才放行。
# add_middleware(中间件类, 参数...)：给 app 套一层中间件，每个请求进出都要经过它
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许任何来源（* 是通配符）；在生产环境中应该设置具体的域名
    allow_credentials=True,  # 允许请求携带 cookie 等身份凭证
    allow_methods=["*"],  # 允许任何 HTTP 方法（GET/POST/...）
    allow_headers=["*"],  # 允许任何请求头
)

logger.info("CORS配置成功")

# ==================== API密钥配置 ====================
# 从环境变量获取阿里云DashScope API密钥（用于语音识别和合成）
if DASHSCOPE_API_KEY:
    logger.info('DASHSCOPE_API_KEY 已加载')
else:
    logger.warning('DASHSCOPE_API_KEY 未配置!')

# ==================== API文档（本地化 swagger-ui） ====================
# FastAPI 默认的 /docs 页面从 cdn.jsdelivr.net 拉取 swagger-ui 的 CSS/JS，
# 本机代理（clash）或网络不稳时页面会白屏。
# 这里关闭默认实现（docs_url=None），用 fastapi.openapi.docs.get_swagger_ui_html
# 生成同样的页面，但资源指向项目内 static/swagger-ui/（离线可用）。
from fastapi.openapi.docs import get_swagger_ui_html

# @app.get("/docs")：装饰器写法，把下面的函数注册成"GET /docs 的处理器"（每个路由都是这个模式）
# include_in_schema=False：不让 /docs 自己出现在 openapi.json 里（否则文档页里还套娃一个"文档页"）
@app.get("/docs", include_in_schema=False)
async def custom_docs():
    """接口文档页面（swagger-ui 资源本地化版本）"""
    # get_swagger_ui_html：FastAPI 自带的工具函数，生成 swagger-ui 文档页的 HTML。
    # 它默认指向 CDN，这里把 JS/CSS 地址改指到本机 /static/... 实现离线可用；
    # openapi_url 指向 /openapi.json——页面加载后就去拉这份 JSON 来渲染出接口列表
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - 接口文档",
        oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
        swagger_js_url="/static/swagger-ui/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger-ui/swagger-ui.css",
    )

# ==================== 静态文件服务 ====================
# {path:path} 里的 :path 是"路径转换器"：普通参数遇到 / 就会断开，
# 加了它之后一个参数能吃进整段子路径（如 swagger-ui/swagger-ui.css 这种带斜杠的）
@app.get("/static/{path:path}")
async def serve_static(path: str):
    """提供静态文件服务"""
    # os.path.dirname(__file__)：__file__ 是 Python 内置变量 = 当前文件路径，
    #   dirname 取它所在的目录 → app/；os.path.join 按系统分隔符拼出 app/static
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    # 把请求的子路径接在后面 → 完整磁盘路径，如 app/static/admin.html
    file_path = os.path.join(static_dir, path)

    # exists 防止路径不存在时报错，isfile 确保是文件而不是目录，两个条件都满足才返回
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return FileResponse(file_path)  # 文件响应：FastAPI 负责把文件内容发给浏览器
    else:
        # raise（抛出）HTTPException → FastAPI 捕获后转成 404 响应 {"detail": "文件不存在"}
        # 这是"业务代码里返回错误"的标准姿势，不用自己手动拼错误 JSON
        raise HTTPException(status_code=404, detail="文件不存在")

# ==================== 根路径 ====================
@app.get("/")
async def root():
    """根路径：返回管理后台首页（对齐 nginx try_files admin.html 的生产行为）"""
    admin_path = os.path.join(os.path.dirname(__file__), "static", "admin.html")
    if os.path.exists(admin_path):
        return FileResponse(admin_path)  # 直接把 admin.html 文件发给浏览器
    # 兜底：文件不存在就返回一段 JSON（return 一个 dict，FastAPI 自动转成 JSON 响应）
    return {"message": "智能招聘面试模拟系统 API", "version": "1.0.0"}

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
# 注册"兜底异常处理器"：任何接口代码里没被 try/except 接住的异常，最后都会落到这里，
# 统一转成 500 响应——避免 uvicorn 甩出默认的丑陋错误页、客户端拿到无意义的内容
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理器"""
    # exc 就是那个没被接住的异常对象；f-string 里 {exc} 会转成异常的文字描述
    logger.error(f"全局异常: {exc}")
    # traceback：打印异常堆栈（哪一行出的错、怎么一层层调进来的），排障必看
    import traceback
    traceback.print_exc()

    # 返回 500 JSON 响应。注意：str(exc) 会把内部异常原文暴露给客户端，
    # 开发期方便排错；正式对外时建议去掉 message，防止泄露实现细节
    return JSONResponse(
        status_code=500,
        content={"error": "内部服务器错误", "message": str(exc)}
    )


# Python 经典模式：直接运行本文件（python -m app.main）时，内置变量 __name__ 的值
# 才是 '__main__'，下面的启动逻辑才会执行；本文件被别的代码 import 时 __name__ 是
# 'app.main'，条件不成立，不会误触发启动——这样本文件既能当入口又能当模块
if __name__ == '__main__':
    logger.info("启动FastAPI服务器...")
    logger.info("服务器启动在 http://0.0.0.0:10009")

    # 启动uvicorn服务器（端口 10009 与原 Flask 版一致，nginx/Docker 配置无需改动）
    uvicorn.run(
        "app.main:app",  # "模块路径:应用变量名" 格式的字符串，uvicorn 据此 import 并找到 app 对象
        host="0.0.0.0",  # 监听所有网卡：本机 127.0.0.1 和局域网 IP 都能访问；只本机用可改成 127.0.0.1
        port=10009,      # 监听端口
        reload=True,    # 改代码后不自动重启（开发时可改 True 热重载）
        workers=1        # 单进程。已迁 PostgreSQL（支持并发写，不再有 SQLite 单写者锁库问题）；个人版保持单进程简单可靠
    )
