# KerKer 安装脚本 (Windows PowerShell)
# 使用方法:
#   irm https://gitee.com/wxiangqi1202/kerker/raw/main/install.ps1 | iex
# 或本地: .\install.ps1

$ErrorActionPreference = "Stop"

# ─── 配置（发布时修改） ───
$Version   = "0.2.0"
$GiteeUser = "wxiangqi1202"
$GiteeRepo = "kerker"

# ─── Banner ───
Write-Host ""
Write-Host "  KerKer Installer" -ForegroundColor Cyan
Write-Host "  Computational Agent Framework" -ForegroundColor DarkGray
Write-Host ""

# ─── 架构检测 ───
$Arch = if ([Environment]::Is64BitOperatingSystem) { "x86_64" } else { "x86" }
# ARM64 检测 (Windows 11+)
try {
    if ((Get-CimInstance Win32_Processor).Architecture -eq 12) { $Arch = "arm64" }
} catch {}

Write-Host "  -> 系统: windows-$Arch" -ForegroundColor DarkGray

# ─── 下载 ───
$FileName    = "kerker-windows-${Arch}.exe"
$DownloadUrl = "https://gitee.com/$GiteeUser/$GiteeRepo/releases/download/v$Version/$FileName"
$InstallDir  = Join-Path $env:USERPROFILE ".kerker"
$Target      = Join-Path $InstallDir "kerker.exe"

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

Write-Host "  -> 下载 KerKer v$Version..." -ForegroundColor Cyan

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $DownloadUrl -OutFile $Target -UseBasicParsing
} catch {
    Write-Host "  X 下载失败: $_" -ForegroundColor Red
    Write-Host "    URL: $DownloadUrl" -ForegroundColor DarkGray
    exit 1
}

$Size = [math]::Round((Get-Item $Target).Length / 1MB, 1)
Write-Host "  √ 下载完成 (${Size}MB)" -ForegroundColor Green

# ─── 添加到 PATH ───
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($UserPath -notlike "*$InstallDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$InstallDir;$UserPath", "User")
    $env:Path = "$InstallDir;$env:Path"
    Write-Host "  √ 已添加到用户 PATH" -ForegroundColor Green
} else {
    Write-Host "  √ PATH 已包含安装目录" -ForegroundColor Green
}

# ─── 完成 ───
Write-Host ""
Write-Host "  安装成功！" -ForegroundColor Green
Write-Host ""
Write-Host "  使用:  kerker" -ForegroundColor Cyan
Write-Host "  首次启动自动引导 API Key 配置" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  (如果 kerker 命令未生效，请重启终端)" -ForegroundColor DarkGray
Write-Host ""
