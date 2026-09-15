# 无硬件图传演示脚本：启动本地模拟相机，再运行 Qt 接收端并自动截图。
param(
    [string]$Python = "python",
    [int]$Duration = 12
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ArtifactDir = Join-Path (Split-Path -Parent $ScriptDir) "artifacts"
$Screenshot = Join-Path $ArtifactDir "qt_receiver_mock.png"

$Server = Start-Process -FilePath $Python `
    -ArgumentList @((Join-Path $ScriptDir "mock_camera_server.py"), "--port", "8765", "--interval", "10") `
    -WorkingDirectory $ScriptDir -WindowStyle Hidden -PassThru

try {
    Start-Sleep -Milliseconds 800
    & $Python (Join-Path $ScriptDir "qt_receiver.py") `
        --url "http://127.0.0.1:8765" `
        --interval 10 `
        --duration $Duration `
        --screenshot $Screenshot `
        --capture-dir (Join-Path $ArtifactDir "mock_captures")
}
finally {
    if ($Server -and -not $Server.HasExited) {
        Stop-Process -Id $Server.Id -Force
    }
}

Write-Output "Screenshot: $Screenshot"
