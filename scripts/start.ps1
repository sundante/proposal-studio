# Start Proposal Studio: makes sure Ollama runs, then opens the app (http://127.0.0.1:8765, this
# machine only). The app asks which workspace folder to trust and work in.
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
& (Join-Path $Root '.venv\Scripts\studio.exe') ui @args
