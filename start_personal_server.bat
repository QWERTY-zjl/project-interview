@echo off

REM 启动个人用户版面试模拟系统服务器
cd /d "%~dp0\app"

REM 检查Python是否安装
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python 未安装，请先安装 Python 3.7 或更高版本
    pause
    exit /b 1
)

REM 检查依赖是否安装
pip list | findstr "Flask" >nul 2>&1
if %errorlevel% neq 0 (
    echo 正在安装依赖...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo 依赖安装失败，请检查网络连接
        pause
        exit /b 1
    )
)

REM 启动服务器
echo 启动个人用户版面试模拟系统服务器...
python server.py

pause
