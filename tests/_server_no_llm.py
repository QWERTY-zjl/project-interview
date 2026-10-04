# -*- coding: utf-8 -*-
"""
测试专用服务启动器（tests/_server_no_llm.py）
==============================================
作用：启动 FastAPI 服务，但**彻底屏蔽 DashScope 大模型真实调用**。

原理（不改 .env、不改 app/ 下任何源码）：
1. 在 import app 之前，把 dotenv.load_dotenv 打成 no-op —— config.py 里的
   `from dotenv import load_dotenv` 拿到的就是本 lambda，.env 不会被加载；
2. 同时移除进程环境中的 DASHSCOPE_API_KEY / OPENAI_API_KEY；
3. 于是 app.config.config.DASHSCOPE_API_KEY = None，所有大模型调用点走
   「未配置 key」降级链：
   - question_service.call_llm_api      → 直接返回 None → 默认问题兜底
   - speech_service.synthesize_speech   → (None, "未配置 API Key")
   - expression_service.analyze_face_expression → (None, "未配置 DASHSCOPE_API_KEY")
   - report_service.generate_interview_report   → ({"error": ...}, 500)
   全程零 DashScope 网络请求、零额度消耗。

用法（仓库根目录）：
    app\\venv\\Scripts\\python.exe tests\\_server_no_llm.py
"""

import os
import sys

# 保证可以 import app.*（本文件在 tests/ 下，把仓库根目录加到 sys.path）
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

# 1) 屏蔽 .env 加载（config.py 的 from dotenv import load_dotenv 会拿到这个 no-op）
import dotenv
dotenv.load_dotenv = lambda *args, **kwargs: False

# 2) 移除进程环境里可能存在的 key，双保险
os.environ.pop("DASHSCOPE_API_KEY", None)
os.environ.pop("OPENAI_API_KEY", None)

# 3) 以与 `python -m app.main` 相同的方式启动服务
import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=10009, reload=False, workers=1)
