# SmartCane 上位机 Windows 启动脚本。
# -Install：安装/更新 requirements.txt；-Demo：使用模拟数据，不连接硬件。
param(
    [switch]$Install,
    [switch]$Demo
)

$ErrorActionPreference = "Stop"
$appRoot = $PSScriptRoot
$requirements = Join-Path $appRoot "requirements.txt"

if ($Install) {
    # 依赖只需首次运行或 requirements.txt 变化后安装。
    python -m pip install -r $requirements
}

$arguments = @((Join-Path $appRoot "main.py"))
if ($Demo) {
    $arguments += "--demo"
}
python @arguments
