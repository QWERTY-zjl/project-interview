# 打包绿色软件包：把 git 已跟踪的代码打成 zip（评委解压即用）
# 用法：先提交所有改动，再在仓库根目录执行  powershell -File make_package.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# 前置检查：工作区必须干净，否则 zip 内容不完整（git archive 只打包已提交内容）
$dirty = git status --porcelain
if ($dirty) {
    Write-Host "[中止] 存在未提交的改动，请先提交 git，保证打进包里的代码是完整的：" -ForegroundColor Red
    $dirty | ForEach-Object { Write-Host "  $_" }
    exit 1
}

# 版本号：取当天日期，方便区分多轮提交的作品包
$version = Get-Date -Format "yyyyMMdd"
$outDir = Join-Path $PSScriptRoot "dist"
$outFile = Join-Path $outDir "AI面试模拟系统_$version.zip"

New-Item -ItemType Directory -Force -Path $outDir | Out-Null
git archive --format=zip "--output=$outFile" HEAD

# 密钥注入：真实 API Key 只存在本地 .env（不入 git），打包时才写进 zip 内的 .env，
# 评委解压后无需配置即可运行；git 仓库全程不接触密钥
Add-Type -AssemblyName System.IO.Compression.FileSystem
if (Test-Path ".env") {
    $zip = [System.IO.Compression.ZipFile]::Open((Resolve-Path $outFile).Path, 'Update')
    try {
        $entry = $zip.CreateEntry(".env")
        $writer = New-Object System.IO.StreamWriter($entry.Open(), (New-Object System.Text.UTF8Encoding($false)))
        $writer.Write((Get-Content ".env" -Raw -Encoding UTF8))
        $writer.Close()
    } finally {
        $zip.Dispose()
    }
    Write-Host "[密钥] 已把本地 .env（真实 API Key）注入 zip，评委免配置运行" -ForegroundColor Cyan
} else {
    Write-Host "[警告] 本地未找到 .env，包内不含密钥，评委需自行配置 API Key" -ForegroundColor Yellow
}

$sizeMB = [math]::Round((Get-Item $outFile).Length / 1MB, 2)
Write-Host "[完成] 打包成功: $outFile ($sizeMB MB)" -ForegroundColor Green
Write-Host "提交材料清单核对：安装运行说明.txt / setup.bat / start_personal_server.bat / .env / .env.example 应都在包内"
