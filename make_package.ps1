# 打包绿色软件包：把 git 已跟踪的代码打成 zip（评委解压即用）
# 用法：先提交所有改动，再在仓库根目录执行  powershell -File make_package.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# 前置检查：已跟踪文件必须全部提交（git archive 只打包已提交内容，漏提交会导致包里是旧代码）。
# 未跟踪文件（??）不进包也不影响包完整性，仅提示；已跟踪文件的修改/删除（M/D）直接中止
$dirty = git status --porcelain | Where-Object { $_ -notmatch '^\?\?' }
if ($dirty) {
    Write-Host "[中止] 已跟踪文件存在未提交的改动，请先提交 git：" -ForegroundColor Red
    $dirty | ForEach-Object { Write-Host "  $_" }
    exit 1
}
$untracked = git status --porcelain | Where-Object { $_ -match '^\?\?' }
if ($untracked) {
    Write-Host "[提示] 以下未跟踪文件不会打进包（如需纳入请先提交）：" -ForegroundColor Yellow
    $untracked | ForEach-Object { Write-Host "  $_" }
}

# 版本号：取当天日期，方便区分多轮提交的作品包
$version = Get-Date -Format "yyyyMMdd"
$outDir = Join-Path $PSScriptRoot "dist"
$outFile = Join-Path $outDir "AI面试模拟系统_$version.zip"

New-Item -ItemType Directory -Force -Path $outDir | Out-Null
# --prefix 给包内所有条目套一层顶层文件夹（与 zip 同名），解压不会散落一地文件
$prefix = "AI面试模拟系统_$version/"
git archive --format=zip "--prefix=$prefix" "--output=$outFile" HEAD

# 密钥注入：真实 API Key 只存在本地 .env（不入 git），打包时才写进 zip 内的 .env，
# 评委解压后无需配置即可运行；git 仓库全程不接触密钥
Add-Type -AssemblyName System.IO.Compression.FileSystem
if (Test-Path ".env") {
    $zip = [System.IO.Compression.ZipFile]::Open((Resolve-Path $outFile).Path, 'Update')
    try {
        $entry = $zip.CreateEntry("$prefix.env")
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

# 便携 Python 运行时注入：runtime\python（embeddable Python + 预装依赖）整体追加进
# 顶层文件夹内，评委解压即用，无需安装 Python；runtime 目录不入 git，仅存在于作品包
if (Test-Path "runtime\python\python.exe") {
    $zip = [System.IO.Compression.ZipFile]::Open((Resolve-Path $outFile).Path, 'Update')
    try {
        $files = Get-ChildItem "runtime" -Recurse -File | Where-Object { $_.FullName -notmatch '__pycache__|\\.pytest_cache' }
        foreach ($f in $files) {
            $rel = "runtime\" + $f.FullName.Substring((Resolve-Path "runtime").Path.Length + 1)
            $entryPath = $prefix + ($rel -replace '\\', '/')
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $f.FullName, $entryPath, [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
        }
        Write-Host "[运行时] 已注入便携 Python（$($files.Count) 个文件），评委免安装运行" -ForegroundColor Cyan
    } finally {
        $zip.Dispose()
    }
    $sizeMB = [math]::Round((Get-Item $outFile).Length / 1MB, 2)
} else {
    Write-Host "[警告] 未找到 runtime\python，作品包不含内置 Python，评委需先运行 setup.bat" -ForegroundColor Yellow
}

Write-Host "[完成] 打包成功: $outFile ($sizeMB MB)" -ForegroundColor Green
Write-Host "提交材料清单核对：安装运行说明.txt / setup.bat / start_personal_server.bat / .env / runtime 便携 Python 应都在包内"
