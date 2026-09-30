# 启动服务器（FastAPI 版，使用项目内置 venv；API key 从项目根目录 .env 读取，勿在此硬编码）
Set-Location $PSScriptRoot
Write-Host "启动服务器..."
app\venv\Scripts\python.exe -m app.main
