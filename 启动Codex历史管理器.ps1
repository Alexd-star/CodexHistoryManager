$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = 'python'
$port = 8765

Write-Host "启动 Codex 本地对话历史管理器..."
Write-Host "项目目录: $root"
Write-Host "访问地址: http://127.0.0.1:$port"
Write-Host ""

Set-Location $root
& $python "$root\app.py" --port $port
