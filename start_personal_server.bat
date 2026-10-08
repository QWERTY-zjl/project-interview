@echo off
REM 启动面试模拟系统服务器（FastAPI 版）
cd /d "%~dp0"

REM 解释器优先级：作品包内置便携 Python（免安装）-> 项目 venv -> 系统环境变量中的 python
if exist runtime\python\python.exe (
    set "PY=runtime\python\python.exe"
    echo 检测到内置 Python 运行时，免安装直接启动...
) else if exist app\venv\Scripts\python.exe (
    set "PY=app\venv\Scripts\python.exe"
    echo 使用项目虚拟环境 app\venv...
) else (
    echo 未找到 Python 解释器：请先双击 setup.bat 完成安装，或安装 Python 3.10+
    pause
    exit /b 1
)

REM 禁用用户级 site-packages：保证评委机器只用包内自带依赖，不受本机 Python 环境干扰
set "PYTHONNOUSERSITE=1"

REM API key 从项目根目录 .env 读取（作品包已内置），勿在此硬编码
echo 启动面试模拟系统服务器... 浏览器访问 http://127.0.0.1:10009
%PY% -m app.main

pause
