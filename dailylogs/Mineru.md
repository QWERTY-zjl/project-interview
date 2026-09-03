# Mineru
##  1. mineru是什么？
MinerU是一款由上海人工智能实验室（OpenDataLab团队）开发的开源智能文档解析工具。它的核心目标是“读懂”复杂文档，将PDF、图片、Word、PPT、Excel等格式的文件，精准地转换为结构化的机器可读格式（如Markdown、JSON），现如今markdown格式已经成为了大模型训练的主流格式，这样处理后为AI模型训练、知识库构建等场景提供高质量的数据。
## 2. mineru的底层及工作原理
它的底层使用的是一个自研的VLM(视觉语言大模型)，集成了yolo和paddleocr(飞桨ocr模型)，参数量小于10亿（1B），它的工作采用先布局，后识别”的两阶段策略。先对整个页面做全局分析，确定各区域的类型和阅读顺序，然后再对每个区域进行内容识别。实现了整页文档的一体化理解，直接输出结构化结果。文本，表格都可以直接转化为markdown,但是图片需要调用VlM对图片内容进行
总结再转换为markdown。
它具有两个主要功能：
1. 跨页合并：能自动检测并合并跨页的段落和表格，保持内容的完整性，让模型能够更准确地理解文档的上下文。
2. 层级推断：能通过分析全文的标题，推断出文档的层级结构（如H1, H2, H3），便于markdown格式的输出。

## 3. mineru的工作流程
1.输入：PDF、图片、Word、PPT、Excel等格式的文件
2.文档预处理：检查语言，页面大小，文件是否被扫描以及加密状态
3.内容解析：
（1）区分文本区域、表格区域、图片区域、公式区域
    1. ocr:对扫描的pdf进行文本识别
    2. 对表格区域进行识别，直接输出为html/latex格式
    3. 对公式区域进行识别，转换为latex格式
4.内容后处理：
    对初步提取的结果进行置信度过滤和重叠去除，分析全文的标题，推断出文档的层级结构（如H1, H2, H3），并按照自然的阅读顺序重新排列内容，最后，将所有处理好的内容整合，输出为结构化的Markdown或JSON格式。
## 3. mineru的支持
 mineru支持linux、windows、macos等操作系统。还有华为昇腾等硬件

## 4. mineru的本地部署
 ### 阶段 0：环境准备

- 在 `app\venv` 安装：`pip install "mineru[core]==2.7.6" -i https://mirrors.aliyun.com/pypi/simple`
  - **必须锁 2.7.6**：3.x 起 CLI 架构改变（编排客户端 + 自动拉起本地 API 服务），本方案的 CLI 集成假设不成立
  - 顺带解决 venv 缺失的 `requests`、`Pillow`（mineru 依赖包含）
- 预下载模型权重（避免首个用户请求触发 1-2GB 下载）：
  `$env:MINERU_MODEL_SOURCE='modelscope'; mineru -p "docs\resumes\AI大模型产品经理简历.pdf" -o app\temp\mineru_warmup -b pipeline 

### 阶段 1：新建 `app/ai_services/resume_parser.py`

唯一入口：`parse_resume_to_markdown(pdf_bytes, filename="resume.pdf") -> str`

- **集成方式：subprocess 调 mineru CLI**（`mineru -p x.pdf -o outdir -b pipeline`），进程隔离、可超时控制、失败判定简单；不把 torch 拉进 Flask 进程
  - Windows 下加 `creationflags=CREATE_NO_WINDOW`；env 传 `MINERU_MODEL_SOURCE=modelscope`
  - **必须显式** **`-b pipeline`**（2.7.6 默认后端需 GPU）
  - 输出 md 用 `glob(outdir/**/*.md, recursive=True)` 定位，不硬编码 `auto` 子目录
  - 临时文件放 `app/temp`（复用 config.py 的 TEMP\_DIR），uuid 主名规避中文路径，用后 `shutil.rmtree`
- **降级链**：MinerU CLI 不存在 / 超时（默认 300s，env 可覆盖）/ 非零退出 / 输出空 → 降级 PyPDF2（逻辑从 server.py L1903-1933 迁入）→ 仍失败返回 `""`
- **清洗**：正则剥离图片引用 `![](...)`（保留 HTML 表格与 LaTeX 公式，对出题有价值）、收敛空行、截断至 8000 字符（env 可覆盖）

### 阶段 3：重构 `app/ai_services/question_service.py` + config.py

- `app/config/config.py` 新增：
  ```python
  DASHSCOPE_BASE_URL = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
  LLM_MODEL = os.getenv("LLM_MODEL", "qwen-flash")
  ```
- **`call_llm_api(messages, max_tokens=2000)`**：参数从 `(prompt, resume_image)` 改为 OpenAI 格式 messages 列表；用已安装的 openai SDK 直连 DashScope 兼容接口，模型 `LLM_MODEL`，`response_format={"type":"json_object"}`；json.loads 失败时先剥 \`\`\`json 围栏再试
- **`generate_questions(..., resume_md=None)`**：第 8 参从 `resume_image` 改为 `resume_md`（markdown 文本）
  - `messages = build_interview_prompt(candidate, position, latest_tech_info or "")`（复用 prompt.py，修复 NameError）
  - `resume_md` 非空时追加到 `messages[-1]["content"]`
  - 失败兜底 `get_default_questions()`（从 prompt.py 导入）
- 修复导入：`from app.ai_services.speech_service import synthesize_speech`；`from app.ai_services.prompt import build_interview_prompt, get_default_questions`
- prompt.py 本身不动（只复用其纯函数）

### 阶段 4：改造 `app/server.py` 上传简历路由

- L1895-1945：内联 PyPDF2 解析块 → 替换为调用 `parse_resume_to_markdown`（非 PDF 文件保持旧行为：直接 decode）
- **L1952-2007：整块删除 PIL 画图生成截图代码**（resume\_image 彻底消失）
- L1947-1950：空内容检查改为检查 `resume_md`
- L1819-1821：删掉不再使用的 `import base64` / `from PIL import Image` / `from io import BytesIO`
- L2125：调用传参 `resume_image` → `resume_md`
- 修复导入路径（函数内 import）：L221、L2078（question\_service）、L749、L813、L877（expression\_service）→ `app.ai_services.*`

### 阶段 5：修复 api 模块导入

- `app/api/resume_api.py` L12-13、`app/api/tts_api.py` L9、`app/api/expression_api.py` L12 → `app.ai_services.*`

### 阶段 6：文档与脚本收尾

- README.md 目录树与服务表更新为 `ai_services/`
- `start_server.bat` / `start_server.ps1` 删除硬编码的 DASHSCOPE\_API\_KEY（安全隐患，key 走 .env）

## 验证方案

1. **语法**：`py_compile` 所有改动文件
2. **导入**：`from app.ai_services.question_service import generate_questions` 等全量导入；`import app.server`、`import app.main`
3. **MinerU 冒烟**：CLI 解析 `docs/resumes/AI大模型产品经理简历.pdf`，确认输出 .md 含中文正文
4. **resume\_parser 单测**：主路径（MinerU）+ 降级路径（`MINERU_TIMEOUT=1` 强制降级 PyPDF2）
5. **端到端**：设无效 key 启动 server（端口 10009），`curl -F resume=@...pdf http://127.0.0.1:10009/api/resume/upload`，预期返回 success 且日志出现 `[Question] 使用默认问题`（LLM 失败兜底链路正常）
6. **残留扫描**：`rg "app\.services|ai-services" app` 应 0 条代码命中

## 风险与注意

- mineru\[core] 安装约 4-6GB（含 torch），需用国内镜像；磁盘建议 20GB+
- 首次 MinerU 解析会下载 1-2GB 模型 → 必须预下载（阶段 0）；CPU 解析一次简历约 20-60s，上传接口响应变慢属预期（threaded=True 不阻塞其他请求）
- 行号会随编辑漂移，实施时按锚点（注释/函数名）定位
- MinerU 2.7.6 为 AGPL-3.0 许可，个人项目无碍

