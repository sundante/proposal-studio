# Start Proposal Studio (Open WebUI on http://localhost:8080, bound to this machine only).
# Run from PowerShell:  powershell -ExecutionPolicy Bypass -File scripts\start.ps1
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
foreach ($line in Get-Content (Join-Path $PSScriptRoot 'offline.env')) {
    $trimmed = $line.Trim()
    if ($trimmed -and -not $trimmed.StartsWith('#') -and $trimmed.Contains('=')) {
        $name, $value = $trimmed.Split('=', 2)
        Set-Item -Path "Env:$name" -Value $value
    }
}
$env:STUDIO_HOME = $Root
if (-not $env:DATA_DIR) { $env:DATA_DIR = Join-Path $Root '.owui-data' }
New-Item -ItemType Directory -Force -Path $env:DATA_DIR | Out-Null

try {
    Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 3 | Out-Null
    Write-Host 'Ollama is already running (OLLAMA_* settings only apply if it is started here; quit the tray app to use them).'
} catch {
    $Ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source
    if (-not $Ollama) { $Ollama = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe' }
    Write-Host 'Starting Ollama (one model at a time, cloud off)...'
    Start-Process -FilePath $Ollama -ArgumentList 'serve' -WindowStyle Hidden
    Start-Sleep -Seconds 4
}
& (Join-Path $Root '.venv\Scripts\studio.exe') doctor
Write-Host "Open http://localhost:8080 and pick the 'Proposal Studio' model."
& (Join-Path $Root '.venv\Scripts\open-webui.exe') serve --host 127.0.0.1 --port 8080
