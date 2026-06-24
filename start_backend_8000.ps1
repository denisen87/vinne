$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root "backend"
$python = "C:\Program Files\Python311\python.exe"

if (-not (Test-Path $backend)) {
  Write-Host "Fant ikke backend-mappen: $backend" -ForegroundColor Red
  exit 1
}

if (-not (Test-Path $python)) {
  $python = "python"
}

try {
  $health = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8000/health" -TimeoutSec 2
  if ($health.StatusCode -eq 200) {
    Write-Host "Backend kjører allerede på http://127.0.0.1:8000" -ForegroundColor Green
    Write-Host "Ikke start en ny på 8010/8011. Bruk 8000 i frontend."
    exit 0
  }
} catch {
  $conn = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8000 -ErrorAction SilentlyContinue
  if ($conn) {
    Write-Host "Port 8000 er opptatt, men /health svarer ikke." -ForegroundColor Yellow
    Write-Host "PID på port 8000: $($conn.OwningProcess)"
    Write-Host "Stopp den prosessen hvis du vil starte backend på nytt."
    exit 1
  }
}

Push-Location $backend
try {
  Write-Host "Starter backend på http://127.0.0.1:8000" -ForegroundColor Cyan
  & $python -m uvicorn main:app --host 127.0.0.1 --port 8000
} finally {
  Pop-Location
}
