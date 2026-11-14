# 启动研究续航站 Web 应用（标准库后端，无需 pip 安装）。
# 请先用 scripts/start_powercontext.ps1 启动 PowerContext，并复制 .env.example 为 .env（可选）。
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Resolve-Path (Join-Path $here "..")

if ($env:APP_PYTHON) { $py = $env:APP_PYTHON } else { $py = "python" }

Write-Host "启动研究续航站：$py server.py （读取 $root\.env）"
Push-Location $root
try {
  & $py server.py
} finally {
  Pop-Location
}
