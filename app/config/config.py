"""
配置模块
==========
负责加载和管理应用配置
"""

import os
from dotenv import load_dotenv

# 加载 .env 环境变量文件
load_dotenv()

# 阿里云 DashScope API 密钥（同时支持 OPENAI_API_KEY 环境变量）
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY")

# OpenAI API 密钥（备用）
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# OpenAI API 地址（默认使用国内代理）
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.chatanywhere.tech/v1")

# DashScope OpenAI 兼容接口地址（出题走这里）
DASHSCOPE_BASE_URL = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

# 出题用的文本模型
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-flash")

# 文本向量化模型（知识库向量检索：把文字变成一串数字，用于算语义相似度；
# 与 LLM 同走 DASHSCOPE_BASE_URL 兼容端点、同用一个 API key）
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v3")

# 视觉理解模型（表情识别：分析摄像头抓拍画面里的情绪，需支持图像输入）
VISION_MODEL = os.getenv("VISION_MODEL", "qwen3.8-flash")

# ==================== AI 服务配置（全部可在 .env 里覆盖，无需改代码）====================
# 使用者想换模型/换服务商时，只需要在 .env 里写同名变量，例如：
#   LLM_MODEL=qwen-plus           # 换文本模型
#   TTS_MODEL=cosyvoice-v3-flash  # 换语音合成模型
# 各项用途见下面每条注释；所有值都有默认值，不配也能跑（但 AI 功能需要 DASHSCOPE_API_KEY）

# DashScope 原生 API 端点（语音识别/语音合成/表情识别等「非 OpenAI 兼容」接口走这里；
# 出题和报告走上面的 DASHSCOPE_BASE_URL 兼容端点，两者不同，别混用）
DASHSCOPE_NATIVE_URL = os.getenv("DASHSCOPE_NATIVE_URL", "https://dashscope.aliyuncs.com")

# 语音识别模型（ASR：把面试录音转成文字；dashscope Recognition 本地文件转写对应流式识别模型）
ASR_MODEL = os.getenv("ASR_MODEL", "paraformer-realtime-v2")

# 语音合成模型（TTS：把面试题朗读出来）
TTS_MODEL = os.getenv("TTS_MODEL", "cosyvoice-v3-flash")

# 默认朗读音色（当前端传来的音色类型不在映射表里时兜底用）
# cosyvoice 系列用音色 ID（如 longanzhi_v3 男 / longanya_v3 女），不认 zh-CN-* 风格音色
DEFAULT_TTS_VOICE = os.getenv("DEFAULT_TTS_VOICE", "longanzhi_v3")

# ==================== 数据库连接配置 ====================
# 【分发开关】DATABASE_URL 有值 → 全系统走 PostgreSQL；为空 → 回退 SQLite（原路径不动）
# 双轨即回退开关：删掉 .env 里的 DATABASE_URL 即可整体回到 SQLite，现场秒恢复
# 【conninfo 格式】postgresql://用户名:密码@主机:端口/库名
#   本机开发连容器映射的 127.0.0.1:5432；Docker 部署时 compose 的 environment
#   会用容器网络主机名 postgres 覆盖这里（环境变量优先于 .env 文件）
DATABASE_URL = os.getenv("DATABASE_URL", "")

# SQLite 数据库文件路径（变量名叫 NAME，实际存的是完整路径；仅 DATABASE_URL 为空时使用）
# 【为什么要锚定】"interview_system.db" 这种裸文件名是相对路径，跟「进程启动目录」走：
#   从仓库根启动 → 连 <仓库根>/interview_system.db，从别处启动 → 又是另一个文件。
#   实际后果：服务器连到一个凭空生成的空库，所有查询报 no such table。
# 和建表脚本的锚定方式一致：不管从哪个目录启动，连的都是同一个库文件
DATABASE_NAME = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'db', 'interview_system.db')

# 日志级别（默认 DEBUG）
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")

# 临时文件目录
TEMP_DIR = os.getenv("TEMP_DIR", os.path.join(os.path.dirname(__file__), "..", "temp"))

# 确保临时目录存在
os.makedirs(TEMP_DIR, exist_ok=True)
