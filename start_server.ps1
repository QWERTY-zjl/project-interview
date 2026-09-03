# 设置环境变量
$env:DASHSCOPE_API_KEY = 'sk-cde6f62f2d4b41eaa98943b4f69fb19f'

# 启动服务器
Write-Host "启动服务器..."
python -m app.server
