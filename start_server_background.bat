@echo off

REM 后台静默启动服务器（FastAPI 版）
REM API key 从项目根目录 .env 读取（config.py 的 load_dotenv 自动加载），勿在此硬编码

REM 启动服务器（使用项目内置 venv）
start "Interview Server" /d "%~dp0" app\venv\Scripts\python.exe -m app.main

REM 等待服务器启动
timeout /t 5 /nobreak

REM 打开面试界面
start http://localhost:10009/static/interview.html

echo 服务器已启动，面试界面已打开
