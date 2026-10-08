@echo off

REM 一键安装脚本：创建虚拟环境并安装全部依赖（Python 3.10 及以上版本）
cd /d "%~dp0"

REM 第一步：检查本机是否已安装 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10 或以上版本
    echo        安装时务必勾选 Add Python to PATH，安装完成后重新运行本脚本
    pause
    exit /b 1
)
echo [1/3] 已检测到 Python：
python --version

REM 第二步：创建项目虚拟环境（已存在则跳过，不重复创建）
if exist app\venv\Scripts\python.exe (
    echo [2/3] 虚拟环境已存在，跳过创建
) else (
    echo [2/3] 正在创建虚拟环境（app\venv）...
    python -m venv app\venv
    if errorlevel 1 (
        echo [错误] 虚拟环境创建失败，请检查磁盘空间后重试
        pause
        exit /b 1
    )
)

REM 第三步：安装依赖（使用阿里云镜像加速，首次安装约需 3~5 分钟）
echo [3/3] 正在安装依赖，请耐心等待...
app\venv\Scripts\python.exe -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
if errorlevel 1 (
    echo [错误] 依赖安装失败，请检查网络后重新运行本脚本
    pause
    exit /b 1
)

echo.
echo ==============================================
echo  安装完成！接下来只需两步：
echo  1. 把 .env.example 复制一份并改名为 .env
echo     填入你的 DASHSCOPE_API_KEY（阿里云百炼控制台获取）
echo  2. 双击 start_personal_server.bat 启动系统
echo     浏览器访问 http://127.0.0.1:10009
echo ==============================================
pause
