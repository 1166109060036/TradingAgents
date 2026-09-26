# One-time setup of TradingBot on Windows: Python, a virtual environment, the
# packages (with MetaTrader 5 support), then the setup wizard and a check.
# Run it by double-clicking install.bat.

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root
$env:PYTHONUTF8 = "1"

function Find-Python {
    # The py launcher first; "python" may be the Microsoft Store stub, which
    # fails the version probe and is skipped.
    $candidates = @(
        @{ Exe = "py"; Args = @("-3") },
        @{ Exe = "python"; Args = @() }
    )
    foreach ($c in $candidates) {
        try {
            $a = $c.Args
            $ver = & $c.Exe @a -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $ver -and [version]$ver -ge [version]"3.10") { return $c }
        } catch { }
    }
    return $null
}

Write-Host "== TradingBot setup ==" -ForegroundColor Cyan
Write-Host "Folder: $Root"

$python = Find-Python
if (-not $python) {
    Write-Host "Python 3.10+ not found. Installing Python 3.12 with winget..." -ForegroundColor Yellow
    try {
        winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    } catch {
        Write-Host "winget is not available. Install Python 3.12 from https://www.python.org/downloads/" -ForegroundColor Red
        Write-Host "and tick 'Add python.exe to PATH' in the installer." -ForegroundColor Red
        exit 1
    }
    Write-Host ""
    Write-Host "Python was installed. Close this window and double-click install.bat again." -ForegroundColor Green
    exit 0
}
$pyExe = $python.Exe; $pyArgs = $python.Args

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment (.venv)..."
    & $pyExe @pyArgs -m venv .venv
}
$venvPy = Join-Path $Root ".venv\Scripts\python.exe"

Write-Host "Installing packages (a few minutes the first time)..."
& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install -e ".[mt5]" --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
New-Item -ItemType Directory -Force -Path "logs" | Out-Null

$bot = Join-Path $Root ".venv\Scripts\tradingbot.exe"
if (-not (Test-Path "bot.json")) {
    Write-Host ""
    Write-Host "Open MetaTrader 5 and log in to your Exness DEMO account before continuing." -ForegroundColor Yellow
    Write-Host "In MT5: Tools > Options > Expert Advisors > tick 'Allow algorithmic trading'." -ForegroundColor Yellow
    Write-Host ""
    & $bot setup -c bot.json --env .env
    if ($LASTEXITCODE -ne 0) { exit 1 }
}

Write-Host ""
& $bot check -c bot.json
Write-Host ""
Write-Host "Done. Next steps:" -ForegroundColor Green
Write-Host "  run-now.bat       analyse and trade once now"
Write-Host "  dry-run.bat       analyse only, no orders"
Write-Host "  status.bat        account and positions"
Write-Host "  schedule.bat      run automatically every day"
