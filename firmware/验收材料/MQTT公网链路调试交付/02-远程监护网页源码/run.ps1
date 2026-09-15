param(
    [switch]$Install,
    [switch]$Demo
)

$ErrorActionPreference = "Stop"
$appRoot = $PSScriptRoot

if ($Install) {
    python -m pip install -r (Join-Path $appRoot "requirements.txt")
}

if ($Demo) {
    $env:SMARTCANE_DEMO = "true"
}

python (Join-Path $appRoot "app.py")

