# FastAPI 学习笔记（基于本项目）

> 本文档不是 FastAPI 通用教程，而是**如何把 project-interview 项目当教材**的学习指南。
> 每个概念都对应项目里的真实文件——读的项目代码越多，学得越快，反向也成立。

---

## 0. 这份文档怎么用

- **配三样东西一起用**：本文档（地图）+ 项目代码（教材）+ `/docs` 页面（实验室）
- 读代码时打开浏览器访问 `http://localhost:10009/docs`，接口和函数一一对照
- 每个概念先看"语法拆解"，再跳到项目文件里找实例，最后在 /docs 里动手验证
- 学习顺序严格按第 3 节的路线走，不要跳

---

## 1. FastAPI 在项目中的位置

```
浏览器 / 前端页面
      │  HTTP 请求
      ▼
uvicorn（服务器引擎，占住 10009 端口，管字节收发和并发）
      │  解析成 Python 对象
      ▼
FastAPI（main.py，查路由表：这个路径+方法 → 交给哪个函数）
      │  解析参数、调用函数
      ▼
app/api/*.py（接口函数：本项目 34 个接口）
      │  调用业务层
      ▼
app/ai_services/（调大模型出题/报告）  app/db/（SQLite 读写）
```

一句话分工：
- **uvicorn** 是门卫兼跑堂——没有它，FastAPI 这个库自己不会监听端口
- **FastAPI** 是前台分诊——没有它，uvicorn 不知道请求交给谁
- **api/ 里的函数**是后厨——真正干活的地方，也是你要学的核心

启动链：`start_server.bat` → `python -m app.main` → [main.py](../app/main.py) 末尾 `uvicorn.run(...)` 把整个服务拉起来。

---

## 2. 最小概念集（五个，抓完就能读项目）

### 2.1 路由：函数怎么变成接口

**语法拆解**（以 [resume_api.py](../app/api/resume_api.py) 为例）：

```python
router = APIRouter(tags=["简历"])          # ① 建一个"分组路由器"

@router.post("/api/resume/upload", summary="上传简历并分析")   # ② 装饰器
async def upload_resume(request: Request, resume: UploadFile = File(...), ...):
```

- ② `@router.post(路径)` 叫**装饰器**：读作"把紧跟着的函数登记到路由表：POST 方式访问这个路径时，调用这个函数"。`@` 是 Python 语法糖，等价于 `router.post(...)(upload_resume)`——本项目旧版 main.py 就是这么写的（分离式），规范化后才改成现在的装饰器式。**装饰器式是 FastAPI 官方标准**。
- `tags=["简历"]`：/docs 页面里的分组名；`summary=`：/docs 列表里的中文摘要
- 34 个分组路由器最后在 main.py 里用 `app.include_router(xxx_router)` 挂载到主应用——这就是 main.py 的"组装"角色

**实例分布**：10 个 api 文件的每个函数头上。

**/docs 验证**：打开 /docs，看分组和摘要，点开"简历 → 上传简历并分析"看它的门牌（POST + 路径）。

### 2.2 参数声明：函数签名就是说明书

FastAPI 最魔法的地方：**参数从哪来、什么类型，全写在函数签名里**，框架自动解析校验。

| 写法 | 从哪取值 | 项目实例 |
|---|---|---|
| `token: str = Path(...)` | URL 路径里的占位符 `{token}` | [interview_api.py](../app/api/interview_api.py) 的 `get_interview_info` |
| `keyword: str = Query(None)` | URL 问号后面 `?keyword=x` | position_api 的查询参数 |
| `data: dict = Body(None)` | 请求体 JSON | [auth_api.py](../app/api/auth_api.py) 的注册/登录 |
| `work_experience: str = Form(...)` | 表单字段 | resume_api 的文本参数 |
| `resume: UploadFile = File(...)` | 上传的文件 | resume_api 的简历文件 |

- `Path(...)` 里的 `...` 表示必填；`Body(None)` 里的 `None` 表示可选（不传就是 None）
- 冒号后面是**类型标注**（Python 自带语法，不是 FastAPI 发明的）：FastAPI 按类型自动转换和校验，类型不对直接返回 422，你的函数根本不会被执行——你上传简历时遇到的 422（要文件却给了字符串）就是它在工作

**/docs 验证**：展开任意接口看 Parameters 区域，和函数签名对照。

### 2.3 返回：怎么把 Python 数据发回去

项目里两种写法都在用：

```python
# 写法一：完整控制（状态码 + 内容）—— 项目主流
return JSONResponse(status_code=200, content={"status": "success", "token": token})

# 写法二：直接 return 字典（FastAPI 自动打包成 200）
return {"msg": "ok"}
```

**实例分布**：resume_api 全是写法一（因为不同失败分支要返回不同状态码 400/500）；简单接口用写法二。

### 2.4 错误处理：两套机制

```python
raise HTTPException(status_code=404, detail="文件不存在")   # ① 框架标准：抛异常
return JSONResponse(status_code=500, content={...})          # ② 手动返回：业务错误对象
```

- ① 抛出去由 FastAPI 统一转成响应，适合"快速失败"
- ② 项目里 api 层大量使用，因为前端约定要读 `{"status": "error", "message": ...}` 这种统一结构
- 两者效果类似，**读代码时别把 ② 当成漏网之鱼**——这是项目有意的选择

### 2.5 启动与生命周期：lifespan

main.py 里：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()        # 启动前：建表、初始化
    yield            # ← 服务在这里运行（此行之前=开机，之后=关机）
    # 关停时要做的事写 yield 后面
```

这就是为什么服务器一启动数据库表就自动建好了。语法上 `@asynccontextmanager` 是"把一个函数变成可异步管理的生命周期对象"，细节先不深究，记住**yield 前=启动时执行、yield 后=关停时执行**即可。

---

## 3. 学习路线图（五步，按顺序）

### 第 1 步：在 /docs 里玩出体感（不动代码）

- 目标：建立"接口 = 可调用的函数"的直觉
- 操作：
  1. `GET /api/pricing/plans` → Try it out → Execute（无副作用随便玩）
  2. 走通真实业务闭环：上传一份简历文件 → 复制响应里的 token → 到 `GET /api/interview/{token}/info` 查这场面试 → 再到 `get_question` 拿题
  3. 故意触发一次 422（比如 register 传错类型），读懂响应里的 `loc/msg/input` 三字段
- 自测：422 和 500 的区别是什么？（参数没进门 vs 函数里干活出错）

### 第 2 步：读 main.py，看懂"组装"

- 目标：明白整个应用怎么拼起来
- 重点看四段：`lifespan`（启动钩子）、`CORS`（允许前端页面跨域调接口）、11 行 `include_router`（接口地图）、`uvicorn.run`（启动）
- 跳过：/docs、/static 两个路由（已经懂了）
- 自测：为什么 api 文件里的 router 要 include 才生效？

### 第 3 步：精读 auth_api.py（最简单的完整接口）

- 目标：看懂一个接口从进到出的全部
- 顺序：`api_register`（写库）→ `api_login`（查库+校验）
- 对照 /docs 里"用户认证"分组玩一遍注册登录
- 自测：`data.get("username")` 的数据是从请求的哪部分来的？

### 第 4 步：精读 interview_api.py（核心业务）

- 目标：理解真实复杂度——路径参数、多个接口组成一条业务流
- 顺序按面试生命周期：`create_interview` → `get_interview_info` → `get_next_question` → `submit_text_answer`
- 重点体会：一个 token 怎么把 4 个接口串成一场面试
- 自测：如果 two 个请求同时查同一场面试，会出什么问题？（联想起 SQLite 单写者）

### 第 5 步：对照 server.py（Flask 版），理解框架差异

- server.py 是退役的旧 Flask 入口，同一套业务两种写法，是现成的对照教材
- 对照点：Flask `request.json` 手动取参 vs FastAPI 签名声明自动取参
- 只读不改，读完能回答"为什么这个项目要迁到 FastAPI"
（没做，ai开发重点是ai技术，前后端技术适当了解即可）
---

## 4. 进阶概念（读完五步再回头看）

| 概念 | 项目里的位置 | 要点 |
|---|---|---|
| `async def` vs `def` | interview_api 两种都有 | `async` 函数里**不能调阻塞操作**（如同步大模型调用），否则整个服务卡住；不确定时用 `def`（FastAPI 会自动丢线程池跑） |
| BackgroundTasks | report_api 生成报告 | "先返回 200，后台慢慢生成报告"的异步模式 |
| 中间件 CORS | main.py | 前端页面和接口不同源时浏览器会拦截，CORS 中间件放行 |
| APIRouter 前缀 | 各 api 文件 | 大项目用 `APIRouter(prefix="/api/resume")` 减少重复，本项目为直观没有用，知道即可 |

---

## 5. 动手实验清单（改造练习，由浅入深）

1. 给任意接口换个 summary，刷新 /docs 看变化（30 秒见效，建立信心）
2. 给 `GET /api/pricing/plans` 的返回加一个字段（如 `"server_time": int(time.time())`）
3. 写一个只读新接口 `GET /api/interview/stats`：返回库里 interviews 总数、status 分布（练：新建 router + SQL + 返回）
4. 进阶：把第 3 步的接口改成支持 `?days=7` 只统计最近 N 天（练：Query 参数）

危险区（练手别碰）：支付/订单接口的函数体、`init_db`、任何写库接口的业务逻辑。改坏了先用 git diff 看改了什么。

---

## 6. 本项目实战踩过的坑（真实案例）

| 坑 | 现象 | 根因与解法 |
|---|---|---|
| 422 Unprocessable Content | 参数没进函数就被拦 | FastAPI 自动校验：读响应 JSON 的 `loc`（错在哪）、`msg`（要什么）、`input`（给了什么） |
| /docs 白屏 | HTML 到了但页面空白 | 界面资源从 CDN 加载被代理拦截；已本地化到 `static/swagger-ui/`（见 main.py 自定义 /docs 路由） |
| 文件接口显示成文本框 | UploadFile 无法选文件 | swagger-ui 版本对 OpenAPI 3.1 的兼容缺口，升级 swagger-ui-dist 解决 |
| 付费接口报"付费功能未启用" | 部分接口 503/错误兜底 | `payment_module` 未随 venv 安装，属已知遗留，不是你的问题 |
| 改了代码没效果 | 接口行为没变 | uvicorn 不会自动重载（生产模式），需重启 `python -m app.main` |

---

## 7. 官方文档使用姿势

不用从头读。碰到没见过的写法再去查对应小节：
- <https://fastapi.tiangolo.com/zh/tutorial/> （有官方中文版）
- 常查项：Path Parameters / Query Parameters / Request Body / Form and File / Handling Errors / Middleware

---

*整理于 2026-09-30，基于 FastAPI 迁移完成后的代码结构（34 接口 / 11 分组）。代码结构若后续调整，以实际文件为准。*
