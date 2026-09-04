@echo off

REM 启动服务器（使用项目内置 venv；API key 从项目根目录 .env 读取，勿在此硬编码）
cd /d "%~dp0"
app\venv\Scripts\python.exe -m app.server
