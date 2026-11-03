# Proposal Studio setup for Windows 11. Idempotent, needs internet, NO admin rights.
# Creates .venv (Python 3.11/3.12), installs open-webui + studio, pulls the Ollama models.
# Run from PowerShell:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$OpenWebUIVersion = if ($env:OPEN_WEBUI_VERSION) { $env:OPEN_WEBUI_VERSION } else { '0.13.0' }
$Problems = New-Object System.Collections.Generic.List[string]
$Py = Join-Path $Root '.venv\Scripts\python.exe'

function Find-Python {
    foreach ($v in @('3.11', '3.12')) {
        if (Get-Command py -ErrorAction SilentlyContinue) {
            & py "-$v" -c "import sys" 2>$null
            if ($LASTEXITCODE -eq 0) { return @('py', "-$v") }
        }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $ver = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
        if ($ver -in @('3.11', '3.12')) { return @('python') }
    }
    return $null
}

if (-not (Test-Path $Py)) {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Write-Host 'Creating .venv with uv (Python 3.11)...'
        & uv venv --python 3.11 .venv
    } else {
        $found = Find-Python
        if (-not $found) {
            Write-Host 'Python 3.11 or 3.12 is required. Install it for your user from python.org (no admin), then re-run.'
            exit 1
        }
        Write-Host "Creating .venv with $($found -join ' ')..."
        if ($found.Count -gt 1) { & $found[0] $found[1] -m venv .venv } else { & $found[0] -m venv .venv }
    }
    if (-not (Test-Path $Py)) { $Problems.Add('could not create .venv') }
}

function Install-Package([string[]]$PkgArgs) {
    if (Get-Command uv -ErrorAction SilentlyContinue) { & uv pip install --python $Py @PkgArgs }
    else { & $Py -m pip install @PkgArgs }
    return ($LASTEXITCODE -eq 0)
}
Write-Host "Installing open-webui==$OpenWebUIVersion and studio (this can take a while)..."
if (-not (Install-Package @("open-webui==$OpenWebUIVersion"))) { $Problems.Add('pip install open-webui failed') }
if (-not (Install-Package @('-e', $Root))) { $Problems.Add('pip install studio failed') }

$Ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source
if (-not $Ollama) {
    $candidate = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if (Test-Path $candidate) { $Ollama = $candidate }
}
if ($Ollama) {
    try { Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 3 | Out-Null }
    catch {
        Write-Host 'Starting Ollama...'
        $env:OLLAMA_NO_CLOUD = '1'
        Start-Process -FilePath $Ollama -ArgumentList 'serve' -WindowStyle Hidden
        Start-Sleep -Seconds 4
    }
    $models = & $Py -c "from studio.config import load_config; print(' '.join(sorted({r.model for r in load_config().models.roles.values()})))"
    foreach ($m in ($models -split ' ')) {
        if ($m) {
            Write-Host "ollama pull $m"
            & $Ollama pull $m
            if ($LASTEXITCODE -ne 0) { $Problems.Add("ollama pull $m failed") }
        }
    }
} else {
    $Problems.Add('Ollama not found: install it for your user from https://ollama.com (no admin), then re-run')
}

Write-Host ''
if ($Problems.Count -eq 0) {
    Write-Host 'Setup complete. Next: scripts\start.ps1, then open http://localhost:8080'
} else {
    Write-Host 'Setup finished with problems:'
    foreach ($p in $Problems) { Write-Host "  - $p" }
    exit 1
}
