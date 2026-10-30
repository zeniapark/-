$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    Write-Host "[HANARO] Python 3 is required. Install it from https://www.python.org/downloads/windows/"
    Write-Host "[HANARO] During installation, select 'Add python.exe to PATH'."
    exit 1
}

$toolsDirectory = Join-Path $PSScriptRoot "tools"
$cloudflared = Join-Path $toolsDirectory "cloudflared.exe"
if (-not (Test-Path $cloudflared)) {
    New-Item -ItemType Directory -Path $toolsDirectory -Force | Out-Null
    Write-Host "[HANARO] Downloading the official Cloudflare tunnel program..."
    $download = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    Invoke-WebRequest -Uri $download -OutFile $cloudflared
}

New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot "data") -Force | Out-Null
$env:CS_DB = Join-Path $PSScriptRoot "data\cs.sqlite3"
$env:PORT = "3000"
$env:CS_SECURE_COOKIE = "1"

$server = $null
try {
    $server = Start-Process -FilePath "py" -ArgumentList "-3", "app.py" -WorkingDirectory $PSScriptRoot -PassThru -WindowStyle Hidden
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 300
        try {
            Invoke-WebRequest -Uri "http://127.0.0.1:3000/api/me" -UseBasicParsing -TimeoutSec 1 | Out-Null
            $ready = $true
            break
        } catch {
            if ($server.HasExited) { throw "The HANARO server could not start." }
        }
    }
    if (-not $ready) { throw "The HANARO server did not become ready." }

    Write-Host ""
    Write-Host "[HANARO] The HTTPS sharing address will appear below."
    Write-Host "[HANARO] Share only the https://...trycloudflare.com address with approved members."
    Write-Host "[HANARO] The address changes whenever this program restarts."
    Write-Host "[HANARO] Keep this window open. Press Ctrl+C to stop external access."
    Write-Host ""
    & $cloudflared tunnel --url "http://127.0.0.1:3000" --no-autoupdate
} finally {
    if ($server -and -not $server.HasExited) {
        Stop-Process -Id $server.Id -Force
    }
}
