# KerKer 安装脚本 (Windows PowerShell)
# 使用方法: 在 PowerShell 中执行
#   irm https://raw.githubusercontent.com/wxiangqi1202-cpu/kerker-computer-assistant/main/install.ps1 | iex
# 或本地执行:
#   .\install.ps1

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "  +-----------------------------------+" -ForegroundColor Cyan
Write-Host "  |  KerKer 安装脚本 (Windows)        |" -ForegroundColor Cyan
Write-Host "  |  Computational Agent Framework    |" -ForegroundColor Cyan
Write-Host "  +-----------------------------------+" -ForegroundColor Cyan
Write-Host ""

# ---------- Python 检测 ----------
$PY = $null
foreach ($cmd in @("python3", "python", "py")) {
    try {
        $version = & $cmd --version 2>&1
        if ($version -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -ge 3 -and $minor -ge 9) {
                $PY = $cmd
                break
            }
        }
    } catch {}
}

if (-not $PY) {
    Write-Host "  X 未找到 Python 3.9+，请先安装" -ForegroundColor Red
    Write-Host "    下载: https://www.python.org/downloads/" -ForegroundColor DarkGray
    Write-Host "    安装时请勾选 'Add Python to PATH'" -ForegroundColor DarkGray
    exit 1
}

$pyVersion = & $PY --version 2>&1
Write-Host "  Python: $PY ($pyVersion)"

# ---------- pip 检测 ----------
$PIP = $null
try {
    & $PY -m pip --version 2>&1 | Out-Null
    $PIP = "$PY -m pip"
} catch {
    foreach ($cmd in @("pip3", "pip")) {
        try {
            & $cmd --version 2>&1 | Out-Null
            $PIP = $cmd
            break
        } catch {}
    }
}

if (-not $PIP) {
    Write-Host "  X 未找到 pip" -ForegroundColor Red
    Write-Host "    尝试: $PY -m ensurepip --upgrade" -ForegroundColor DarkGray
    exit 1
}
Write-Host "  pip: $PIP"

# ---------- git 检测 ----------
try {
    git --version | Out-Null
} catch {
    Write-Host "  X 未找到 git，请先安装" -ForegroundColor Red
    Write-Host "    下载: https://git-scm.com/download/win" -ForegroundColor DarkGray
    exit 1
}
Write-Host ""

# ---------- 安装 ----------
$InstallDir = Join-Path $env:USERPROFILE ".kerker\src"

if (Test-Path (Join-Path $InstallDir ".git")) {
    Write-Host "  更新已有安装..."
    Push-Location $InstallDir
    try {
        git pull --quiet
    } catch {
        Write-Host "  ! git pull 失败，使用本地版本继续" -ForegroundColor Yellow
    }
    Pop-Location
} else {
    if (Test-Path $InstallDir) {
        Remove-Item -Recurse -Force $InstallDir
    }
    Write-Host "  下载 KerKer..."
    git clone --quiet --depth 1 https://github.com/wxiangqi1202-cpu/kerker-computer-assistant.git $InstallDir
}

Write-Host "  安装依赖..."
Push-Location $InstallDir
& $PY -m pip install --quiet -e .
Pop-Location

# ---------- 验证 ----------
$kerkerCmd = Get-Command kerker -ErrorAction SilentlyContinue
if ($kerkerCmd) {
    Write-Host ""
    Write-Host "  √ 安装完成！" -ForegroundColor Green
    Write-Host "  路径: $($kerkerCmd.Source)" -ForegroundColor DarkGray
} else {
    Write-Host ""
    Write-Host "  √ 安装完成！" -ForegroundColor Green
    Write-Host "  ! kerker 命令未在 PATH 中找到" -ForegroundColor Yellow
    Write-Host "    可直接运行: $PY $InstallDir\main.py" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "  输入 kerker 启动"
Write-Host "  首次启动会引导你完成 API Key 配置"
Write-Host ""
