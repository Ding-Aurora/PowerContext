# 启动本地 PowerContext Server（SQLite 轻量模式，不需要 seekdb / Embedding / Rerank）。
# 数据目录被隔离到本 qoder 目录下的 .pc-home，绝不写入其它赛题目录。
# 说明：PowerContext 由官方 pip 包提供（参考版本 1.5.1），不属于本应用源码。
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Resolve-Path (Join-Path $here "..")

# POWERCONTEXT_BIN 可指向你自己的 powercontext 可执行；默认尝试常见位置。
if ($env:POWERCONTEXT_BIN) {
  $pc = $env:POWERCONTEXT_BIN
} elseif (Test-Path (Join-Path $root "..\..\work\venv\Scripts\powercontext.exe")) {
  $pc = (Resolve-Path (Join-Path $root "..\..\work\venv\Scripts\powercontext.exe")).Path
} else {
  $pc = "powercontext"  # 依赖 PATH（例如你已 pip install powercontext[cli,server]==1.5.1）
}

$pcHome = Join-Path $root ".pc-home"
New-Item -ItemType Directory -Force -Path $pcHome | Out-Null
$env:POWERCONTEXT_HOME = $pcHome
$port = if ($env:PC_PORT) { $env:PC_PORT } else { 8777 }

Write-Host "启动 PowerContext：$pc server run --host 127.0.0.1 --port $port"
Write-Host "数据目录（隔离在 qoder 内）：$pcHome"
& $pc server run --host 127.0.0.1 --port $port
