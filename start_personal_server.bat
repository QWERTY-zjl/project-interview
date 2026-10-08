@echo off

REM 启动个人用户版面试模拟系统服务器（FastAPI 版，使用项目内置 venv）
cd /d "%~dp0"

REM 检查虚拟环境是否存在
if not exist app\venv\Scripts\python.exe (
    echo 未找到项目虚拟环境 app\venv，请先按 README 完成环境搭建
    pause
    exit /b 1
)

REM 启动服务器（API key 从项目根目录 .env 读取，勿在此硬编码）
echo 启动个人用户版面试模拟系统服务器...
app\venv\Scripts\python.exe -m app.main

pause
