@echo off

REM 设置环境变量
set DASHSCOPE_API_KEY=sk-cde6f62f2d4b41eaa98943b4f69fb19f

REM 启动服务器
start "Interview Server" python -m app.server

REM 等待服务器启动
timeout /t 5 /nobreak

REM 打开面试界面
start http://localhost:10009/static/interview.html

echo 服务器已启动，面试界面已打开
